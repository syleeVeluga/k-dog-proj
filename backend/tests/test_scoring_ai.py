"""V3 contract fixtures and injected transport; no real provider validation."""

import copy
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import analysis, scoring_ai, settings_v3, usage
from app.gemini import GeminiObserver, ProviderError
from app.input_models_v3 import RunCreateV3
from app.storage import encode, uid
from app.worker import Worker
from tests.test_runs_v3 import RunTests


def missing(code):
    return {"code": code, "value": None, "status": "unobserved", "reason": "합성 응답: 실제 관찰 불가",
        "opportunity": "unknown", "validity": "unknown", "welfare_stopped": False, "evidence": [],
        "latency_not_occurred": False, "actual_latency_seconds": None, "vocalization": None}


class SyntheticObserver:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def request_v3(self, files, config, context, schema, guard):
        guard()
        self.calls.append((config, context, files))
        if context.get("items"):
            codes = [item["code"] for item in context["items"]]
            if self.fail in codes:
                raise ProviderError("fixture_request_failed", usage={"provider_usage": {"total_input_tokens": 7}})
            rows = [missing(code) for code in codes]
            for item in rows:
                if item["code"] in ("바5", "개5", "개6"):
                    clip = next(clip for clip in context["clips"] if "entry" in clip["window_ids"])
                    item.update(value={"바5": 0, "개5": -1, "개6": 1}[item["code"]], status="observed", reason=None,
                        opportunity="present", validity="valid", evidence=[{"clip_name": clip["name"], "window_id": "entry",
                        "start_seconds": 0, "end_seconds": 1, "observed_seconds": 1, "note": "합성 1초 근거"}])
            result = {"observations": rows}
        else:
            result = {"expected_revision": 1, "reason": "합성 판정 계약", "decisions": [{"key": key, "label": None,
                "status": "held", "evidence_codes": [], "counter_codes": [], "counter_note": "합성 자료 근거 없음",
                "opportunity_note": "실자료 판독 미검증", "reason": "다중 실제 근거 부족"} for key in ("attachment", "owner_type", "entry")]}
        return result, {"provider": "gemini", "model": config["model"], "total_input_tokens": 7,
                        "provider_usage": {"total_input_tokens": 7, "total_output_tokens": 3, "total_tokens": 10}}


class AiTests(RunTests):
    def setUp(self):
        super().setUp()
        response = self.client.put(f"/api/cases/{self.item['case_id']}", json={"expected_revision": self.item["input_revision"],
            "participant_id": self.item["participant_id"], "dog_name": self.item["dog_name"],
            "consents": {"analysis_feedback": "confirmed", "stranger_contact": "unknown"}})
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()
        # Build the fixture batch against this new immutable revision using the same actual footage.
        with self.store.connect() as db:
            row = self.store.case(db, self.item["case_id"])
        self.batch = self.batch.model_copy(update={"input_revision": row["input_revision"],
            "input": self.batch.input.model_copy(update={"manifest_ref": row["manifest_ref"], "manifest_hash": row["manifest_hash"]})})
        import hashlib
        self.store.path(self.batch_ref).write_bytes(self.batch.model_dump_json().encode())
        self.batch_hash = hashlib.sha256(self.store.path(self.batch_ref).read_bytes()).hexdigest()
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", row["case_id"], "preprocess.complete", {"ref": self.batch_ref, "hash": self.batch_hash,
                "session_id": self.item["selected_session_id"], "input_revision": row["input_revision"]})
        self.request = RunCreateV3(expected_revision=row["input_revision"], request_id=uid(), preprocess_ref=self.batch_ref, preprocess_hash=self.batch_hash)
        self.pipeline = settings_v3.defaults().model_copy(update={"q11_scope_confirmed": True})
        self.version = settings_v3.save(self.store, settings_v3.AiDraftV3(expected_active="inactive", config=self.pipeline), "developer")["version"]
        settings_v3.activate(self.store, self.version, settings_v3.AiActivateV3(expected_active="inactive"), "developer")
        self.config = scoring_ai.configuration(self.version, self.pipeline)
        self.request = self.request.model_copy(update={"settings_version": self.version})

    def start_ai(self, **updates):
        return scoring_ai.start(self.store, self.item["case_id"], self.item["selected_session_id"], self.request.model_copy(update=updates), self.user)

    def snapshot_group(self, code="바5"):
        run = self.start_ai()
        row = self.read_row(run["run_id"])
        return analysis, scoring_ai.run_v3.snapshot_for(row), next(stage for stage in self.config.stages if stage.stage == "score_v3" and code in stage.item_codes), row

    def test_exact109_schema_rejects_duplicate_unknown_auto_missing_and_negative_range(self):
        _, snapshot, group, row = self.snapshot_group()
        raw, _ = SyntheticObserver().request_v3([], {"model": group.model}, scoring_ai.context(snapshot, group, row), {}, lambda: None)
        normalized = scoring_ai.normalize(snapshot, group, raw)
        self.assertEqual(next(item for item in normalized if item["code"] == "개5")["value"], -1)
        self.assertEqual(next(item for item in normalized if item["code"] == "바5")["value"], 0)
        for mutate in (lambda data: data["observations"].pop(), lambda data: data["observations"].append(data["observations"][0]),
                       lambda data: data["observations"][0].update(code="개26"), lambda data: data["observations"][0].update(code="개20"),
                       lambda data: data["observations"][0].update(value=-99), lambda data: data["observations"][0].update(opportunity="unknown")):
            invalid = copy.deepcopy(raw); mutate(invalid)
            with self.assertRaises(ValueError):
                scoring_ai.normalize(snapshot, group, invalid)
        codes = [code for stage in self.config.stages if stage.stage == "score_v3" for code in stage.item_codes]
        self.assertEqual(len(codes), 109)
        self.assertEqual(len(set(codes)), 109)

    def test_clip_local_source_time_bounds_amount_and_foreign_clip(self):
        _, snapshot, group, row = self.snapshot_group("바13")
        raw = {"observations": [missing(code) for code in group.item_codes]}
        clip = scoring_ai.clips_for(snapshot, group)[0]
        item = next(item for item in raw["observations"] if item["code"] == "바13")
        item.update(value=0, status="observed", reason=None, opportunity="present", validity="valid", evidence=[{
            "clip_name": clip.name, "window_id": "exit", "start_seconds": 1, "end_seconds": 2, "observed_seconds": 1, "note": "클립1~2초"}])
        observed = scoring_ai.normalize(snapshot, group, raw)
        self.assertEqual(next(item for item in observed if item["code"] == "바13")["evidence"][0]["start_seconds"], 83)
        for change in ({"clip_name": "other-case"}, {"end_seconds": 11}, {"observed_seconds": 0}, {"observed_seconds": 2}, {"window_id": "entry"}):
            invalid = copy.deepcopy(raw); next(item for item in invalid["observations"] if item["code"] == "바13")["evidence"][0].update(change)
            with self.assertRaises(ValueError): scoring_ai.normalize(snapshot, group, invalid)

    def test_whole_audio_correct_stranger_exit_and_no_partial_listening(self):
        for code, window_id in (("개49", "stranger"), ("개50", "exit")):
            _, snapshot, group, row = self.snapshot_group(code)
            raw = {"observations": [missing(item) for item in group.item_codes]}
            clip = next(clip for clip in scoring_ai.clips_for(snapshot, group) if window_id in clip.window_ids)
            item = next(item for item in raw["observations"] if item["code"] == code)
            item.update(value=0, status="observed", reason=None, opportunity="present", validity="valid", evidence=[{
                "clip_name": clip.name, "window_id": window_id, "start_seconds": 0, "end_seconds": 10, "observed_seconds": 10, "note": "전체 청취"}],
                vocalization={"clip_name": clip.name, "listened_seconds": 10, "cumulative_vocal_seconds": 0, "whole_interval_judged": True, "note": "합성 무발성"})
            normalized = scoring_ai.normalize(snapshot, group, raw)
            scoring_ai.stored_group(snapshot, group, {"observations": normalized})
            for change in ({"listened_seconds": 1}, {"whole_interval_judged": False}, {"cumulative_vocal_seconds": 10}):
                invalid = copy.deepcopy(raw); next(item for item in invalid["observations"] if item["code"] == code)["vocalization"].update(change)
                with self.assertRaises(ValueError): scoring_ai.normalize(snapshot, group, invalid)

    def test_complete_publication_grant_only_exposure_and_usage_no_duplicate(self):
        run = self.start_ai()
        observer = SyntheticObserver()
        Worker(self.store, observer=observer).once()
        view = scoring_ai.run_v3.view(self.store, run["run_id"], self.user)
        self.assertEqual(view["status"], "succeeded", view)
        self.assertTrue(view["result_available"])
        sheet_id = "ai-" + run["run_id"]
        for client in (self.client, self.reviewer, self.other):
            self.assertEqual(client.get(f"/api/sheets/{sheet_id}").status_code, 403)
            self.assertEqual(client.get(f"/api/basic-results/ai-basic-{run['run_id']}").status_code, 403)
        human = self.submit(self.assign())
        grant = self.client.post(f"/api/sheets/{human['sheet_id']}/grants", json={"expected_revision": human["revision"],
            "target_sheet_id": sheet_id, "target_revision": 1, "reason": "독립 제출 뒤 AI 완료본 공개"})
        self.assertEqual(grant.status_code, 200, grant.text)
        ref = self.reviewer.get(f"/api/sheets/{human['sheet_id']}").json()["grants"][0]["ref"]
        revealed = self.reviewer.post(f"/api/sheets/{human['sheet_id']}/reveal", json={"expected_revision": human["revision"], "ref": ref})
        self.assertEqual(revealed.status_code, 200, revealed.text)
        self.assertEqual(len(revealed.json()["target"]["sheet"]["observations"]), 109)
        self.assertEqual(len(revealed.json()["results"]), 1)
        self.assertEqual(self.reviewer.get(f"/api/sheets/{human['sheet_id']}").json()["document"]["purpose"], "review")
        meters = usage.summarize(self.store)
        self.assertEqual(meters["calls_reserved"], len(observer.calls))
        self.assertEqual(sum(group["meters"]["total_input_tokens"] for group in meters["groups"]), len(observer.calls) * 7)
        self.assertIsNone(meters["complete_meter_cost_estimate"])
        for _, context, _ in observer.calls:
            self.assertNotIn("expert", encode(context))
            self.assertNotIn("event_opinion", encode(context))
        self.assertEqual(self.read_row(run["run_id"])["input_revision"], self.item["input_revision"])
        reopened = self.client.post(f"/api/sheets/{sheet_id}/reopen", json={"expected_revision": 1, "reason": "AI 재개방 금지 회귀"})
        self.assertEqual(reopened.status_code, 403)
        self.assertEqual(next(item for item in self.client.get(self.base + '/sheets').json() if item["sheet_id"] == sheet_id)["rater_kind"], "ai")
        for revision, active in ((1, False), (2, True)):
            changed = self.client.patch(f"/api/sheets/{sheet_id}/assignment", json={"expected_revision": revision,
                "reason": "AI 배정 metadata 회귀", "active": active})
            self.assertEqual(changed.status_code, 200, changed.text)
        viewer = self.reviewer.get(f"/api/sheets/{human['sheet_id']}").json()
        granted = self.client.post(f"/api/sheets/{human['sheet_id']}/grants", json={"expected_revision": viewer["summary"]["revision"],
            "target_sheet_id": sheet_id, "target_revision": 3, "reason": "재활성화 완료본 공개"})
        self.assertEqual(granted.status_code, 200, granted.text)
        new_view = self.reviewer.get(f"/api/sheets/{human['sheet_id']}").json()
        newest = next(link for link in new_view["grants"] if link["revision"] == 3)
        public = self.reviewer.post(f"/api/sheets/{human['sheet_id']}/reveal", json={"expected_revision": new_view["summary"]["revision"], "ref": newest["ref"]})
        self.assertEqual(public.status_code, 200, public.text)
        self.assertEqual(len(public.json()["results"]), 1)
        self.assertEqual(public.json()["results"][0]["input"]["revision"], 1)

    def test_partial_failure_preserves_success_nulls_and_held_judgement(self):
        run = self.start_ai()
        Worker(self.store, observer=SyntheticObserver(fail="바13")).once()
        self.assertEqual(self.read_row(run["run_id"])["status"], "partial_failed")
        with self.store.connect() as db:
            sheet = db.execute("SELECT * FROM score_sheets WHERE sheet_id=?", ("ai-" + run["run_id"],)).fetchone()
        doc = scoring_ai.sheets.read_document(self.store, sheet["manifest_ref"], sheet["manifest_hash"])
        values = {item.code: item for item in doc.sheet.observations}
        self.assertEqual(values["바5"].value, 0)
        self.assertIsNone(values["바13"].value)
        self.assertIn("요청 오류", values["바13"].reason)
        self.assertTrue(doc.ai_failures)
        with self.assertRaises(HTTPException): self.action(run, retry=True)

    def test_pending_schema_repair_does_not_create_program_attempt_then_completes(self):
        run = self.start_ai()
        class RepairObserver(SyntheticObserver):
            def request_v3(self, files, config, context, schema, guard):
                raw, usage = super().request_v3(files, config, context, schema, guard)
                if context.get("items") and context["items"][0]["code"] == "바5" and "repair" not in context:
                    raw["observations"].pop()
                return raw, usage
        worker = Worker(self.store, observer=RepairObserver())
        worker.once()
        self.assertEqual(self.read_row(run["run_id"])["status"], "retry_wait")
        with self.store.connect(write=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM steps WHERE run_id=? AND stage='calculate_v3'", (run["run_id"],)).fetchone()[0], 0)
            db.execute("UPDATE steps SET retry_at='2000-01-01T00:00:00+00:00' WHERE run_id=? AND status='retry_wait'", (run["run_id"],))
        worker.once()
        self.assertEqual(self.read_row(run["run_id"])["status"], "succeeded")

    def test_settings_separate_q11_activation_race_and_consent_block(self):
        developer = self.client_for("developer")
        view = developer.get("/api/developer/settings-v3")
        self.assertEqual(view.status_code, 200, view.text)
        self.assertEqual(self.reviewer.get("/api/developer/settings-v3").status_code, 403)
        invalid = self.pipeline.model_copy(update={"q11_scope_confirmed": False})
        saved = settings_v3.save(self.store, settings_v3.AiDraftV3(expected_active=self.version, config=invalid), "developer")
        with self.assertRaises(HTTPException): settings_v3.activate(self.store, saved["version"], settings_v3.AiActivateV3(expected_active=self.version), "developer")
        self.assertEqual(developer.post(f"/api/developer/settings-v3/{self.version}/trial", json={"group": next(iter(settings_v3.groups())), "mode": "schema"}).json()["status"], "schema_valid")
        self.assertEqual(developer.post(f"/api/developer/settings-v3/{self.version}/trial", json={"group": "legacy", "mode": "schema"}).status_code, 422)
        run = self.start_ai()
        new = settings_v3.save(self.store, settings_v3.AiDraftV3(expected_active=self.version, config=self.pipeline), "developer")["version"]
        settings_v3.activate(self.store, new, settings_v3.AiActivateV3(expected_active=self.version), "developer")
        with self.assertRaises(HTTPException): self.start_ai(request_id=uid())
        Worker(self.store, observer=SyntheticObserver()).once()
        self.assertEqual(self.read_row(run["run_id"])["status"], "succeeded")
        self.assertEqual(json.loads(self.read_row(run["run_id"])["config_snapshot_json"])["active_settings_version"], self.version)

    def test_provider_sampling_nested_meters_incomplete_and_cleanup(self):
        clip = self.batch.clips[0]
        config = self.pipeline.groups[next(iter(settings_v3.groups()))].model_dump()
        requests = []
        def transport(method, url, key, **kwargs):
            requests.append((method, url, kwargs))
            if url.endswith('/upload/v1beta/files'): return {}, {"X-Goog-Upload-URL": "https://generativelanguage.googleapis.com/upload/sample"}
            if 'upload/sample' in url: return {"file": {"name": "files/synthetic", "state": "ACTIVE", "uri": "https://generativelanguage.googleapis.com/v1beta/files/synthetic"}}, {}
            if method == 'DELETE': raise ProviderError("cleanup_failed")
            return {"status": "in_progress", "model": config["model"], "usage": {"total_input_tokens": 7, "input_tokens_by_modality": [{"modality": "video", "tokens": 5}]}}, {}
        with patch("app.secrets.credential", return_value=("secret-never-output", "vault-1")), patch("app.gemini.request", side_effect=transport):
            with self.assertRaises(ProviderError) as failed:
                GeminiObserver(self.store).request_v3([(self.store.path(clip.ref), clip)], config,
                    {"run_id": "synthetic-trial", "audit_actor": "developer"}, {}, lambda: None)
        self.assertTrue(failed.exception.uncertain)
        self.assertEqual(failed.exception.usage["provider_usage"]["input_tokens_by_modality"][0]["tokens"], 5)
        self.assertTrue(failed.exception.usage["remote_cleanup_pending"])
        payload = next(kwargs["data"] for method, url, kwargs in requests if url.endswith('/interactions'))
        self.assertEqual(payload["input"][0]["processing"]["fps"], config["fps"])
        self.assertEqual(payload["input"][0]["resolution"], config["media_resolution"])
        self.assertEqual(payload["input"][0]["name"], clip.name)
        self.assertNotIn("media_resolution", payload["generation_config"])
        self.assertEqual(usage.token_meters({"by_modality": [{"tokens": 5}]}), {"by_modality.0.tokens": 5})
        with patch("app.secrets.credential", return_value=("secret-never-output", "vault-1")), patch("app.gemini.request") as network:
            with self.assertRaises(ProviderError) as oversized:
                GeminiObserver(self.store).request_v3([(self.store.path(clip.ref), clip.model_copy(update={"size_bytes": 2_000_000_001}))],
                    config, {"run_id": "synthetic-limit", "audit_actor": "developer"}, {}, lambda: None)
        self.assertEqual(oversized.exception.code, "v3_file_size_limit")
        network.assert_not_called()

    def test_explicit_reuse_skips_score_calls_and_budget_exhaustion_holds_results(self):
        first = self.start_ai()
        initial = SyntheticObserver()
        Worker(self.store, observer=initial).once()
        reused = self.start_ai(request_id=uid(), reuse_run_id=first["run_id"])
        observer = SyntheticObserver()
        Worker(self.store, observer=observer).once()
        self.assertEqual(self.read_row(reused["run_id"])["status"], "succeeded")
        self.assertEqual(len(observer.calls), 1)  # Fresh basic decision; no copied billing for score groups.
        totals = usage.summarize(self.store)
        self.assertEqual(totals["calls_reserved"], len(initial.calls) + 1)
        self.assertGreater(totals["reused_ai_steps"], 0)
        exhausted = self.enqueue(value=self.request.model_copy(update={"request_id": uid()}), config=self.config.model_copy(update={"max_ai_calls": 1}))
        limited = SyntheticObserver()
        Worker(self.store, observer=limited).once()
        self.assertEqual(len(limited.calls), 1)
        self.assertEqual(self.read_row(exhausted["run_id"])["status"], "partial_failed")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM basic_results WHERE result_id=?", ("ai-basic-" + exhausted["run_id"],)).fetchone()
        result = scoring_ai.judgements.document_for(self.store, row)
        self.assertTrue(all(decision.status == "held" for decision in result.decisions))

    def test_consent_withdrawal_and_same_size_clip_mutation_stop_before_provider(self):
        first = self.start_ai()
        clip = self.batch.clips[0]
        original = self.store.path(clip.ref).read_bytes()
        self.store.path(clip.ref).write_bytes(b'x' * len(original))
        observer = SyntheticObserver()
        Worker(self.store, observer=observer).once()
        self.assertEqual(observer.calls, [])
        self.assertEqual(self.read_row(first["run_id"])["status"], "failed")
        self.store.path(clip.ref).write_bytes(original)
        second = self.start_ai(request_id=uid())
        response = self.client.put(f"/api/cases/{self.item['case_id']}", json={"expected_revision": self.item["input_revision"],
            "participant_id": self.item["participant_id"], "dog_name": self.item["dog_name"],
            "consents": {"analysis_feedback": "declined", "stranger_contact": "unknown"}})
        self.assertEqual(response.status_code, 200, response.text)
        Worker(self.store, observer=observer).once()
        self.assertEqual(observer.calls, [])
        self.assertEqual(self.read_row(second["run_id"])["status"], "failed")

    def test_consent_withdrawal_inside_publication_window_never_publishes(self):
        run = self.start_ai()
        original = scoring_ai.password_hash
        def withdraw(secret):
            response = self.client.put(f"/api/cases/{self.item['case_id']}", json={"expected_revision": self.item["input_revision"],
                "participant_id": self.item["participant_id"], "dog_name": self.item["dog_name"],
                "consents": {"analysis_feedback": "declined", "stranger_contact": "unknown"}})
            self.assertEqual(response.status_code, 200, response.text)
            return original(secret)
        with patch("app.scoring_ai.password_hash", side_effect=withdraw):
            Worker(self.store, observer=SyntheticObserver()).once()
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM score_sheets WHERE sheet_id=?", ("ai-" + run["run_id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM basic_results WHERE result_id=?", ("ai-basic-" + run["run_id"],)).fetchone()[0], 0)
        self.assertEqual(self.read_row(run["run_id"])["status"], "failed")

    def test_requestor_deactivated_inside_publication_window_never_publishes(self):
        run = self.start_ai()
        original = scoring_ai.password_hash
        def deactivate(secret):
            with self.store.connect(write=True) as db:
                db.execute("UPDATE users SET active=0 WHERE username='operator'")
            return original(secret)
        with patch("app.scoring_ai.password_hash", side_effect=deactivate):
            Worker(self.store, observer=SyntheticObserver()).once()
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM score_sheets WHERE sheet_id=?", ("ai-" + run["run_id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM basic_results WHERE result_id=?", ("ai-basic-" + run["run_id"],)).fetchone()[0], 0)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(AiTests(name) for name in AiTests.__dict__ if name.startswith("test_"))
