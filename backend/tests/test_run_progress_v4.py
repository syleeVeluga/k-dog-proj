import json
from types import SimpleNamespace
import unittest

from app import analysis, run_v4
from app.domain.runs_v4 import RunConfigV4, RunViewV4
from app.intake import new_session
from app.storage import now, uid
from tests import test_run_v4 as helpers


class RunProgressV4Tests(unittest.TestCase):
    setUp = helpers.RunV4Tests.setUp
    current = helpers.RunV4Tests.current
    enqueue = helpers.RunV4Tests.enqueue
    row = helpers.RunV4Tests.row

    def add_step(self, run_id, stage, key, state, attempt=1, claim="claim", **changes):
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,created_at,updated_at,usage_json,retry_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uid(), run_id, stage, key, attempt, state, claim, now(), now(),
                       json.dumps(changes.get("usage", {})), changes.get("retry_at")))

    def update(self, run_id, status="running", claim="claim", lease=None):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET status=?,claim_token=?,lease_expires_at=? WHERE run_id=?",
                       (status, claim, lease or analysis.later(180), run_id))

    def view(self, run_id):
        return RunViewV4.model_validate(run_v4.view(self.store, run_id, self.user))

    def test_fixed_plan_waiting_keys_and_private_read_only_dto(self):
        run = self.enqueue()
        with self.store.connect() as db:
            before = [tuple(row) for row in db.execute("SELECT * FROM changes")]
        value = self.view(run["run_id"])
        self.assertEqual(value.requested_by, "operator")
        self.assertEqual([stage.stage for stage in value.progress.stages], ["score_v4", "calculate_v4", "attachment_v4", "publish_v4"])
        self.assertEqual(value.progress.stages[0].keys[0].key, self.config.stages[0].key)
        self.assertEqual(value.progress.stages[0].waiting, 1)
        self.assertIsNone(value.progress.current_stage)
        self.assertFalse(value.progress.state_uncertain)
        serialized = value.model_dump_json()
        for private in ("claim_token", "lease_expires_at", "output_ref", "prompt", "observations", "preprocess_ref"):
            self.assertNotIn(private, serialized)
        with self.store.connect() as db:
            self.assertEqual(before, [tuple(row) for row in db.execute("SELECT * FROM changes")])

    def test_all_planned_stages_advance_and_original_requester_survives_retry_actor(self):
        seed = self.config.stages[0].model_dump(mode="json")
        planned = [{**seed, "stage": stage, "key": "session" if stage != "score_v4" else seed["key"],
                    **({"provider": "program", "model": "program", "provider_call": False} if stage in ("calculate_v4", "publish_v4") else {})}
                   for stage in ("score_v4", "calculate_v4", "attachment_v4", "publish_v4")]
        config = RunConfigV4.model_validate_json(json.dumps({**self.config.model_dump(mode="json"), "stages": planned}))
        run_id = self.enqueue(config=config)["run_id"]
        self.update(run_id)
        for index, plan in enumerate(config.stages):
            self.add_step(run_id, plan.stage, plan.key, "running")
            view = self.view(run_id)
            self.assertEqual(view.progress.current_stage, plan.stage)
            self.assertEqual(sum(stage.completed for stage in view.progress.stages), index)
            with self.store.connect(write=True) as db:
                db.execute("UPDATE steps SET status='succeeded' WHERE run_id=? AND stage=?", (run_id, plan.stage))
        with self.store.connect(write=True) as db:
            self.store.audit(db, "reviewer", run_id, "run_v4.retry", {"reason": "합성 재시도 행위자"})
        self.update(run_id, "succeeded")
        view = self.view(run_id)
        self.assertEqual(view.requested_by, "operator")
        self.assertEqual(sum(stage.completed for stage in view.progress.stages), 4)
        self.assertIsNone(view.progress.current_stage)

    def test_only_current_claim_with_live_lease_is_running(self):
        run_id = self.enqueue()["run_id"]
        planned = self.config.stages[0]
        self.add_step(run_id, planned.stage, planned.key, "running")
        self.update(run_id)
        self.assertEqual(self.view(run_id).progress.current_stage, "score_v4")
        for status, claim, lease in (("queued", "claim", None), ("retry_wait", "claim", None),
                                     ("stopped", "claim", None), ("running", "new-claim", None),
                                     ("running", "claim", "2000-01-01T00:00:00Z")):
            self.update(run_id, status, claim, lease)
            value = self.view(run_id)
            self.assertIsNone(value.progress.current_stage)
            self.assertEqual(value.progress.stages[0].running, 0)
            self.assertEqual(value.progress.state_uncertain, status == "running")

    def test_latest_valid_attempts_retry_time_and_reuse_are_not_double_counted(self):
        run_id = self.enqueue()["run_id"]
        planned = self.config.stages[0]
        self.add_step(run_id, planned.stage, planned.key, "superseded", retry_at=analysis.later(600))
        due = analysis.later(300)
        self.add_step(run_id, planned.stage, planned.key, "retry_wait", attempt=2, retry_at=due)
        self.update(run_id, "retry_wait")
        value = self.view(run_id)
        self.assertEqual(value.retry_at, due)
        self.assertEqual(value.progress.stages[0].waiting, 1)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET status='superseded' WHERE run_id=? AND attempt=2", (run_id,))
        self.add_step(run_id, planned.stage, planned.key, "succeeded", attempt=3, usage={"reused": True})
        self.update(run_id, "partial_failed")
        value = self.view(run_id)
        self.assertEqual(value.progress.stages[0].completed, 1)
        self.assertTrue(value.progress.stages[0].keys[0].reused)
        self.assertIsNone(value.retry_at)

    def test_resolver_is_actor_scoped_after_input_session_and_settings_changes(self):
        run_id = self.enqueue()["run_id"]
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            session = new_session(note="다음 합성 회차")
            manifest.sessions.append(session)
            manifest.selected_session_id = session.session_id
            self.store.save(db, row, manifest, "reviewer", "session.add")
        found = run_v4.by_request(self.store, self.case_id, self.session_id, self.request.request_id, self.user)
        self.assertTrue(found["found"])
        self.assertEqual(found["run"]["run_id"], run_id)
        self.assertTrue(found["run"]["outdated"])
        reviewer = SimpleNamespace(username="reviewer", role="reviewer")
        self.assertFalse(run_v4.by_request(self.store, self.case_id, self.session_id, self.request.request_id, reviewer)["found"])
        self.assertFalse(run_v4.by_request(self.store, self.case_id, self.session_id, "missing", self.user)["found"])
        self.assertEqual(run_v4.view(self.store, run_id, reviewer)["requested_by"], "operator")
