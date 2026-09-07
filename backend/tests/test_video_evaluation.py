"""Three-view semantic counterexamples, contracts, recovery and REST wiring."""

import copy
import json
import unittest
from unittest.mock import patch

from app.analysis import (
    claim, later, related_input, split_branch_key, validated_observation, validated_prepared, step_payload, write_output,
)
from app.ledger import branch_items
from app.domain.contracts import BehaviorCatalog
from app.gemini import ProviderError
from app.observation_models import VideoResponse
from app.storage import encode, now, uid
from app.usage import summarize
from app.video_models import Measurement
from tests import test_observation as observation
from tests.video_fixtures import ledger_response, video_response


class DirectObserver:
    def __init__(self):
        self.calls = []
        self.callback = None
        self.ledger_callback = None

    def observe(self, path, media, config, context, guard):
        guard()
        self.calls.append((media.video_id, context, config))
        usage = {"model": "synthetic-test-only", "total_tokens": 10}
        if config.get("ledger"):
            if self.ledger_callback:
                return self.ledger_callback(media, context, guard), usage
            return ledger_response(context), usage
        if self.callback:
            return self.callback(media, context, guard), usage
        return video_response(context), usage

    def branch_calls(self):
        return [c for c in self.calls if "items" in c[1]]

    def ledger_calls(self):
        return [c for c in self.calls if "steps" in c[1]]

    def review_calls(self):
        return [c for c in self.branch_calls() if len(c[1]["items"]) < len(branch_items(c[1]["branch"]))]


def measure(result, item_id, measurements):
    """Branch calls only receive their own items, so a shared callback must tolerate absence."""
    item = next((i for i in result.items if i.item_id == item_id), None)
    if item is not None:
        item.measurements = measurements
    return result


class VideoPipelineTests(unittest.TestCase):
    pipeline_mode = "per_video"
    login = observation.ObservationTests.login
    start = observation.ObservationTests.start
    view = observation.ObservationTests.view
    ready_retries = observation.ObservationTests.ready_retries
    delete_case = observation.ObservationTests.delete_case

    def setUp(self):
        observation.ObservationTests.setUp(self)
        result = self.client.post(self.base + "/videos", content=b"synthetic third view", params={
            "session_id": self.item["selected_session_id"], "camera_id": "CAM-0", "filename": "third.mp4",
            "expected_revision": self.item["input_revision"]})
        self.assertEqual(result.status_code, 201)
        self.item = result.json()
        self.observer = DirectObserver()
        self.worker.observer = self.observer
        self.video_ids = [v["video_id"] for v in self.item["manifest"]["sessions"][0]["videos"]]

    def test_three_views_direct_rubric_no_summary_evaluator_and_no_triple_score(self):
        self.start()
        def views(media, context, guard):
            result = video_response(context, {} if media.video_id == self.video_ids[0] else None)
            result.unconfirmed_conditions = ["이 화각에서는 훈련 구간이 보이지 않습니다."]
            return result
        self.observer.callback = views
        self.worker.once()
        result = self.view()
        self.assertEqual(result["evaluation_mode"], "per_video")
        self.assertEqual(result["status"], "scored")
        self.assertEqual(len(result["video_assessments"]), 6)
        self.assertTrue(all(any(v["original_name"] in condition for v in self.item["manifest"]["sessions"][0]["videos"])
                            for condition in result["unconfirmed_conditions"]))
        self.assertEqual(len(result["scores"]["items"]), 55)
        score = next(i for i in result["scores"]["items"] if i["item_id"] == "BS-01")
        self.assertEqual((score["status"], score["raw_score"]), ("scored", 1.0))
        self.assertEqual(len(self.worker.evaluator.calls), 0)
        self.assertEqual(len(self.observer.ledger_calls()), 3)
        self.assertEqual(len(self.observer.branch_calls()), 6)
        self.assertEqual({len(c[1]["items"]) for c in self.observer.branch_calls()}, {36, 19})
        self.assertEqual({c[1]["branch"] for c in self.observer.branch_calls()}, {"dog", "owner"})
        self.assertTrue(all(len(c[1]["items"][0]["options"]) > 1 for c in self.observer.branch_calls()))
        self.assertTrue(all("survey" not in c[1] for c in self.observer.calls))
        self.assertTrue(all("sampling_static_1fps" in e["quality_flags"] for e in result["evidence"]))
        self.assertEqual({a["branch"] for a in result["video_assessments"]}, {"dog", "owner"})
        self.assertEqual(len(result["ledgers"]), 3)
        usage = summarize(self.store)
        self.assertEqual(usage["unreserved_ai_steps"], 0)
        report = self.client.get(self.base + "/reports/" + result["run_id"]).json()
        self.assertEqual(report["status"], "ready")

    def test_disagreement_has_one_scoped_pass_no_majority_and_remains_pending(self):
        self.start()
        def different(media, context, guard):
            return video_response(context, {"BS-01": "BS-01:S2" if media.video_id == self.video_ids[0] else "BS-01:S1"})
        self.observer.callback = different
        self.worker.once()
        result = self.view()
        reviews = self.observer.review_calls()
        self.assertEqual(len(reviews), 3)
        self.assertTrue(all([i["item_id"] for i in c[1]["items"]] == ["BS-01"] for c in reviews))
        self.assertTrue(all(c[1]["branch"] == "dog" for c in reviews))
        self.assertEqual(next(i for i in result["scores"]["items"] if i["item_id"] == "BS-01")["status"], "conflicting_evidence")
        self.assertEqual(len(result["video_assessments"]), 9)
        self.assertEqual(len({e["evidence_id"] for e in result["evidence"]}), 6)
        total = len(self.observer.calls)
        self.assertFalse(self.worker.once())
        self.assertEqual(len(self.observer.calls), total)

    def test_review_can_resolve_but_failed_review_cannot_freeze_premature_merge(self):
        run_id = self.start()
        failing = True
        def response(media, context, guard):
            review = len(context["items"]) == 1
            if review and failing and media.video_id == self.video_ids[0]:
                raise ProviderError("provider_http_400")
            return video_response(context, {"BS-01": "BS-01:S2" if not review and media.video_id == self.video_ids[0] else "BS-01:S1"})
        self.observer.callback = response
        self.worker.once()
        self.assertEqual(self.view()["status"], "partial_failed")
        self.assertIsNone(self.view()["scores"])
        failing = False
        self.assertEqual(self.client.post(self.base + f"/analysis/{run_id}/retry").status_code, 200)
        self.worker.once()
        # Successful ledgers and branch decisions are never recalled; only the failed review reruns.
        self.assertEqual(len(self.observer.ledger_calls()), 3)
        self.assertEqual(len([c for c in self.observer.branch_calls() if not c[1]["focus_intervals"]]), 6)
        self.assertEqual(len(self.observer.review_calls()), 4)
        self.assertEqual(self.view()["scores"]["items"][0]["raw_score"], 1.0)

    def test_retry_reuses_successful_views_and_current_run_survives_restart(self):
        run_id = self.start()
        def flaky(media, context, guard):
            if media.video_id == self.video_ids[1]:
                raise ProviderError("provider_http_429", retryable=True)
            return video_response(context)
        self.observer.callback = flaky
        self.worker.once()
        self.assertEqual(len(self.view()["video_assessments"]), 4)
        self.assertEqual(self.view()["status"], "retry_wait")
        self.observer.callback = None
        self.ready_retries()
        from app.worker import Worker
        Worker(self.store, observer=self.observer, evaluator=self.worker.evaluator,
               reporter=self.worker.reporter, probe=observation.fake_probe).once()
        self.assertEqual(len(self.observer.ledger_calls()), 3)
        self.assertEqual(len(self.observer.branch_calls()), 8)
        self.assertEqual(self.view()["status"], "scored")
        self.start(reanalyze=True, reuse_run_id=run_id)
        self.worker.once()
        self.assertEqual(len(self.observer.calls), 11)
        self.assertEqual(self.view()["status"], "scored")

    def test_output_contract_rejects_bad_item_option_refs_coverage_and_measurements(self):
        self.start()
        self.worker.once()
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM runs").fetchone()
            prepared = validated_prepared(row, step_payload(self.store, row, db.execute("SELECT * FROM steps WHERE stage='prepare'").fetchone()))
            step = db.execute("SELECT * FROM steps WHERE stage='observe' AND branch_key LIKE '%/dog' LIMIT 1").fetchone()
            payload = step_payload(self.store, row, step)
            catalog = BehaviorCatalog.model_validate_json(encode(json.loads(row["config_snapshot_json"])["behavior_catalog"]))
        variants = []
        missing = copy.deepcopy(payload); missing["video_items"].pop(); variants.append(missing)
        duplicate = copy.deepcopy(payload); duplicate["video_items"][-1] = duplicate["video_items"][0]; variants.append(duplicate)
        option = copy.deepcopy(payload); option["video_items"][0]["selected_option_id"] = "BS-01:S4"; variants.append(option)
        refs = copy.deepcopy(payload); refs["video_items"][0]["evidence_ids"] = ["ev-other-video"]; variants.append(refs)
        coverage = copy.deepcopy(payload); coverage["video_items"][0]["coverage"] = "partial"; variants.append(coverage)
        time = copy.deepcopy(payload); time["evidence"][0]["source_end_sec"] = 99; variants.append(time)
        audio = copy.deepcopy(payload); audio["evidence"][0]["modality"] = "audio"; variants.append(audio)
        measure = copy.deepcopy(payload); measure["video_items"][0]["measurements"] = [{"kind":"duration_sec","value":9.0,"start_sec":0.0,"end_sec":9.0}]; variants.append(measure)
        video_id, branch = split_branch_key(step["branch_key"])
        for value in variants:
            with self.subTest(value=value["video_items"][0]), self.assertRaises(ValueError):
                validated_observation(value, prepared.run_input, video_id, catalog=catalog,
                                      expected_items=branch_items(branch), branch=branch)
        # A branch may not answer for the other branch's items.
        with self.assertRaises(ValueError):
            validated_observation(payload, prepared.run_input, video_id, catalog=catalog,
                                  expected_items=branch_items("owner"), branch="owner")

    def test_inflight_deletion_does_not_publish_or_continue_views(self):
        self.start()
        def remove(media, context, guard):
            self.delete_case()
            return ledger_response(context)
        self.observer.ledger_callback = remove
        self.worker.once()
        self.assertEqual(len(self.observer.calls), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM runs").fetchone()[0], "stopped")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps WHERE stage='observe' AND status='succeeded'").fetchone()[0], 0)

    def test_budget_stops_before_third_video_and_fps_matches_request(self):
        from app import settings
        selected = settings.current
        def limited(store, db):
            version, config = selected(store, db)
            return version, config.model_copy(update={"max_ai_calls": 2, "fps": 2.0})
        with patch("app.settings.current", side_effect=limited):
            self.start()
        self.worker.once()
        self.assertEqual(len(self.observer.calls), 2)
        self.assertEqual(self.view()["status"], "partial_failed")
        self.assertTrue(all("sampling_static_2fps" in e["quality_flags"] and "sampling_static_1fps" not in e["quality_flags"]
                            for e in self.view()["evidence"]))

    def test_missing_measurement_and_pending_rules_never_get_scores(self):
        self.start()
        self.observer.callback = lambda media, context, guard: video_response(context, {"DOG-13": "DOG-13:S1", "DOG-12": "DOG-12:S1", "OWN-14": "OWN-14:S1"})
        self.worker.once()
        items = {i["item_id"]: i for i in self.view()["scores"]["items"]}
        self.assertEqual(items["DOG-13"]["status"], "insufficient_evidence")
        self.assertEqual(items["DOG-12"]["status"], "rule_pending")
        self.assertEqual(items["OWN-14"]["status"], "rule_pending")

    def test_explicit_conflict_cannot_be_hidden_by_one_scored_view(self):
        self.start()
        def response(media, context, guard):
            result = video_response(context)
            if media.video_id != self.video_ids[0]:
                result.items[0].status = "conflicting_evidence"
                result.items[0].selected_option_id = None
                result.items[0].measurements = [Measurement(kind="duration_sec", value=3.0, start_sec=0.0, end_sec=3.0)]
            return result
        self.observer.callback = response
        self.worker.once()
        self.assertEqual(len(self.observer.review_calls()), 6)
        self.assertEqual(self.view()["scores"]["items"][0]["status"], "conflicting_evidence")
        self.assertEqual(len(self.view()["evaluations"][0]["evaluation"]["items"][0]["evidence_ids"]), 3)

    def test_measurement_outside_original_is_rejected_before_item_withholding(self):
        self.start()
        def invalid(media, context, guard):
            result = video_response(context)
            result.items[0].measurements = [Measurement(kind="duration_sec", value=5.0, start_sec=0.0, end_sec=5.0)]
            return result
        self.observer.callback = invalid
        self.worker.once()
        self.assertEqual(self.view()["status"], "retry_wait")
        self.assertEqual(self.view()["video_assessments"], [])

    def test_one_unsupported_measurement_withholds_only_its_item(self):
        self.start()
        def response(media, context, guard):
            result = video_response(context, {"BS-01": "BS-01:S1", "DOG-13": "DOG-13:S1"})
            return measure(result, "DOG-13", [Measurement(kind="command_count", value=1.0, start_sec=1.0, end_sec=3.0)])
        self.observer.callback = response
        self.worker.once()
        result = self.view()
        self.assertEqual(result["status"], "scored")
        self.assertEqual(len(self.observer.branch_calls()), 6)
        for artifact in [a for a in result["video_assessments"] if a["branch"] == "dog"]:
            self.assertEqual(len(artifact["video_items"]), 36)
            item = next(i for i in artifact["video_items"] if i["item_id"] == "DOG-13")
            self.assertEqual(item["status"], "insufficient_evidence")
            self.assertIsNone(item["selected_option_id"])
            self.assertEqual(item["measurements"], [])
            self.assertIn("1–3초", item["reason"])
            self.assertIn("1–2초", item["reason"])
        self.assertEqual(result["scores"]["items"][0]["status"], "scored")

    def test_invalid_options_are_rejected_before_pending_normalization(self):
        self.start()
        self.observer.callback = lambda media, context, guard: video_response(context, {"DOG-12": "INVALID", "DOG-13": "INVALID"})
        self.worker.once()
        self.assertEqual(self.view()["status"], "retry_wait")
        # Only the branch holding the invalid options fails; the other branch keeps its result.
        self.assertEqual({a["branch"] for a in self.view()["video_assessments"]}, {"owner"})
        self.ready_retries()
        self.worker.once()
        self.assertEqual(self.view()["status"], "partial_failed")
        self.assertEqual(len(self.observer.branch_calls()), 9)

    def test_direct_output_before_db_adoption_recovers_without_recalling_video(self):
        run_id = self.start()
        row = claim(self.store)
        prepared = self.worker.stage(row, "prepare", "session", lambda p: validated_prepared(row, p),
                                     lambda step: self.worker.prepare(row, step))
        catalog = BehaviorCatalog.model_validate_json(encode(json.loads(row["config_snapshot_json"])["behavior_catalog"]))
        info = prepared.media[0]
        ledger = self.worker.stage(row, "ledger", info.video_id, lambda p: p,
                                   lambda step: self.worker.build_ledger(row, step, prepared, info))
        step = {"step_id": uid(), "claim_token": row["claim_token"], "attempt": 1}
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,created_at,updated_at) "
                       "VALUES(?,?,'observe',?,1,'running',?,?,?)",
                       (step["step_id"], run_id, f"{info.video_id}/dog", row["claim_token"], now(), now()))
        payload = self.worker.assess_video(row, step, prepared, info, catalog, "dog", measures=ledger["measures"])
        write_output(self.store, row, step, payload)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at=? WHERE run_id=?", (later(-1), run_id))
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        self.assertEqual(len(self.observer.ledger_calls()), 3)
        self.assertEqual(len(self.observer.branch_calls()), 6)
        self.assertEqual(len([s for s in self.view()["steps"] if s["stage"] == "observe"]), 6)
        self.assertEqual(len([s for s in self.view()["steps"] if s["stage"] == "ledger"]), 3)

    def test_a_run_frozen_on_an_earlier_per_video_pipeline_is_never_reported_scored(self):
        # Run snapshots are immutable, so freeze the version at enqueue time instead.
        with patch("app.video_evaluation.VERSION", "video-evaluate-1.0"):
            run_id = self.start()
        with self.store.connect() as db:
            frozen = json.loads(db.execute("SELECT config_snapshot_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0])
        self.assertEqual(frozen["pipeline_version"], "video-evaluate-1.0")
        self.worker.once()
        result = self.view()
        # No half-migrated structure, no paid calls, and never a scored run without a merge.
        self.assertEqual(result["status"], "partial_failed")
        self.assertIsNone(result["scores"])
        self.assertEqual(self.observer.calls, [])
        self.assertEqual([s for s in result["steps"] if s["stage"] in ("ledger", "observe")], [])

    def test_reused_branch_decision_always_carries_its_ledger(self):
        first = self.start()
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        second = self.start(reanalyze=True, reuse_run_id=first)
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        # Chaining a second generation must not drop the ledger the decisions were checked against.
        self.start(reanalyze=True, reuse_run_id=second)
        self.worker.once()
        with self.store.connect() as db:
            reuse = json.loads(db.execute("SELECT reuse_manifest_json FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()[0])
        ledgers = {e["video_id"] for e in reuse if e.get("stage") == "ledger"}
        observes = {e["video_id"] for e in reuse if e.get("stage", "observe") == "observe"}
        self.assertEqual(ledgers, set(self.video_ids))
        self.assertTrue(observes <= ledgers)
        result = self.view()
        self.assertEqual(result["status"], "scored")
        self.assertEqual(len(result["ledgers"]), 3)
        self.assertEqual(self.client.get(self.base + "/analysis").status_code, 200)

    def test_legacy_related_input_ignores_only_explicit_legacy_mode(self):
        self.start()
        with self.store.connect() as db:
            row = dict(db.execute("SELECT * FROM runs").fetchone())
        config = json.loads(row["config_snapshot_json"])
        config.pop("evaluation_mode")
        old = {**row, "config_snapshot_json": encode(config)}
        config["evaluation_mode"] = "legacy"
        legacy = {**row, "config_snapshot_json": encode(config)}
        self.assertEqual(related_input(old), related_input(legacy))
        self.assertNotEqual(related_input(old), related_input(row))

    def test_command_count_requires_source_range_and_owner_audio(self):
        self.start()
        def response(media, context, guard):
            result = video_response(context, {"BS-01": "BS-01:S1", "OWN-11": "OWN-11:S1", "DOG-13": "DOG-13:S1"})
            for item in result.items:
                if item.item_id in ("OWN-11", "DOG-13"):
                    item.measurements = [Measurement(kind="command_count", value=4.0, start_sec=1.0, end_sec=2.0)]
            return VideoResponse.model_validate_json(result.model_dump_json())
        self.observer.callback = response
        self.worker.once()
        self.assertEqual(len(self.view()["video_assessments"]), 6)
        for artifact in self.view()["video_assessments"]:
            for item in artifact["video_items"]:
                if item["item_id"] in ("OWN-11", "DOG-13"):
                    self.assertEqual(item["status"], "insufficient_evidence")
                    self.assertIsNone(item["selected_option_id"])
                    self.assertEqual(item["measurements"], [])
        self.assertEqual(self.view()["scores"]["items"][0]["status"], "scored")
        self.start(reanalyze=True)
        def silent(media, context, guard):
            result = measure(video_response(context, {"OWN-11": "OWN-11:S1"}), "OWN-11",
                             [Measurement(kind="command_count", value=1.0, start_sec=1.0, end_sec=2.0)])
            return VideoResponse.model_validate_json(result.model_dump_json())
        self.observer.callback = silent
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        self.assertEqual(next(i for i in self.view()["scores"]["items"] if i["item_id"] == "OWN-11")["status"], "insufficient_evidence")

    def test_direct_rest_sends_video_full_rubric_and_supported_schema(self):
        from app.gemini import BASE, GeminiObserver, video_schema
        from app.ledger import ledger_schema
        calls = []
        self.start()
        def transport(method, url, key, **kwargs):
            calls.append((method, url, kwargs))
            if "upload/v1beta" in url:
                return {}, {"X-Goog-Upload-URL": BASE + "/upload-session"}
            if "upload-session" in url:
                return {"file": {"name": "files/f1", "state": "ACTIVE", "uri": BASE + "/v1beta/files/f1"}}, {}
            if method == "DELETE":
                return {}, {}
            context = json.loads(kwargs["data"]["input"][1]["text"])
            body = ledger_response(context) if "steps" in context else video_response(context)
            return {"status": "completed", "steps": [{"type": "model_output", "content": [
                {"type": "text", "text": body.model_dump_json()}]}], "usage": {"total_tokens": 12}}, {}
        self.worker.observer = GeminiObserver()
        with patch("app.gemini.request", side_effect=transport):
            self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        bodies = [kwargs["data"] for method, url, kwargs in calls if url.endswith("/interactions")]
        self.assertEqual(len(bodies), 9)
        branch = [b for b in bodies if "items" in json.loads(b["input"][1]["text"])]
        ledgers = [b for b in bodies if "steps" in json.loads(b["input"][1]["text"])]
        self.assertEqual((len(branch), len(ledgers)), (6, 3))
        self.assertEqual(branch[0]["input"][0]["type"], "video")
        self.assertEqual({len(json.loads(b["input"][1]["text"])["items"]) for b in branch}, {36, 19})
        self.assertEqual(branch[0]["response_format"]["schema"], video_schema(4.0))
        self.assertEqual(ledgers[0]["response_format"]["schema"], ledger_schema(4.0))
        self.assertTrue(all(b["input"][0]["processing"] == {"type": "static", "fps": 1.0} for b in bodies))
        self.assertTrue(all(b["generation_config"] == {"max_output_tokens": 65536} for b in bodies))
        self.assertEqual(sum(method == "DELETE" for method, _, _ in calls), 9)

    def test_measured_command_with_owner_audio_remains_scorable(self):
        def audible(path, video, prepared_path, prepared_ref):
            return observation.fake_probe(path, video, prepared_path, prepared_ref).model_copy(
                update={"audio_status": "present", "quality_flags": []})
        self.worker.probe = audible
        def response(media, context, guard):
            result = video_response(context, {"OWN-11": "OWN-11:S1", "DOG-13": "DOG-13:S1"})
            for item in result.items:
                if item.status == "scored":
                    item.measurements = [Measurement(kind="command_count", value=1.0, start_sec=1.0, end_sec=2.0)]
            for evidence in result.observations:
                evidence.modality = "audio_video"
            return result
        self.observer.callback = response
        self.start()
        self.worker.once()
        items = {i["item_id"]: i for i in self.view()["scores"]["items"]}
        self.assertEqual(items["OWN-11"]["status"], "scored")
        self.assertEqual(items["DOG-13"]["raw_score"], 1.0)

    def test_explicit_forward_link_fills_reverse_tag_but_unknown_index_is_rejected(self):
        self.start()
        def response(media, context, guard):
            result = video_response(context)
            for observation_item in result.observations:
                observation_item.candidate_item_ids = ["BS-02"]
            return result
        self.observer.callback = response
        self.worker.once()
        self.assertEqual(self.view()["scores"]["items"][0]["status"], "scored")
        for evidence in self.view()["evidence"]:
            self.assertEqual(evidence["candidate_item_ids"], ["BS-02", "BS-01"])
            self.assertEqual(evidence["observation"], "가상 관찰: 입장 시 이동")
            self.assertEqual((evidence["source_start_sec"], evidence["source_end_sec"]), (1.0, 2.0))
        self.start(reanalyze=True)
        def invalid(media, context, guard):
            result = video_response(context)
            result.items[0].observation_indices = [999]
            return result
        self.observer.callback = invalid
        self.worker.once()
        self.assertEqual(self.view()["status"], "retry_wait")
        self.assertEqual(self.view()["video_assessments"], [])


if __name__ == "__main__":
    unittest.main()
