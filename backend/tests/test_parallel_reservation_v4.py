"""Deterministic reservation races; synthetic transport only."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import analysis, gemini_keys
from app.gemini import ProviderError
from app.maintenance import runtime_lock
from app.worker import Worker
from tests import test_run_v4 as run_fixture


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = run_fixture.RunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store

    def claimed(self, limit=3):
        self.fixture.enqueue(config=self.fixture.config.model_copy(update={"max_ai_calls": limit}))
        return analysis.claim(self.store)

    def test_last_budget_slot_has_one_sender_under_four_way_race(self):
        row = self.claimed(1)
        worker, ready, sent = Worker(self.store), threading.Barrier(4), []
        def work(step):
            ready.wait(timeout=10)
            worker.reserve_call(row, step)
            sent.append(step["step_id"])
            return {"usage": {}}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = [pool.submit(worker.stage, row, "score_v4", f"branch-{n}", lambda value: value, work) for n in range(4)]
            for result in results:
                result.result(timeout=15)
        self.assertEqual(len(sent), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT SUM(call_reserved) FROM steps").fetchone()[0], 1)

    def test_same_branch_cannot_recover_or_send_while_current_attempt_is_live(self):
        row = self.claimed()
        worker, started, release, sent = Worker(self.store), threading.Event(), threading.Event(), []
        def work(step):
            worker.reserve_call(row, step)
            sent.append(step["step_id"])
            started.set()
            self.assertTrue(release.wait(timeout=10))
            return {"usage": {}}
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(worker.stage, row, "score_v4", "same", lambda value: value, work)
            self.assertTrue(started.wait(timeout=10))
            try:
                self.assertIsNone(worker.stage(row, "score_v4", "same", lambda value: value, work))
            finally:
                release.set()
            first.result(timeout=10)
        self.assertEqual(len(sent), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps").fetchone()[0], 1)

    def test_worker_boundary_covers_python_entrypoint_and_drain(self):
        with runtime_lock(self.store, "worker-execution"), self.assertRaises(HTTPException):
            Worker(self.store).once()
        self.assertFalse(Worker(self.store).once())

    def test_concurrent_recovery_never_retries_an_already_adopted_attempt(self):
        row = self.claimed()
        worker, branch, sends = Worker(self.store), self.fixture.config.stages[0].key, []
        def interrupted(step):
            worker.reserve_call(row, step)
            analysis.write_output(self.store, row, step, {"synthetic": "valid", "usage": {}})
            raise OSError("synthetic crash after immutable output")
        with self.assertRaises(OSError):
            worker.stage(row, "score_v4", branch, lambda value: value, interrupted)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE run_id=?", (row["run_id"],))
        current = analysis.claim(self.store)
        ready, adopted, lock, calls = threading.Barrier(2), threading.Event(), threading.Lock(), []
        original_adopt = analysis.adopt
        def adopt(*args):
            with lock:
                number = len(calls)
                calls.append(number)
            ready.wait(timeout=10)
            if number:
                self.assertTrue(adopted.wait(timeout=10))
            try:
                return original_adopt(*args)
            finally:
                if not number:
                    adopted.set()
        def forbidden(step):
            sends.append(step)
            return {"synthetic": "valid", "usage": {}}
        with patch("app.worker.adopt", side_effect=adopt), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker.stage, current, "score_v4", branch, lambda value: value, forbidden) for _ in range(2)]
            for future in futures:
                future.result(timeout=15)
        self.assertEqual(sends, [])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps").fetchone()[0], 1)

    def test_shared_cooldown_wait_is_interruptible_before_reservation(self):
        row = self.claimed()
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", row["run_id"], "gemini.cooldown", {"retry_at": "2999-01-01T00:00:00Z"})
        def stop(_):
            self.fixture.action(row["run_id"])
        with patch("app.worker.time.sleep", side_effect=stop), self.assertRaises(HTTPException):
            Worker(self.store).wait_for_provider(row, {}, lambda: analysis.guard(self.store, row["run_id"], row["claim_token"]))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps WHERE call_reserved=1").fetchone()[0], 0)

    def test_cooldown_created_between_wait_and_reservation_cannot_send(self):
        row, sent = self.claimed(), []
        class Observer:
            def request_v4(self, *args):
                sent.append(True)
                return {}, {}
        worker = Worker(self.store, observer=Observer())
        original_wait = worker.wait_for_provider
        def race(*args):
            original_wait(*args)
            with self.store.connect(write=True) as db:
                self.store.audit(db, "operator", row["run_id"], "gemini.cooldown", {"retry_at": "2999-01-01T00:00:00Z"})
        def stop(_):
            self.fixture.action(row["run_id"])
        with patch.object(worker, "wait_for_provider", side_effect=race), patch("app.worker.time.sleep", side_effect=stop):
            with self.assertRaises(HTTPException):
                worker.gemini_request(row, {}, [], {}, {}, {}, lambda: worker.check(row))
        self.assertEqual(sent, [])

    def test_simultaneous_primary_failures_decide_backup_once(self):
        row = self.claimed(10)
        ready = threading.Barrier(4)
        def fallback(number):
            exc = ProviderError("primary_denied", http_status=403,
                usage={"credential_slot": "primary", "operation_phase": "inference", "audit_actor": "operator"})
            ready.wait(timeout=10)
            with self.store.connect(write=True) as db:
                accepted = gemini_keys.request_fallback(self.store, db, row, {"step_id": str(number), "attempt": 1}, exc, 3,
                    retry_at=f"2999-01-01T00:00:0{number}Z")
                return accepted, exc.usage["fallback_retry_at"]
        with patch("app.gemini_keys.secrets._credential", return_value=("synthetic-key", "synthetic-ref")):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(fallback, range(4)))
                self.assertTrue(all(result[0] for result in results))
                self.assertEqual(len({result[1] for result in results}), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='gemini.fallback_requested'").fetchone()[0], 1)
            self.assertEqual(gemini_keys.selection(db, row["run_id"])["credential_slot"], "backup")
