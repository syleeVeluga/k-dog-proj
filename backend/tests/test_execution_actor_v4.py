"""Shared retries keep source identity and authenticate the actual retry actor."""
import unittest
from types import SimpleNamespace

from app import run_v4, report_runs_v4 as reports
from app.domain.runs_v4 import ActionV4
from app.worker import Worker
from tests import test_run_v4 as run_support, test_report_runs_v4 as report_support


class ExecutionActorV4Tests(unittest.TestCase):
    def fixture(self, kind):
        value = (run_support.RunV4Tests if kind == "run" else report_support.ReportRunV4Tests)()
        value.setUp()
        self.addCleanup(value.doCleanups)
        return value

    def prepare_retry(self, value, kind):
        created = value.enqueue()
        run_id = created["run_id"]
        original = value.row(run_id)["input_snapshot_json"]
        value.action(run_id)
        with value.store.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO users(username,role,password_hash) VALUES('shared-retry','reviewer','synthetic-no-login')")
            db.execute("UPDATE users SET active=0 WHERE username=?", (value.user.username,))
        actor = SimpleNamespace(username="shared-retry", role="reviewer")
        expected = value.row(run_id)["updated_at"]
        if kind == "run":
            run_v4.action(value.store, run_id, ActionV4(expected_updated_at=expected, reason="다른 업무 사용자의 합성 재시도"), actor, retry=True)
        else:
            reports.action(value.store, run_id, reports.ReportActionV4(expected_updated_at=expected, reason="다른 업무 사용자의 합성 재시도"), actor, retry=True)
        self.assertEqual(value.row(run_id)["input_snapshot_json"], original)
        return run_id, actor

    def test_other_actor_retries_run_from_inactive_creator(self):
        value = self.fixture("run")
        run_id, actor = self.prepare_retry(value, "run")
        self.assertTrue(value.worker().once())
        self.assertEqual(value.row(run_id)["status"], "succeeded")
        with value.store.connect() as db:
            self.assertEqual(db.execute("SELECT actor FROM changes WHERE target=? AND action='run_v4.retry'", (run_id,)).fetchone()[0], actor.username)

    def test_other_actor_retries_report_and_is_actual_issuer(self):
        value = self.fixture("report")
        run_id, actor = self.prepare_retry(value, "report")
        value.work()
        self.assertEqual(value.row(run_id)["status"], "succeeded")
        data, _, _ = reports.download(value.store, value.case_id, value.session_id, run_id, "pdf", actor)
        self.assertTrue(data.startswith(b"%PDF"))
        with value.store.connect() as db:
            self.assertEqual(db.execute("SELECT actor FROM changes WHERE target=? AND action='report.s1.issue'", (run_id,)).fetchone()[0], actor.username)

    def test_inactive_current_retry_actor_cannot_adopt_output(self):
        for kind in ("run", "report"):
            with self.subTest(kind=kind):
                value = self.fixture(kind)
                run_id, actor = self.prepare_retry(value, kind)
                with value.store.connect(write=True) as db:
                    db.execute("UPDATE users SET active=0 WHERE username=?", (actor.username,))
                if kind == "run":
                    value.worker().once()
                else:
                    Worker(value.store).once()
                self.assertIn(value.row(run_id)["status"], ("failed", "stopped"))
                self.assertIsNone(value.row(run_id)["result_ref"])


if __name__ == "__main__":
    unittest.main()
