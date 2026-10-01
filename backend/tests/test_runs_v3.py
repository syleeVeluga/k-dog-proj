"""Execution fences with synthetic immutable files and Python-only work injection."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import analysis, maintenance, preprocess_v3, run_v3
from app.domain.preprocess_v3 import BatchV3
from app.domain.runs_v3 import ReuseV3, RunConfigV3
from app.gemini import ProviderError
from app.input_models import UserView
from app.input_models_v3 import RunActionV3, RunCreateV3
from app.storage import Store, encode, now, uid
from app.worker import Worker
from tests.test_sheets import SheetTests


class RunTests(SheetTests):
    def setUp(self):
        super().setUp()
        self.user = UserView(username="operator", role="operator", active=True)
        with self.store.connect() as db:
            row = self.store.case(db, self.item["case_id"])
            session = self.store.manifest(row).sessions[0]
        plan = preprocess_v3.window_plan(session)
        folder = f"clips/{row['case_id']}/{session.session_id}/{uid()}"
        self.store.path(folder).mkdir(parents=True)
        clips = []
        for clip in plan["clips"]:
            ref = f"{folder}/{clip['name']}.mp4"
            raw = b"synthetic immutable clip " + clip["name"].encode()
            self.store.path(ref).write_bytes(raw)
            clips.append({**clip, "fps": "12/1", "ref": ref, "hash": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                "source_time_offset_sec": clip["start_sec"], "decoded_duration_sec": clip["end_sec"] - clip["start_sec"],
                "audio_status": "present", "audio_available_seconds": clip["end_sec"] - clip["start_sec"],
                "audio_listened_seconds": None, "vocal_seconds": None, "quality_events": []})
        self.batch = BatchV3.model_validate_json(encode({
            "rules_version": preprocess_v3.RULES["version"], "rules": preprocess_v3.RULES, **preprocess_v3.ASSET_HASHES,
            "case_id": row["case_id"], "session_id": session.session_id, "batch_id": folder.split("/")[-1],
            "input_revision": row["input_revision"], "input": {"manifest_ref": row["manifest_ref"], "manifest_hash": row["manifest_hash"]},
            "video_id": self.video["video_id"], "source_sha256": self.video["sha256"], "source_duration_sec": 100.0,
            "source_width": 96, "source_height": 64, "source_fps": "12/1", "source_audio": "present", "source_audio_ranges": [],
            "sources": [video.model_dump(mode="json") for video in session.videos], "created_at": now(), "clips": clips,
            "windows": plan["windows"], "recording": session.recording.model_dump(mode="json"), "provisional": True,
            "provisional_reason": "합성 fixture: 공급자 검증 아님", "listening_policy": "whole audio"}))
        self.batch_ref = f"{folder}/clips.json"
        self.store.path(self.batch_ref).write_bytes(self.batch.model_dump_json().encode())
        self.batch_hash = hashlib.sha256(self.store.path(self.batch_ref).read_bytes()).hexdigest()
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", row["case_id"], "preprocess.complete", {"ref": self.batch_ref, "hash": self.batch_hash,
                "session_id": session.session_id, "input_revision": row["input_revision"]})
        self.config = RunConfigV3.model_validate_json(encode({"version": "python-test-only", "max_ai_calls": 3, "stages": [{
            "stage": "score", "key": "entry", "item_codes": ["바5"], "prompt": "synthetic fixture",
            "response_schema": {"type": "object"}, "provider": "python-test-only", "model": "test-injected",
            "production_fps": "native", "request_fps": 12.0, "media_resolution": "original"}]}))
        self.request = RunCreateV3(expected_revision=row["input_revision"], request_id=uid(),
            preprocess_ref=self.batch_ref, preprocess_hash=self.batch_hash)

    def enqueue(self, *, value=None, config=None, reuse=()):
        return run_v3.enqueue(self.store, self.item["case_id"], self.item["selected_session_id"],
            value or self.request, self.user, config or self.config, enabled=True, reuse=reuse)

    def read_row(self, run_id):
        with self.store.connect() as db:
            return dict(db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())

    def action(self, run, retry=False):
        current = run_v3.view(self.store, run["run_id"], self.user)
        return run_v3.action(self.store, run["run_id"], RunActionV3(expected_updated_at=current["updated_at"], reason="합성 명시 요청"), self.user, retry=retry)

    def handler(self, snapshot, group, row):
        def validate(payload):
            if payload.get("fixture") != "valid":
                raise ValueError("incomplete fixture")
            return payload
        return validate, lambda step: {"fixture": "valid", "usage": {"cost": None}}

    def test_idempotency_immutable_migration_future_database_and_inactive_api(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(lambda _: self.enqueue(), range(2)))
        self.assertEqual(runs[0]["run_id"], runs[1]["run_id"])
        for field, value in (("kind", "report_v3"), ("request_id", "other"), ("request_hash", "x"),
                             ("input_hash", "x"), ("input_snapshot_json", "{}"), ("config_snapshot_json", "{}"), ("reuse_manifest_json", "[]")):
            with self.assertRaises(sqlite3.IntegrityError), self.store.connect(write=True) as db:
                db.execute(f"UPDATE runs SET {field}=? WHERE run_id=?", (value, runs[0]["run_id"]))
        with self.assertRaises(HTTPException):
            self.enqueue(config=self.config.model_copy(update={"version": "different"}))
        self.assertEqual(self.client.post(self.base + "/runs-v3", json=self.request.model_dump()).status_code, 503)
        Store(self.root)
        Store(self.root)
        with self.store.connect(write=True) as db:
            db.execute("PRAGMA user_version=99")
        before = (self.root / "kdog.sqlite3").read_bytes()
        with self.assertRaises(ValueError):
            Store(self.root)
        self.assertEqual((self.root / "kdog.sqlite3").read_bytes(), before)

    def test_stale_foreign_manifest_clip_hash_and_revision_during_hash_are_rejected(self):
        with self.assertRaises(HTTPException):
            self.enqueue(value=self.request.model_copy(update={"expected_revision": 1}))
        clip = self.batch.clips[0]
        path = self.store.path(clip.ref)
        original = path.read_bytes()
        path.write_bytes(b"!" * len(original))
        with self.assertRaises(HTTPException):
            self.enqueue()
        path.write_bytes(original)
        manifest_path = self.store.path(self.batch_ref)
        raw = manifest_path.read_bytes()
        manifest_path.write_bytes(raw[:-1] + b" ")
        with self.assertRaises(HTTPException):
            self.enqueue()
        manifest_path.write_bytes(raw)
        original_verify = run_v3.verify_files
        calls = []
        def revise(*args):
            stamps = original_verify(*args)
            calls.append(True)
            # A writer succeeds while the long hash phase runs outside a writer transaction.
            if len(calls) == 1:
                self.client.put(f"/api/cases/{self.item['case_id']}", json={"expected_revision": self.item["input_revision"],
                    "participant_id": "0001", "dog_name": "편집됨"}).raise_for_status()
            return stamps
        with patch("app.run_v3.verify_files", side_effect=revise), self.assertRaises(HTTPException):
            self.enqueue()

    def test_new_and_unknown_kinds_never_use_legacy_and_completion_keeps_display(self):
        run = self.enqueue()
        with patch("app.worker.session_snapshot", side_effect=AssertionError("legacy parser")):
            self.assertTrue(Worker(self.store, v3_work=self.handler).once())
        self.assertEqual(self.read_row(run["run_id"])["status"], "succeeded")
        with self.store.connect(write=True) as db:
            self.assertIsNone(db.execute("SELECT display_run_id FROM cases WHERE case_id=?", (self.item["case_id"],)).fetchone()[0])
            for kind in ("future_unknown", "report_v3"):
                run_id = uid()
                db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,status,created_at,updated_at,kind) "
                    "VALUES(?,?,?,1,'{}','{}','queued',?,?,?)", (run_id, self.item["case_id"], self.item["selected_session_id"], now(), now(), kind))
        with patch("app.worker.session_snapshot", side_effect=AssertionError("legacy parser")):
            Worker(self.store).once()
            Worker(self.store).once()
        with self.store.connect() as db:
            self.assertEqual({r[0] for r in db.execute("SELECT failure_code FROM runs WHERE kind IN ('future_unknown','report_v3')")},
                {"unsupported_run_kind", "v3_report_inactive"})

    def test_claim_expiry_stop_retry_old_token_and_current_input_history(self):
        run = self.enqueue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: analysis.claim(self.store), range(2)))
        self.assertEqual(sum(row is not None for row in claims), 1)
        old = next(row for row in claims if row)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at='1970-01-01' WHERE run_id=?", (run["run_id"],))
        new = analysis.claim(self.store)
        self.assertNotEqual(old["claim_token"], new["claim_token"])
        with self.assertRaises(HTTPException):
            analysis.guard(self.store, old["run_id"], old["claim_token"])
        self.action(run)
        with self.assertRaises(HTTPException):
            analysis.guard(self.store, new["run_id"], new["claim_token"])
        self.action(run, retry=True)
        self.item = self.client.put(f"/api/cases/{self.item['case_id']}", json={"expected_revision": self.item["input_revision"],
            "participant_id": "0001", "dog_name": "실행 후 편집"}).json()
        Worker(self.store, v3_work=self.handler).once()
        status = self.reviewer.get(f"/api/runs-v3/{run['run_id']}")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertTrue(status.json()["outdated"])
        self.assertEqual(status.json()["status"], "succeeded")
        for forbidden in ("payload", "result_ref", "result_hash", "input_snapshot_json", "config_snapshot_json", "usage_json"):
            self.assertNotIn(forbidden, status.text)
        self.assertEqual(self.reviewer.get(f"/api/runs-v3/{run['run_id']}/result").status_code, 404)

    def test_latest_post_write_crash_recovers_without_call_and_incomplete_reserves_unknown_billing(self):
        run = self.enqueue()
        row = analysis.claim(self.store)
        worker = Worker(self.store, v3_work=self.handler)
        validate, _ = self.handler(None, None, row)
        def crash(step):
            worker.reserve_call(row, step)
            analysis.write_output(self.store, row, step, {"fixture": "valid", "usage": {"cost": None}})
            raise OSError("post-write interruption")
        with self.assertRaises(OSError):
            worker.stage(row, "score", "entry", validate, crash)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at='1970-01-01' WHERE run_id=?", (run["run_id"],))
        with patch.object(worker, "v3_work", side_effect=lambda *args: (validate, lambda step: self.fail("must recover"))):
            worker.once()
        self.assertEqual(self.read_row(run["run_id"])["status"], "succeeded")
        another = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}))
        row = analysis.claim(self.store)
        worker = Worker(self.store, v3_work=self.handler)
        def incomplete(step):
            worker.reserve_call(row, step)
            analysis.write_output(self.store, row, step, {"fixture": "incomplete"})
            raise OSError("incomplete output")
        with self.assertRaises(OSError):
            worker.stage(row, "score", "entry", validate, incomplete)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at='1970-01-01' WHERE run_id=?", (another["run_id"],))
        worker.once()
        status = run_v3.view(self.store, another["run_id"], self.user)
        self.assertEqual(status["steps"][0]["status"], "abandoned")
        self.assertTrue(status["steps"][0]["billing_uncertain"])
        self.assertEqual(status["steps"][1]["attempt"], 2)

    def test_attempt_call_and_schema_caps_survive_explicit_retry(self):
        run = self.enqueue()
        worker = Worker(self.store)
        def handler(snapshot, group, row):
            def work(step):
                worker.reserve_call(row, step)
                raise ProviderError("v3_schema_invalid", retryable=True)
            return lambda payload: payload, work
        worker.v3_work = handler
        worker.once()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET retry_at='1970-01-01' WHERE run_id=?", (run["run_id"],))
        worker.once()
        self.assertEqual(self.read_row(run["run_id"])["status"], "failed")
        self.action(run, retry=True)
        worker.once()
        status = run_v3.view(self.store, run["run_id"], self.user)
        self.assertEqual(len(status["steps"]), 2)
        capped = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}), config=self.config.model_copy(update={"max_ai_calls": 1}))
        def unavailable(snapshot, group, row):
            def work(step):
                worker.reserve_call(row, step)
                raise ProviderError("temporary_failure", retryable=True, uncertain=True)
            return lambda payload: payload, work
        worker.v3_work = unavailable
        worker.once()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET retry_at='1970-01-01' WHERE run_id=?", (capped["run_id"],))
        worker.once()
        status = run_v3.view(self.store, capped["run_id"], self.user)
        self.assertEqual(status["steps"][-1]["code"], "call_budget_exhausted")

    def test_explicit_reuse_only_identical_windows_assets_groups_and_sampling(self):
        run = self.enqueue()
        Worker(self.store, v3_work=self.handler).once()
        source = self.read_row(run["run_id"])
        with self.store.connect() as db:
            step = db.execute("SELECT * FROM steps WHERE run_id=?", (run["run_id"],)).fetchone()
        entry = ReuseV3(source_run_id=run["run_id"], step_id=step["step_id"], stage="score", key="entry",
            ref=step["output_ref"], hash=step["output_hash"], compatibility_hash=run_v3.compatibility(run_v3.snapshot_for(source), self.config))
        reused = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}), reuse=(entry,))
        def must_reuse(snapshot, group, row):
            validate, _ = self.handler(snapshot, group, row)
            return validate, lambda step: self.fail("reuse must skip work")
        Worker(self.store, v3_work=must_reuse).once()
        self.assertEqual(self.read_row(reused["run_id"])["status"], "succeeded")
        for field, value in (("prompt", "changed"), ("response_schema", {"type": "array"}), ("model", "other"),
                ("request_fps", 1.0), ("media_resolution", "low"), ("production_fps", "1"), ("item_codes", ("바6",))):
            config = self.config.model_copy(update={"stages": (self.config.stages[0].model_copy(update={field: value}),)})
            with self.assertRaises(HTTPException):
                self.enqueue(value=self.request.model_copy(update={"request_id": uid()}), config=config, reuse=(entry,))
        unrelated = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}))
        Worker(self.store, v3_work=self.handler).once()
        with self.store.connect() as db:
            usage = json.loads(db.execute("SELECT usage_json FROM steps WHERE run_id=?", (unrelated["run_id"],)).fetchone()[0])
        self.assertNotIn("reused", usage)

    def test_backup_restore_hashes_and_latest_deletion_ledger(self):
        run = self.enqueue()
        Worker(self.store, v3_work=self.handler).once()
        with self.store.connect() as db:
            refs = maintenance.references(self.store, db)
        self.assertIn(self.batch_ref, refs)
        self.assertIn(self.read_row(run["run_id"])["result_ref"], refs)
        backup = self.root.parent / uid()
        self.addCleanup(lambda: __import__("shutil").rmtree(backup, ignore_errors=True))
        maintenance.backup(self.store, backup, "admin")
        self.delete_case(self.item)
        destination = self.root.parent / uid()
        self.addCleanup(lambda: __import__("shutil").rmtree(destination, ignore_errors=True))
        maintenance.restore(self.store, backup, destination)
        restored = Store(destination)
        with restored.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
        maintenance.clean(restored, purge_deleted=True)
        with restored.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_older_attempt_is_never_adopted_or_recovered_and_deletion_fences_recovery(self):
        run = self.enqueue()
        row = analysis.claim(self.store)
        worker = Worker(self.store, v3_work=self.handler)
        validate, _ = self.handler(None, None, row)
        saved = []
        def crash(step):
            saved.append(step)
            analysis.write_output(self.store, row, step, {"fixture": "valid"})
            raise OSError("post-write")
        with self.assertRaises(OSError):
            worker.stage(row, "score", "entry", validate, crash)
        ref = f"runs/{row['run_id']}/{saved[0]['step_id']}/output.json"
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,created_at,updated_at) "
                "VALUES(?,?,'score','entry',2,'failed',?,?,?)", (uid(), row["run_id"], row["claim_token"], now(), now()))
        with self.assertRaises(HTTPException):
            analysis.adopt(self.store, row, saved[0], ref, hashlib.sha256(self.store.path(ref).read_bytes()).hexdigest(), {})
        self.action(run)
        self.action(run, retry=True)
        Worker(self.store, v3_work=self.handler).once()
        with self.store.connect() as db:
            states = [(s["attempt"], s["status"]) for s in db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY attempt", (run["run_id"],))]
        self.assertEqual(states, [(1, "running"), (2, "failed"), (3, "succeeded")])
        another = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}))
        row = analysis.claim(self.store)
        with self.assertRaises(OSError):
            worker.stage(row, "score", "entry", validate, crash)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at='1970-01-01' WHERE run_id=?", (another["run_id"],))
        def deleting(snapshot, group, current):
            def validate_after_delete(payload):
                self.delete_case(self.item)
                return payload
            return validate_after_delete, lambda step: self.fail("must not call")
        Worker(self.store, v3_work=deleting).once()
        self.assertEqual(self.read_row(another["run_id"])["status"], "stopped")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM steps WHERE run_id=?", (another["run_id"],)).fetchone()[0], "running")

    def test_wrong_case_batch_and_backup_reference_corruption(self):
        wrong = self.batch.model_copy(update={"case_id": "another-case"})
        ref = self.batch_ref.replace("clips.json", "other/clips.json")
        self.store.path(ref).parent.mkdir()
        raw = wrong.model_dump_json().encode()
        self.store.path(ref).write_bytes(raw)
        altered = self.request.model_copy(update={"preprocess_ref": ref, "preprocess_hash": hashlib.sha256(raw).hexdigest()})
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", self.item["case_id"], "preprocess.complete", {"ref": ref, "hash": altered.preprocess_hash})
        with self.assertRaises(HTTPException):
            self.enqueue(value=altered)
        run = self.enqueue()
        Worker(self.store, v3_work=self.handler).once()
        output = self.store.path(self.read_row(run["run_id"])["result_ref"])
        original = output.read_bytes()
        output.write_bytes(b"!" * len(original))
        with self.assertRaises(HTTPException), self.store.connect() as db:
            maintenance.references(self.store, db)
        output.write_bytes(original)

    def test_explicit_retry_does_not_reset_attempt_budget_and_inactive_handler_is_recorded(self):
        run = self.enqueue()
        worker = Worker(self.store)
        worker.once()
        self.assertEqual(self.read_row(run["run_id"])["failure_code"], "v3_provider_inactive")
        self.action(run, retry=True)
        def failure(snapshot, group, row):
            def work(step):
                raise ProviderError("fixture_failure")
            return lambda payload: payload, work
        worker.v3_work = failure
        for i in range(4):
            worker.once()
            if i < 3:
                self.action(run, retry=True)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps WHERE run_id=?", (run["run_id"],)).fetchone()[0], 3)

    def test_reserved_transport_interruption_and_explicit_stop_keep_billing_unknown(self):
        run = self.enqueue()
        worker = Worker(self.store)
        def interrupted(snapshot, group, row):
            def work(step):
                worker.reserve_call(row, step)
                raise OSError("transport interruption")
            return lambda payload: payload, work
        worker.v3_work = interrupted
        worker.once()
        status = run_v3.view(self.store, run["run_id"], self.user)
        self.assertEqual(status["status"], "failed")
        self.assertTrue(status["steps"][0]["billing_uncertain"])
        with self.store.connect() as db:
            usage = json.loads(db.execute("SELECT usage_json FROM steps WHERE run_id=?", (run["run_id"],)).fetchone()[0])
        self.assertTrue(usage["billing_uncertain"])
        self.assertEqual(usage["code"], "worker_interrupted")
        another = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}))
        row = analysis.claim(self.store)
        def stop(step):
            worker.reserve_call(row, step)
            self.action(another)
            return {"fixture": "valid"}
        validate, _ = self.handler(None, None, row)
        with self.assertRaises(HTTPException):
            worker.stage(row, "score", "entry", validate, stop)
        self.assertTrue(run_v3.view(self.store, another["run_id"], self.user)["steps"][0]["billing_uncertain"])

    def test_candidate_change_after_validation_cannot_be_adopted_during_write_or_recovery(self):
        for recovery in (False, True):
            run = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}))
            row = analysis.claim(self.store)
            worker = Worker(self.store, v3_work=self.handler)
            validate, _ = self.handler(None, None, row)
            original = analysis.write_output
            def changed_write(store, current, step, payload):
                ref, output_hash = original(store, current, step, payload)
                path = store.path(ref)
                value = json.loads(path.read_bytes())
                value["input_hash"] = "f" * 64
                path.write_bytes(encode(value).encode())
                return ref, output_hash
            if not recovery:
                with patch("app.worker.write_output", side_effect=changed_write), self.assertRaises(HTTPException):
                    worker.stage(row, "score", "entry", validate, lambda step: {"fixture": "valid"})
            else:
                def crash(step):
                    original(self.store, row, step, {"fixture": "valid"})
                    raise OSError("post-write")
                with self.assertRaises(OSError):
                    worker.stage(row, "score", "entry", validate, crash)
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE runs SET lease_expires_at='1970-01-01' WHERE run_id=?", (run["run_id"],))
                original_read = analysis.step_output
                def changed_read(store, current, step, **kwargs):
                    output = original_read(store, current, step, **kwargs)
                    if kwargs.get("recover"):
                        value = json.loads(store.path(output[1]).read_bytes())
                        value["input_hash"] = "f" * 64
                        store.path(output[1]).write_bytes(encode(value).encode())
                    return output
                with patch("app.worker.step_output", side_effect=changed_read):
                    Worker(self.store, v3_work=self.handler).once()
                with self.store.connect() as db:
                    self.assertEqual(db.execute("SELECT status FROM steps WHERE run_id=? ORDER BY attempt", (run["run_id"],)).fetchone()[0], "abandoned")
                self.assertEqual(self.read_row(run["run_id"])["status"], "succeeded")
            if not recovery:
                self.action(run)

    def test_legacy_default_and_expired_retry_stay_on_the_existing_worker_path(self):
        run_ids = []
        with self.store.connect(write=True) as db:
            for state in ("retry_wait", "running"):
                run_id = uid()
                run_ids.append(run_id)
                db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,status,"
                    "claim_token,lease_expires_at,created_at,updated_at) VALUES(?,?,?,1,'{}','{}',?,'old','1970-01-01',?,?)",
                    (run_id, self.item["case_id"], self.item["selected_session_id"], state, now(), now()))
        worker = Worker(self.store)
        with patch("app.run_v3.process", side_effect=AssertionError("new parser")), patch.object(worker, "prepare", return_value=None) as prepare:
            worker.once()
            worker.once()
        self.assertEqual(prepare.call_count, 2)
        for run_id in run_ids:
            self.assertEqual(self.read_row(run_id)["kind"], "legacy")
            self.assertEqual(self.read_row(run_id)["status"], "failed")


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(RunTests(name) for name in RunTests.__dict__ if name.startswith("test_"))
