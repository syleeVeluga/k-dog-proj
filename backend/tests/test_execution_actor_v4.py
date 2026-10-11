"""Shared retries keep source identity and authenticate the actual retry actor."""
import unittest
from types import SimpleNamespace

from app import run_v4, report_runs_v4 as reports, scoring_ai_v4, settings_v4
from app.domain.runs_v4 import ActionV4
from app.worker import Worker
from tests import test_run_v4 as run_support, test_report_runs_v4 as report_support
from tests import test_attachment_ai_v4 as attachment_support, test_report_narrative_v4 as narrative_support


class ExecutionActorV4Tests(unittest.TestCase):
    def fixture(self, kind):
        value = (run_support.RunV4Tests if kind == "run" else report_support.ReportRunV4Tests)()
        value.setUp()
        self.addCleanup(value.doCleanups)
        return value

    def prepare_retry(self, value, kind, **options):
        created = value.enqueue(**options)
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

    def test_actual_ai_retry_provider_and_publication_audit_use_retry_actor(self):
        value = self.fixture("run")
        pipeline = settings_v4.defaults()
        pipeline.raw_observation_scope_confirmed = True
        run_id, actor = self.prepare_retry(value, "run", config=scoring_ai_v4.configuration(None, pipeline))
        calls = []

        class Provider:
            def request_v4(self, files, config, context, schema, guard):
                guard()
                calls.append(context["audit_actor"])
                if context.get("task") == "attachment_v4":
                    return attachment_support.selected(context), {}
                observations = [{"code": item["code"], "value": None, "status": "unobserved",
                    "reason": "synthetic: no actual observation"} for item in context["items"]]
                for item in observations:
                    if item["code"] == "개18":
                        definition = next(value for value in context["items"] if value["code"] == "개18")
                        window = next(value["window"] for value in context["windows"] if value["window"]["window_id"] == definition["windows"][0])
                        item.update(value=1, status="observed", opportunity="present", validity="valid", evidence=[{
                            "clip_id": "c1", "window_id": window["window_id"], "start_seconds": window["start_seconds"],
                            "end_seconds": window["end_seconds"], "observed_seconds": window["end_seconds"]-window["start_seconds"],
                            "note": "synthetic reunion approach"}])
                return {**context["identity"], "observations": observations}, {}

        self.assertTrue(Worker(value.store, observer=Provider()).once())
        self.assertEqual(value.row(run_id)["status"], "succeeded")
        self.assertEqual(calls, [actor.username] * 43)
        with value.store.connect() as db:
            self.assertEqual(db.execute("SELECT actor FROM changes WHERE target=? AND action='ai.publish'", (value.case_id,)).fetchone()[0], actor.username)

    def test_actual_narrative_retry_provider_and_issue_use_retry_actor(self):
        value = self.fixture("report")
        value.historical_config.stop()
        run_id, actor = self.prepare_retry(value, "report")
        calls = []

        class Provider:
            def request_v4(self, files, config, context, schema, guard):
                guard()
                calls.append(context["audit_actor"])
                return narrative_support.generated(context), {}

        self.assertTrue(Worker(value.store, observer=Provider()).once())
        self.assertEqual(value.row(run_id)["status"], "succeeded")
        self.assertEqual(calls, [actor.username])
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
