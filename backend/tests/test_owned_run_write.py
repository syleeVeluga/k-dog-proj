"""Owned transaction outcomes on real temporary SQLite, without provider calls."""

import json
import sqlite3
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import analysis
from app.gemini import ProviderError
from app.storage import now, uid
from app.worker import Worker
from tests import test_run_v4


class OwnedRunWriteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_v4.RunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.run = self.fixture.enqueue()
        self.row = analysis.claim(self.store)

    def step(self, row=None):
        row = row or self.row
        value = {"step_id": uid(), "claim_token": row["claim_token"]}
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,created_at,updated_at) "
                       "VALUES(?,?, 'score_v4',?,1,'running',?,?,?)",
                       (value["step_id"], row["run_id"], value["step_id"], row["claim_token"], now(), now()))
        return value

    def test_commit_returns_current_row_and_closes_connection(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET failure_code='current' WHERE run_id=?", (self.row["run_id"],))
        with analysis.owned_write(self.store, self.row, conflict_detail="synthetic fence") as (db, current):
            self.assertEqual(current["failure_code"], "current")
            db.execute("UPDATE runs SET failure_code='committed' WHERE run_id=?", (current["run_id"],))
        self.assertEqual(self.fixture.row(self.row["run_id"])["failure_code"], "committed")
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")

    def test_body_failure_rolls_back_and_closes_connection(self):
        with self.assertRaisesRegex(ValueError, "body failed"):
            with analysis.owned_write(self.store, self.row, conflict_detail="synthetic fence") as (db, current):
                db.execute("UPDATE runs SET failure_code='rollback' WHERE run_id=?", (current["run_id"],))
                raise ValueError("body failed")
        self.assertIsNone(self.fixture.row(self.row["run_id"])["failure_code"])
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")

    def test_changed_claim_stopped_expired_and_missing_run_never_enter_body(self):
        for field, value in (("claim_token", "new-owner"), ("status", "stopped"), ("lease_expires_at", "2000-01-01T00:00:00Z")):
            with self.subTest(field=field):
                with self.store.connect(write=True) as db:
                    db.execute(f"UPDATE runs SET {field}=? WHERE run_id=?", (value, self.row["run_id"]))
                with self.assertRaises(HTTPException) as error:
                    with analysis.owned_write(self.store, self.row, conflict_detail="synthetic fence"):
                        self.fail("invalid ownership entered mutation")
                self.assertEqual((error.exception.status_code, error.exception.detail), (409, "synthetic fence"))
                with self.store.connect(write=True) as db:
                    db.execute(f"UPDATE runs SET {field}=? WHERE run_id=?", (self.row[field], self.row["run_id"]))
        with self.assertRaises(HTTPException):
            with analysis.owned_write(self.store, {**self.row, "run_id": "missing"}, conflict_detail="missing"):
                self.fail("missing run entered mutation")

    def test_current_actor_and_revision_are_rechecked_inside_write(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='operator'")
        with self.assertRaises(HTTPException):
            with analysis.owned_write(self.store, self.row, conflict_detail="actor"):
                self.fail("inactive actor entered mutation")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=1 WHERE username='operator'")
            db.execute("UPDATE cases SET input_revision=input_revision+1 WHERE case_id=?", (self.row["case_id"],))
        with self.assertRaises(HTTPException):
            with analysis.owned_write(self.store, self.row, conflict_detail="revision"):
                self.fail("changed revision entered mutation")

    def test_credential_failure_commits_reservation_and_selection_evidence(self):
        step = self.step()
        def unavailable(store, db, row, step, actor):
            store.audit(db, actor, row["case_id"], "synthetic.selection.failed", {})
            raise ProviderError("synthetic_credential_unavailable")
        with patch("app.worker.gemini_keys.select", side_effect=unavailable):
            with self.assertRaises(ProviderError):
                Worker(self.store).reserve_call(self.row, step, credential_actor="operator")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT call_reserved FROM steps WHERE step_id=?", (step["step_id"],)).fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='synthetic.selection.failed'").fetchone()[0], 1)

    def test_reservation_is_once_per_attempt(self):
        step = self.step()
        worker = Worker(self.store)
        worker.reserve_call(self.row, step)
        with self.assertRaises(HTTPException):
            worker.reserve_call(self.row, step)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT SUM(call_reserved) FROM steps WHERE run_id=?", (self.row["run_id"],)).fetchone()[0], 1)

    def test_once_can_finalize_access_failure_but_never_overwrites_new_claim(self):
        for replaced in (False, True):
            with self.subTest(replaced=replaced):
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE users SET active=1 WHERE username='operator'")
                self.fixture.request = self.fixture.request.model_copy(update={"request_id": uid()})
                run = self.fixture.enqueue()
                def fail(row):
                    step = self.step(row)
                    with self.store.connect(write=True) as db:
                        db.execute("UPDATE steps SET call_reserved=1 WHERE step_id=?", (step["step_id"],))
                        db.execute("UPDATE users SET active=0 WHERE username='operator'")
                        if replaced:
                            db.execute("UPDATE runs SET claim_token='new-owner' WHERE run_id=?", (row["run_id"],))
                    raise HTTPException(403, "synthetic actor revoked")
                worker = Worker(self.store)
                with patch.object(worker, "process", side_effect=fail):
                    self.assertTrue(worker.once())
                result = self.fixture.row(run["run_id"])
                self.assertEqual(result["status"], "running" if replaced else "failed")
                with self.store.connect() as db:
                    usage = json.loads(db.execute("SELECT usage_json FROM steps WHERE run_id=?", (run["run_id"],)).fetchone()[0])
                self.assertEqual(usage.get("billing_uncertain"), None if replaced else True)
