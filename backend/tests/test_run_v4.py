"""S1 infrastructure with synthetic immutable bytes and Python-only provider seams."""

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import analysis, preprocess_v4, run_v4, scoring_ai_v4, settings_v4, uploads
from app.domain.preprocess_v4 import BatchV4
from app.domain.runs_v4 import ActionV4, ReuseV4, RunConfigV4, RunViewV4, StartV4
from app.domain.media_v4 import PreservedMediaRegistrationV4
from app.gemini import ProviderError
from app.input_models import StoredVideo
from app.input_models_v3 import CaseCreateV3
from app.intake import create_case
from app.domain.catalog_v4 import SURVEY_VERSION
from app.storage import Store, encode, now, uid
from app.worker import Worker
from tests.test_scoring_ai_v4 import snapshot as sample_snapshot, group


class RunV4Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-runs-s1-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        self.user = SimpleNamespace(username="operator", role="operator")
        with self.store.connect(write=True) as db:
            for name, role in (("operator", "operator"), ("reviewer", "reviewer"), ("developer", "developer")):
                db.execute("INSERT INTO users(username,role,password_hash) VALUES(?,?,?)", (name, role, "synthetic-no-login"))
            self.case_id = create_case(self.store, db, CaseCreateV3(event_id="SYNTHETIC", participant_id="S1-RUN", dog_name="합성견"), "operator", SURVEY_VERSION, s1=True)
        sample = sample_snapshot()
        raw = b"synthetic source, not a participant video"
        self.store.path("videos/v1.mp4").write_bytes(raw)
        video = StoredVideo(video_id="v1", original_name="synthetic.mp4", storage_ref="videos/v1.mp4", sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            self.session_id = manifest.selected_session_id
            manifest.consents.analysis_feedback = "confirmed"
            manifest.sessions[0].videos = [video]
            manifest.sessions[0].recording_s1 = sample.session.recording_s1
            self.store.save(db, row, manifest, "operator", "synthetic.recording")
        uploads.register_preserved_video(self.store, self.case_id, self.session_id, "v1", PreservedMediaRegistrationV4(
            request_id="register-synthetic", expected_revision=self.current()["input_revision"], camera_id="CAM1", source_kind="original"), "operator")
        with self.store.connect() as db:
            row = self.store.case(db, self.case_id)
            session = self.store.manifest(row).sessions[0]
            files, metadata = preprocess_v4._source_snapshot(self.store, db, self.case_id, session, "operator")
        batch = sample.batch.model_dump(mode="json")
        batch.update(case_id=self.case_id, session_id=self.session_id, input_revision=row["input_revision"],
            input={"ref": row["manifest_ref"], "hash": row["manifest_hash"]}, source_files=[file.model_dump(mode="json") for file in files], source_metadata=list(metadata))
        batch["request"]["expected_revision"] = row["input_revision"]
        for clip in batch["clips"]:
            for kind in ("original", "ai"):
                source = clip[kind]
                data = f"synthetic {kind} derivative".encode()
                path = self.store.path(source["ref"]); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
                source.update(hash=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        self.batch = BatchV4.model_validate_json(encode(batch))
        self.batch_ref = "clips/synthetic/batch.json"
        self.store.path(self.batch_ref).write_bytes(self.batch.model_dump_json().encode())
        self.batch_hash = hashlib.sha256(self.store.path(self.batch_ref).read_bytes()).hexdigest()
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", self.case_id, "preprocess_v4.completed", {"session_id": self.session_id, "batch_id": self.batch.batch_id,
                "claim_token": self.batch.claim_token, "ref": self.batch_ref, "hash": self.batch_hash})
        self.request = StartV4(expected_revision=row["input_revision"], request_id=uid(), preprocess_ref=self.batch_ref, preprocess_hash=self.batch_hash)
        self.config = RunConfigV4(raw_observation_scope_confirmed=True, stages=(group("개5"),), max_ai_calls=3)

    def current(self):
        with self.store.connect() as db:
            return dict(self.store.case(db, self.case_id))

    def enqueue(self, *, value=None, config=None, reuse=()):
        return run_v4.enqueue(self.store, self.case_id, self.session_id, value or self.request, self.user, config or self.config, enabled=True, reuse=reuse)

    def row(self, run_id):
        with self.store.connect() as db:
            return dict(run_v4.row_for(self.store, db, run_id))

    def action(self, run_id, retry=False):
        return run_v4.action(self.store, run_id, ActionV4(expected_updated_at=self.row(run_id)["updated_at"], reason="synthetic explicit action"), self.user, retry=retry)

    def worker(self, handler=None):
        worker = Worker(self.store)
        worker.v4_work = handler or self.handler
        return worker

    def handler(self, snapshot, stage, row):
        def validate(payload):
            if payload.get("synthetic") != "valid":
                raise ValueError("bad synthetic artifact")
            return payload
        def work(step):
            Worker(self.store).reserve_call(row, step)
            return {"synthetic": "valid", "usage": {"cost_usd": None, "timing": {"inference_seconds": .01}}}
        return validate, work

    def due(self, run_id):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET retry_at='2000-01-01T00:00:00Z' WHERE run_id=? AND status='retry_wait'", (run_id,))

    def test_admission_idempotency_immutable_pin_and_private_operational_status(self):
        result = self.enqueue()
        self.assertEqual(self.enqueue()["run_id"], result["run_id"])
        with self.assertRaises(HTTPException):
            self.enqueue(config=self.config.model_copy(update={"max_ai_calls": 2}))
        with self.store.connect(write=True) as db:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE runs SET input_hash=? WHERE run_id=?", ("0" * 64, result["run_id"]))
        self.worker().once()
        view = run_v4.view(self.store, result["run_id"], SimpleNamespace(username="reviewer"))
        self.assertEqual((view["status"], view["reserved_calls"]), ("succeeded", 1))
        self.assertEqual(view["steps"][0]["timing"]["inference_seconds"], .01)
        self.assertIsNone(view["steps"][0]["cost_usd"])
        self.assertNotIn("synthetic", json.dumps(view))
        self.assertNotIn("output_ref", json.dumps(view))
        self.assertNotIn("source_snapshot", json.dumps(view))
        RunViewV4.model_validate(view)

    def test_legacy_kind_tampered_source_and_revision_races_reject(self):
        result = self.enqueue()
        with self.assertRaises(HTTPException):
            run_v4.snapshot_for({**self.row(result["run_id"]), "kind": "scoring_v3"})
        path = self.store.path(self.batch.clips[0].ai.ref)
        path.write_bytes(b"x" * path.stat().st_size)
        with self.assertRaises(HTTPException):
            self.enqueue(value=self.request.model_copy(update={"request_id": uid()}))
        self.assertFalse(self.worker().once() is False)
        self.assertEqual(self.row(result["run_id"])["status"], "failed")

    def test_input_changed_after_hash_fences_admission(self):
        original = run_v4.verify_files
        def change(store, snapshot):
            stamps = original(store, snapshot)
            with store.connect(write=True) as db:
                row = store.case(db, self.case_id)
                manifest = store.manifest(row)
                manifest.sessions[0].note = "synthetic changed input"
                store.save(db, row, manifest, "operator", "synthetic.change")
            return stamps
        with patch.object(run_v4, "verify_files", side_effect=change):
            with self.assertRaises(HTTPException) as caught:
                self.enqueue()
        self.assertEqual(caught.exception.status_code, 409)

    def test_claim_expiry_stop_and_old_token_cannot_adopt(self):
        run = self.enqueue()
        old = analysis.claim(self.store)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE run_id=?", (run["run_id"],))
        current = analysis.claim(self.store)
        self.assertNotEqual(old["claim_token"], current["claim_token"])
        with self.assertRaises(HTTPException):
            self.worker().stage(old, "score_v4", self.config.stages[0].key, lambda value: value, lambda step: {"synthetic": "late"})
        self.action(run["run_id"])
        with self.assertRaises(HTTPException):
            run_v4.finish(self.worker(), current, "succeeded", None)
        self.assertEqual(self.row(run["run_id"])["status"], "stopped")

    def failure_handler(self, code, *, retryable=True, uncertain=False):
        def handler(snapshot, stage, row):
            def work(step):
                Worker(self.store).reserve_call(row, step)
                raise ProviderError(code, retryable=retryable, uncertain=uncertain)
            return lambda payload: payload, work
        return handler

    def test_three_attempt_budget_and_billing_unknown_survive_explicit_retry(self):
        run = self.enqueue()
        worker = self.worker(self.failure_handler("timeout", uncertain=True))
        for _ in range(3):
            self.assertTrue(worker.once()); self.due(run["run_id"])
        self.assertEqual(self.row(run["run_id"])["status"], "failed")
        self.action(run["run_id"], retry=True)
        self.assertTrue(worker.once())
        view = run_v4.view(self.store, run["run_id"], self.user)
        self.assertEqual(len(view["steps"]), 3)
        self.assertTrue(all(step["billing_uncertain"] for step in view["steps"]))

    def test_schema_repair_and_reserved_call_caps(self):
        run = self.enqueue()
        worker = self.worker(self.failure_handler("v4_schema_invalid"))
        for _ in range(2):
            worker.once(); self.due(run["run_id"])
        self.action(run["run_id"], retry=True); worker.once()
        self.assertEqual(len(run_v4.view(self.store, run["run_id"], self.user)["steps"]), 2)
        second = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}), config=self.config.model_copy(update={"max_ai_calls": 1}))
        worker = self.worker(self.failure_handler("timeout", uncertain=True)); worker.once(); self.due(second["run_id"]); worker.once()
        view = run_v4.view(self.store, second["run_id"], self.user)
        self.assertEqual(view["reserved_calls"], 1)
        self.assertEqual(view["steps"][-1]["code"], "call_budget_exhausted")

    def test_stop_during_reserved_work_preserves_unknown_cost_and_no_output(self):
        run = self.enqueue()
        def handler(snapshot, stage, row):
            def work(step):
                Worker(self.store).reserve_call(row, step)
                self.action(row["run_id"])
                return {"synthetic": "valid", "usage": {}}
            return lambda payload: payload, work
        self.worker(handler).once()
        view = run_v4.view(self.store, run["run_id"], self.user)
        self.assertEqual(view["status"], "stopped")
        self.assertTrue(view["steps"][0]["billing_uncertain"])
        self.assertFalse(view["result_available"])

    def test_consent_and_actor_revocation_prevent_claim_and_late_output(self):
        run = self.enqueue()
        def handler(snapshot, stage, row):
            def work(step):
                Worker(self.store).reserve_call(row, step)
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE users SET active=0 WHERE username='operator'")
                return {"synthetic": "valid", "usage": {}}
            return lambda payload: payload, work
        self.worker(handler).once()
        self.assertEqual(self.row(run["run_id"])["status"], "failed")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=1 WHERE username='operator'")
            case = self.store.case(db, self.case_id); manifest = self.store.manifest(case)
            manifest.consents.analysis_feedback = "declined"
            self.store.save(db, case, manifest, "operator", "synthetic.withdraw")
        with self.assertRaises(HTTPException):
            self.action(run["run_id"], retry=True)
        with self.assertRaises(HTTPException):
            self.enqueue(value=self.request.model_copy(update={"request_id": uid()}))

    def test_file_changed_after_validation_cannot_be_adopted(self):
        run = self.enqueue()
        write = analysis.write_output
        def changed(store, row, step, payload):
            result = write(store, row, step, payload)
            path = store.path(self.batch.clips[0].ai.ref)
            path.write_bytes(b"x" * path.stat().st_size)
            return result
        with patch("app.worker.write_output", side_effect=changed):
            self.worker().once()
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps WHERE run_id=? AND status='succeeded'", (run["run_id"],)).fetchone()[0], 0)

    def test_explicit_reuse_requires_identical_settings_and_successful_pinned_artifact(self):
        first = self.enqueue(); self.worker().once()
        with self.store.connect() as db:
            row = run_v4.row_for(self.store, db, first["run_id"])
            step = db.execute("SELECT * FROM steps WHERE run_id=? AND status='succeeded'", (first["run_id"],)).fetchone()
            reuse = ReuseV4(source_run_id=first["run_id"], step_id=step["step_id"], stage="score_v4", key=step["branch_key"], ref=step["output_ref"],
                           hash=step["output_hash"], compatibility_hash=run_v4.compatibility(run_v4.snapshot_for(row), self.config))
        second = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}), reuse=(reuse,))
        def only_reuse(snapshot, stage, row):
            def forbidden(step):
                self.fail("reused work must not call the provider")
            return lambda payload: payload, forbidden
        self.worker(only_reuse).once()
        view = run_v4.view(self.store, second["run_id"], self.user)
        self.assertEqual((view["status"], view["reserved_calls"]), ("succeeded", 0))
        self.assertTrue(view["steps"][0]["reused"])
        with self.assertRaises(HTTPException):
            self.enqueue(value=self.request.model_copy(update={"request_id": uid()}), reuse=(reuse,), config=self.config.model_copy(update={"max_ai_calls": 2}))

    def test_restart_recovers_complete_artifact_without_a_second_call(self):
        run = self.enqueue()
        with patch("app.worker.adopt", side_effect=RuntimeError("synthetic crash before DB adoption")):
            with self.assertRaises(RuntimeError):
                self.worker().once()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE run_id=?", (run["run_id"],))
        def recovered(snapshot, stage, row):
            validate, _ = self.handler(snapshot, stage, row)
            def forbidden(step):
                self.fail("durable artifact must be recovered without another external request")
            return validate, forbidden
        self.worker(recovered).once()
        view = run_v4.view(self.store, run["run_id"], self.user)
        self.assertEqual((view["status"], view["reserved_calls"], len(view["steps"])), ("succeeded", 1, 1))

    def test_restart_after_reservation_preserves_uncertain_attempt_and_call_budget(self):
        run = self.enqueue()
        def interrupted(snapshot, stage, row):
            validate, _ = self.handler(snapshot, stage, row)
            def work(step):
                Worker(self.store).reserve_call(row, step)
                raise RuntimeError("synthetic response lost")
            return validate, work
        with self.assertRaises(RuntimeError):
            self.worker(interrupted).once()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE run_id=?", (run["run_id"],))
        self.worker().once()
        view = run_v4.view(self.store, run["run_id"], self.user)
        self.assertEqual((view["status"], view["reserved_calls"]), ("succeeded", 2))
        self.assertEqual([step["status"] for step in view["steps"]], ["abandoned", "succeeded"])
        self.assertTrue(view["steps"][0]["billing_uncertain"])
        self.assertIsNone(view["steps"][0]["cost_usd"])

    def test_nested_provider_meters_preserve_breakdowns_without_double_counting(self):
        run = self.enqueue()
        def metered(snapshot, stage, row):
            validate, perform = self.handler(snapshot, stage, row)
            def work(step):
                payload = perform(step)
                payload["usage"].update(provider_usage={"total_input_tokens": 10, "total_output_tokens": 4,
                    "total_tokens": 14, "input_tokens_by_modality": {"video_tokens": 8}, "invalid_tokens": True}, total_tokens=999)
                return payload
            return validate, work
        self.worker(metered).once()
        result = RunViewV4.model_validate(run_v4.view(self.store, run["run_id"], self.user))
        step = result.steps[0]
        self.assertEqual((step.input_tokens, step.output_tokens, step.total_tokens), (10, 4, 14))
        self.assertEqual(step.token_meters["input_tokens_by_modality.video_tokens"], 8)
        self.assertNotIn("invalid_tokens", step.token_meters)
        self.assertIsNone(step.cost_usd)

    def test_partial_group_failure_publishes_explicit_nulls_and_preserves_successes(self):
        pipeline = settings_v4.defaults(); pipeline.raw_observation_scope_confirmed = True
        config = scoring_ai_v4.configuration(None, pipeline)
        run = self.enqueue(config=config)
        calls, failed_codes = [], []
        class PartialProvider:
            def request_v4(self, files, config, context, schema, guard):
                guard(); calls.append(context)
                if len(calls) == 1:
                    failed_codes.extend(item["code"] for item in context["items"])
                    raise ProviderError("synthetic_group_failed", retryable=False)
                return {**context["identity"], "observations": [{"code": item["code"], "value": None,
                    "status": "unobserved", "reason": "synthetic observed group fixture"} for item in context["items"]]}, {}
        Worker(self.store, observer=PartialProvider()).once()
        view = RunViewV4.model_validate(run_v4.view(self.store, run["run_id"], self.user))
        self.assertEqual((view.status, view.result_available, view.reserved_calls), ("partial_failed", True, 42))
        self.assertEqual(sum(step.status == "failed" for step in view.steps), 1)
        with self.store.connect() as db:
            ai = db.execute("SELECT * FROM score_sheets WHERE case_id=?", (self.case_id,)).fetchone()
            document = json.loads(self.store.path(ai["manifest_ref"]).read_bytes())
        values = {entry["code"]: entry for entry in document["sheet"]["observations"]}
        for code in failed_codes:
            self.assertIsNone(values[code]["value"])
            self.assertEqual(values[code]["status"], "unobserved")
            self.assertIn("synthetic_group_failed", values[code]["reason"])
        with self.assertRaises(HTTPException):
            self.action(run["run_id"], retry=True)

    def test_actual_handler_calculates_and_publishes_full_s1_with_fake_provider(self):
        pipeline = settings_v4.defaults(); pipeline.raw_observation_scope_confirmed = True
        config = scoring_ai_v4.configuration(None, pipeline)
        run = self.enqueue(config=config)
        calls = []
        class FakeProvider:
            def request_v4(self, files, config, context, schema, guard):
                guard(); calls.append(context)
                return {**context["identity"], "observations": [{"code": item["code"], "value": None,
                    "status": "unobserved", "reason": "synthetic fixture: no actual observation"} for item in context["items"]]}, {"cost_usd": None}
        worker = Worker(self.store, observer=FakeProvider())
        worker.once()
        view = run_v4.view(self.store, run["run_id"], self.user)
        self.assertEqual(view["status"], "succeeded")
        self.assertTrue(view["result_available"])
        self.assertEqual((len(calls), view["reserved_calls"]), (42, 42))
        with self.store.connect() as db:
            ai = db.execute("SELECT * FROM score_sheets WHERE case_id=?", (self.case_id,)).fetchone()
            self.assertIsNotNone(ai)
            document = json.loads(self.store.path(ai["manifest_ref"]).read_bytes())
            self.assertEqual(len(document["sheet"]["observations"]), 86)
            self.assertEqual(document["origin"], "ai_service")
            self.assertEqual(document["ai_run_id"], run["run_id"])
            result = db.execute("SELECT * FROM basic_results WHERE sheet_id=?", (ai["sheet_id"],)).fetchone()
            self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
