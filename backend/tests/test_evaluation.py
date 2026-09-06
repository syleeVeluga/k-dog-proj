"""M3 fixed arithmetic, concurrent persistence and synthetic REST contract tests."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from app.domain.contracts import BehaviorCatalog, BranchEvaluation, Evidence, RunInput, SurveyCatalog
from app.evaluation import Evaluator, configuration, make_evaluation
from app.gemini import ProviderError
from app.scoring import RULES, behavior_scores, rounded, survey_scores
from app.storage import REPO_ROOT, encode
from tests import test_observation as observation
from tests.evaluation_fixtures import evaluation_response


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.catalog = BehaviorCatalog.model_validate_json((REPO_ROOT / "resources/catalogs/behavior-v1.json").read_bytes())
        self.survey_catalog = SurveyCatalog.model_validate_json((REPO_ROOT / "resources/catalogs/survey-v1.json").read_bytes())
        fixture = json.loads((Path(__file__).parent / "fixtures/contract-case.json").read_text(encoding="utf-8"))
        self.run = RunInput.model_validate_json(encode({**fixture["run"], "scoring_rule_version": RULES["version"]}))
        self.evidence = Evidence.model_validate_json(encode({**fixture["evidence"][0],
            "candidate_item_ids": [item.item_id for item in self.catalog.items]}))

    def branch(self, branch, selected):
        items = [{"item_id": item.item_id, "status": "scored" if item.item_id in selected else "insufficient_evidence",
                  "selected_option_id": selected.get(item.item_id), "evidence_ids": [self.evidence.evidence_id], "reason": "가상 시험"}
                 for item in self.catalog.items if item.item_id.startswith("OWN-") == (branch == "owner")]
        return BranchEvaluation.model_validate_json(encode({"run_id": self.run.run_id, "branch": branch, "items": items}))

    def test_all_55_source_scores_50_targets_and_reference_exclusion(self):
        selections = {item.item_id: item.options[0].option_id for item in self.catalog.items}
        result = behavior_scores(self.run, [self.branch(b, selections) for b in ("dog", "owner")], self.catalog, (self.evidence,))
        self.assertEqual(len(result.items), 55)
        self.assertEqual(sum(d.target_count for d in result.domains), 50)
        self.assertEqual(sum(d.valid_count for d in result.domains), 50)
        self.assertEqual({d.domain: d.target_count for d in result.domains},
                         {"EDU": 7, "SOC_P": 1, "SOC_D": 1, "SOC_E": 9, "ATT": 14, "CON": 12, "TRN": 6})
        for domain in result.domains:
            values = [item.options[0].score for item in self.catalog.items if item.domain == domain.domain]
            self.assertEqual(domain.mean, rounded(sum(map(lambda v: Decimal(str(v)), values)) / len(values)))
            self.assertEqual(domain.maximum, max(values))

    def test_missing_branch_no_zero_scores_and_duplicate_cameras_do_not_add_scores(self):
        item = self.catalog.items[0]
        branch = self.branch("dog", {item.item_id: item.options[0].option_id})
        one = behavior_scores(self.run, [branch], self.catalog, (self.evidence,))
        extra = self.evidence.model_copy(update={"evidence_id": "ev-second-camera"})
        two = behavior_scores(self.run, [branch], self.catalog, (self.evidence, extra))
        self.assertEqual(one, two)
        self.assertEqual(len(one.items), 36)
        self.assertEqual(sum(d.valid_count for d in one.domains), 1)
        self.assertTrue(all(d.mean is None and d.maximum is None for d in one.domains if d.valid_count == 0))
        self.assertTrue(all(s.raw_score is None for s in one.items if s.status != "scored"))

    def test_direction_score_sum_winner_and_tie(self):
        # Locate real equal-valued A/B options within the same domain, never invent options.
        candidates = [(item, option) for item in self.catalog.items for option in item.options if item.domain and option.direction]
        a, b = next((a, b) for a in candidates for b in candidates
                    if a[0].domain == b[0].domain and a[0].item_id != b[0].item_id
                    and a[1].direction == "A" and b[1].direction == "B" and a[1].score == b[1].score)
        for selections, expected in [({a[0].item_id: a[1].option_id}, "A"),
                                     ({a[0].item_id: a[1].option_id, b[0].item_id: b[1].option_id}, None)]:
            result = behavior_scores(self.run, [self.branch(branch, selections) for branch in ("dog", "owner")], self.catalog, (self.evidence,))
            domain = next(d for d in result.domains if d.domain == a[0].domain)
            self.assertEqual(domain.direction, expected)
            self.assertEqual(domain.direction_a_sum, a[1].score)

    def test_survey_reverse_pending_missing_equal_domain_weight_and_rounding(self):
        answers = {f"q{i:02}": 1 for i in range(1, 31)}
        result = survey_scores("r", answers, self.survey_catalog)
        self.assertEqual(result.overall_reference, 2.33)  # (1 + 1 + 5) / 3, not the 16-item mean
        self.assertEqual({q.item_id for q in result.items if q.converted == 5}, set(RULES["reverse_items"]))
        q23 = next(q for q in result.items if q.item_id == "q23")
        self.assertEqual((q23.raw, q23.converted, q23.status), (1, None, "rule_pending"))
        self.assertIsNone(next(g for g in result.groups if g.group == "C-2").target_count)
        answers["q01"] = None
        partial = survey_scores("r", answers, self.survey_catalog)
        self.assertIsNone(partial.overall_reference)
        self.assertIsNone(next(g for g in partial.groups if g.group == "A").mean)
        self.assertEqual(next(g for g in partial.groups if g.group == "D").mean, 5.0)
        self.assertEqual(rounded(Decimal("2.345")), 2.35)
        # No intermediate rounding: (7/6 + 1 + 4/3) / 3 = 7/6 => 1.17.
        answers = {f"q{i:02}": 1 for i in range(1, 31)}
        answers.update(q01=2, q26=4, q27=5, q28=5)
        self.assertEqual(survey_scores("r", answers, self.survey_catalog).overall_reference, 1.17)
        self.assertEqual(answers["q26"], 4)
        for invalid in [True, 0, 6, 1.0, "1"]:
            with self.assertRaises(ValueError):
                survey_scores("r", {**answers, "q01": invalid}, self.survey_catalog)

    def test_known_boundaries_cannot_gain_scores_and_invalid_options_still_rejected(self):
        for item_id, seconds in [("DOG-12", 5), ("DOG-12", 15), ("OWN-14", 2)]:
            item = next(i for i in self.catalog.items if i.item_id == item_id)
            branch = "owner" if item_id.startswith("OWN") else "dog"
            raw = self.branch(branch, {item_id: item.options[0].option_id})
            from app.evaluation_models import EvaluationResponse
            response = EvaluationResponse(branch=branch, items=list(raw.items))
            evidence = self.evidence.model_copy(update={"observation": f"가상 관찰 지속 {seconds}초"})
            artifact = make_evaluation(response, {}, self.run, branch, self.catalog, (evidence,))
            score = next(s for s in artifact.scores.items if s.item_id == item_id)
            self.assertEqual((score.status, score.raw_score), ("rule_pending", None))
            bad = response.model_copy(update={"items": [i.model_copy(update={"selected_option_id": "invented"}) if i.item_id == item_id else i for i in response.items]})
            with self.assertRaises(ValueError):
                make_evaluation(bad, {}, self.run, branch, self.catalog, (evidence,))

    def test_unrelated_evidence_is_removed_without_failing_the_branch(self):
        from app.evaluation_models import EvaluationResponse

        item = next(item for item in self.catalog.items if item.item_id == "OWN-15")
        response = EvaluationResponse(branch="owner", items=list(self.branch("owner", {
            item.item_id: item.options[0].option_id,
        }).items))
        unrelated = self.evidence.model_copy(update={
            "evidence_id": "ev-unrelated",
            "candidate_item_ids": ("OWN-14",),
        })
        response = response.model_copy(update={"items": [
            value.model_copy(update={"evidence_ids": (unrelated.evidence_id,)})
            if value.item_id == item.item_id else value
            for value in response.items
        ]})

        artifact = make_evaluation(response, {}, self.run, "owner", self.catalog, (self.evidence, unrelated))
        result = next(value for value in artifact.evaluation.items if value.item_id == item.item_id)
        score = next(value for value in artifact.scores.items if value.item_id == item.item_id)
        self.assertEqual((result.status, result.selected_option_id, result.evidence_ids),
                         ("insufficient_evidence", None, ()))
        self.assertIn("채점을 보류", result.reason)
        self.assertEqual((score.status, score.raw_score), ("insufficient_evidence", None))


class EvaluationTests(unittest.TestCase):
    setUp = observation.ObservationTests.setUp
    login = observation.ObservationTests.login
    access = observation.ObservationTests.access
    start = observation.ObservationTests.start
    view = observation.ObservationTests.view
    ready_retries = observation.ObservationTests.ready_retries

    def test_parallel_owner_delay_exposes_persisted_dog_and_survey(self):
        entered = threading.Barrier(2, timeout=5)
        release = threading.Event()
        def evaluate(config, context, guard):
            entered.wait()
            if context["branch"] == "owner":
                if not release.wait(10):
                    raise ProviderError("test_deadline")
            return evaluation_response(context), {}
        self.worker.evaluator.callback = evaluate
        self.start()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.worker.once)
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    view = self.view()
                    if view["evaluations"]:
                        break
                    time.sleep(0.02)
                self.assertEqual(view["status"], "running")
                self.assertEqual([e["evaluation"]["branch"] for e in view["evaluations"]], ["dog"])
                self.assertEqual(len(view["scores"]["items"]), 36)
                self.assertIsNotNone(view["survey_scores"])
                self.assertFalse(future.done())
            finally:
                release.set()
            future.result(timeout=10)
        self.assertEqual(self.view()["status"], "scored")
        for _, context in self.worker.evaluator.calls:
            serialized = encode(context)
            for forbidden in ("survey", "participant_id", "dog_name", "raw_score", "case_id", "run_id"):
                self.assertNotIn('"' + forbidden + '"', serialized)

    def test_failure_only_retries_owner_even_if_success_used_all_attempts(self):
        run_id = self.start()
        def failed(config, context, guard):
            if context["branch"] == "owner":
                raise ProviderError("provider_http_400")
            return evaluation_response(context), {}
        self.worker.evaluator.callback = failed
        self.worker.once()
        self.assertEqual(self.view()["status"], "partial_failed")
        self.assertEqual(len(self.view()["scores"]["items"]), 36)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET attempt=3 WHERE stage='evaluate' AND branch_key='dog'")
        self.assertEqual(self.client.post(self.base + f"/analysis/{run_id}/retry").status_code, 200)
        self.worker.evaluator.callback = None
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        self.assertEqual([c[1]["branch"] for c in self.worker.evaluator.calls].count("dog"), 1)
        self.assertEqual(len(self.observer.calls), 2)

    def test_schema_repair_cap_preserves_usage_and_success_branch(self):
        run_id = self.start()
        def invalid(config, context, guard):
            response = evaluation_response(context)
            if context["branch"] == "owner":
                response.items.pop()
            return response, {"input_tokens": 11}
        self.worker.evaluator.callback = invalid
        self.worker.once()
        self.assertEqual(self.view()["status"], "retry_wait")
        self.ready_retries()
        self.worker.once()
        self.assertEqual(self.view()["status"], "partial_failed")
        self.assertEqual(len(self.view()["scores"]["items"]), 36)
        self.assertIn("repair", self.worker.evaluator.calls[-1][1])
        failed = [s for s in self.view()["steps"] if s["stage"] == "evaluate" and s["branch_key"] == "owner"]
        self.assertEqual(len(failed), 2)
        self.assertTrue(all(s["usage"]["input_tokens"] == 11 for s in failed))
        self.assertEqual(self.client.post(self.base + f"/analysis/{run_id}/retry").status_code, 409)

    def test_survey_change_reuses_both_evaluations_and_changed_owner_config_only_repeats_owner(self):
        source = self.start()
        self.worker.once()
        first = self.view()
        session = self.item["manifest"]["sessions"][0]
        self.item = self.client.put(self.base + "/survey", json={"expected_revision": self.item["input_revision"],
            "session_id": session["session_id"], "survey_version": session["survey_version"],
            "answers": {f"q{i:02}": 4 for i in range(1, 31)}}).json()
        self.start(reuse_run_id=source)
        self.worker.once()
        self.assertEqual(len(self.worker.evaluator.calls), 2)
        self.assertEqual(len(self.observer.calls), 2)
        self.assertTrue(all(a["usage"]["reused"] for a in self.view()["evaluations"]))
        self.assertEqual(self.view()["scores"]["items"], first["scores"]["items"])
        self.assertEqual(self.view()["survey_scores"]["overall_reference"], 3.33)
        with patch.dict(os.environ, {"KDOG_EVALUATE_OWNER_MODEL": "gemini-new-test"}):
            self.start(reuse_run_id=source)
        self.worker.once()
        self.assertEqual(len(self.worker.evaluator.calls), 3)
        self.assertEqual(self.worker.evaluator.calls[-1][1]["branch"], "owner")
        self.assertEqual(len(self.observer.calls), 2)

    def test_settings_permissions_stale_write_and_frozen_queued_run(self):
        for role in ("operator", "reviewer"):
            self.login(role)
            self.assertEqual(self.client.get("/api/developer/evaluation").status_code, 403)
            self.assertEqual(self.client.put("/api/developer/evaluation", json={}).status_code, 403)
        self.login("operator")
        run_id = self.start()
        self.login("developer")
        current = self.client.get("/api/developer/evaluation").json()
        body = {"expected_version": current["version"], "branches": {"dog": {"provider": "openai", "model": "gpt-test"},
            "owner": {"provider": "anthropic", "model": "claude-test"}}}
        self.assertEqual(self.client.put("/api/developer/evaluation", json=body).status_code, 200)
        self.assertEqual(self.client.put("/api/developer/evaluation", json=body).status_code, 409)
        self.login("operator")
        self.worker.once()
        self.assertTrue(all(config["provider"] == "gemini" for config, _ in self.worker.evaluator.calls))
        self.start()
        self.worker.once()
        self.assertEqual({config["provider"] for config, _ in self.worker.evaluator.calls[-2:]}, {"openai", "anthropic"})
        with self.store.connect() as db:
            self.assertEqual(json.loads(db.execute("SELECT config_snapshot_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0])["evaluation"]["dog"]["provider"], "gemini")

    def test_invalid_environment_provider_can_be_corrected_in_developer_settings(self):
        self.login("developer")
        with patch.dict(os.environ, {"KDOG_EVALUATE_DOG_PROVIDER": "invalid-provider"}):
            response = self.client.get("/api/developer/evaluation")
            self.assertEqual(response.status_code, 200)
            current = response.json()
            self.assertEqual(current["branches"]["dog"]["provider"], "invalid-provider")
            self.assertFalse(current["key_available"]["dog"])
            branches = {"dog": {"provider": "gemini", "model": "gemini-test-only"},
                        "owner": {"provider": "gemini", "model": "gemini-test-only"}}
            response = self.client.put("/api/developer/evaluation", json={"expected_version": current["version"], "branches": branches})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["branches"], branches)

    def test_withdrawal_while_two_requests_inflight_rejects_both_results(self):
        entered = threading.Barrier(3, timeout=8)
        release = threading.Event()
        def delayed(config, context, guard):
            entered.wait()
            release.wait(10)
            return evaluation_response(context), {}
        self.worker.evaluator.callback = delayed
        self.start()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.worker.once)
            try:
                entered.wait()
                self.access(False)
            finally:
                release.set()
            future.result(timeout=10)
        self.assertEqual(self.view()["evaluations"], [])
        self.assertIsNone(self.view()["scores"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM steps WHERE stage='evaluate' AND status='succeeded'").fetchone()[0], 0)

    def test_evaluation_file_before_db_crash_recovers_without_provider_recall(self):
        from app.analysis import adopt, later
        run_id = self.start()
        def crash(store, row, step, ref, output_hash, usage):
            payload = json.loads(store.path(ref).read_text(encoding="utf-8"))["payload"]
            if payload.get("evaluation", {}).get("branch") == "dog":
                raise RuntimeError("synthetic process interruption after publication")
            return adopt(store, row, step, ref, output_hash, usage)
        with patch("app.worker.adopt", side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.worker.once()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at=? WHERE run_id=?", (later(-1), run_id))
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        self.assertEqual(len(self.worker.evaluator.calls), 2)
        self.assertEqual(len([s for s in self.view()["steps"] if s["stage"] == "evaluate"]), 2)

    def test_corrupt_evaluation_is_rejected_for_read_and_reuse(self):
        run_id = self.start()
        self.worker.once()
        with self.store.connect() as db:
            ref = db.execute("SELECT output_ref FROM steps WHERE stage='evaluate' LIMIT 1").fetchone()[0]
        self.store.path(ref).write_text("{}", encoding="utf-8")
        self.assertEqual(self.client.get(self.base + "/analysis").status_code, 409)
        self.assertEqual(self.client.post(self.base + "/analysis", json={"expected_revision": self.item["input_revision"], "reuse_run_id": run_id}).status_code, 409)
        self.assertEqual(len(self.worker.evaluator.calls), 2)


class AdapterTests(unittest.TestCase):
    def test_malformed_provider_envelopes_become_stage_failures(self):
        for provider in ("gemini", "openai", "anthropic"):
            config = {**configuration("gemini-test")["dog"], "provider": provider, "model": "test-model"}
            for response in ([], {"usage": None, "usageMetadata": None}, {"usage": [1], "usageMetadata": [1]}):
                with self.subTest(provider=provider, response=response), \
                     patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret", "OPENAI_API_KEY": "test-secret", "ANTHROPIC_API_KEY": "test-secret"}), \
                     patch("app.evaluation.request", return_value=(response, {})):
                    with self.assertRaises(ProviderError) as caught:
                        Evaluator().evaluate(config, {"branch": "dog"}, lambda: None)
                    self.assertEqual(caught.exception.code, "provider_response_invalid")

    def test_transport_uses_provider_specific_auth_and_blocks_cross_origin(self):
        from unittest.mock import MagicMock
        from app.gemini import request
        hosts = {"openai": "api.openai.com", "anthropic": "api.anthropic.com"}
        for provider, host in hosts.items():
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = b"{}"
            with patch("app.gemini.build_opener", return_value=opener):
                request("POST", f"https://{host}/v1/test", "test-secret", data={}, provider=provider)
            sent = opener.open.call_args.args[0]
            headers = {key.lower(): value for key, value in sent.header_items()}
            self.assertEqual(headers["authorization" if provider == "openai" else "x-api-key"],
                             "Bearer test-secret" if provider == "openai" else "test-secret")
            self.assertNotIn("x-goog-api-key", headers)
            if provider == "anthropic":
                self.assertEqual(headers["anthropic-version"], "2023-06-01")
            with self.assertRaises(ProviderError):
                request("POST", "https://example.com/v1/test", "test-secret", provider=provider)

    def test_three_provider_contracts_usage_guard_and_no_fallback(self):
        from app.evaluation_models import EvaluationResponse
        empty = EvaluationResponse(branch="dog", items=[]).model_dump_json()
        for provider in ("gemini", "openai", "anthropic"):
            config = {**configuration("gemini-test")["dog"], "provider": provider, "model": "test-model"}
            context = {"branch": "dog", "items": [], "evidence": []}
            responses = {
                "gemini": {"status": "completed", "steps": [{"type": "model_output", "content": [
                    {"type": "text", "text": empty}]}], "usage": {"total_tokens": 13}},
                "openai": {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": empty}]}], "usage": {"input_tokens": 13}},
                "anthropic": {"stop_reason": "end_turn", "content": [{"type": "text", "text": empty}], "usage": {"input_tokens": 13}},
            }
            guarded = []
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret", "OPENAI_API_KEY": "test-secret", "ANTHROPIC_API_KEY": "test-secret"}), \
                 patch("app.evaluation.request", return_value=(responses[provider], {})) as transport:
                _, usage = Evaluator().evaluate(config, context, lambda: guarded.append(True))
                self.assertEqual(guarded, [True])
                self.assertEqual(transport.call_count, 1)
                body = transport.call_args.kwargs["data"]
                self.assertNotIn("test-secret", encode(body))
                if provider == "openai":
                    self.assertFalse(body["store"])
                    self.assertTrue(body["text"]["format"]["strict"])
                    self.assertTrue(transport.call_args.args[1].endswith("/v1/responses"))
                elif provider == "anthropic":
                    self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
                else:
                    self.assertTrue(transport.call_args.args[1].endswith("/v1beta/interactions"))
                    self.assertFalse(body["store"])
                    self.assertEqual(body["response_format"]["mime_type"], "application/json")
                    self.assertEqual(body["generation_config"]["max_output_tokens"], 65536)
                self.assertEqual(usage["provider"], provider)
                transport.side_effect = ProviderError("developer_settings_required")
                with self.assertRaises(ProviderError):
                    Evaluator().evaluate(config, context, lambda: None)
                self.assertEqual(transport.call_count, 2)

    def test_incomplete_refusal_and_invalid_json_are_not_scores(self):
        config = {**configuration("gemini-test")["dog"], "provider": "openai", "model": "gpt-test"}
        for result, expected in [({"status": "incomplete", "output": []}, "evaluation_incomplete"),
            ({"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}, "evaluation_refused"),
            ({"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]}, "evaluation_schema_invalid")]:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}), patch("app.evaluation.request", return_value=({**result, "usage": {"input_tokens": 19}}, {})):
                with self.assertRaises(ProviderError) as caught:
                    Evaluator().evaluate(config, {"branch": "dog"}, lambda: None)
            self.assertEqual(caught.exception.code, expected)
            self.assertEqual(caught.exception.usage["input_tokens"], 19)
