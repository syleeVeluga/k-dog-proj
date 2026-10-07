"""Synthetic narrative contracts and real worker/immutable-output boundaries."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app import analysis, maintenance, report_narrative_v4 as narrative, report_profile_v4 as profiles, report_runs_v4 as runs, usage
from app.domain.report_runs_v4 import ReportPublicationV4
from app.gemini import ProviderError
from app.storage import Store, encode, uid
from app.worker import Worker
from tests.report_fixture_v4 import fixture
from tests import test_report_runs_v4 as support


def generated(context):
    facts = {item["fact_id"]: item for item in context["facts"]}
    observed = next((key for key, item in facts.items() if item["kind"] in ("observation", "survey") and item["value"] is not None), None)
    def claim(fact_id, text="기록된 관찰 범위에서 함께 확인해 주세요."):
        return {"text": text, "fact_ids": [fact_id]}
    return {**context["identity"], "cards": [{"key": item["key"], "claims": [claim("final:"+item["key"] if "final:"+item["key"] in facts else "policy:scope")]} for item in context["cards"]],
        "details": [claim(observed)] if observed else [], "summary": [claim("policy:scope")],
        "actions": [claim(observed, "관찰된 상황에서는 편안한 거리를 확보하고 반응을 확인해 주세요.")] if observed and context["action_capacity"] else []}


class NarrativeContractTests(unittest.TestCase):
    def setUp(self):
        self.final, self.ref, self.batch = fixture({"개18": 1, "보23": 2, "보16": 1}, survey={"s01": 2}, opinion={"priority_help": "짧고 예측 가능한 일상부터 도움", "domains": [{"domain": "attachment", "text": "원문은 보존되어야 합니다."}]})
        self.profile = profiles.build(self.final, self.ref, batch=self.batch)
        self.context = narrative.context_for(self.profile)

    def test_generated_content_preserves_facts_final_types_and_priority_help(self):
        assessment = narrative.normalize(self.profile, generated(self.context), "gemini-3.8-flash")
        result = narrative.apply(self.profile, assessment)
        self.assertEqual(result.facts, self.profile.facts)
        self.assertEqual([item.label for item in result.cards], [item.label for item in self.profile.cards])
        self.assertEqual(result.actions[0].validation, "human_verbatim")
        self.assertEqual(result.actions[0].text, self.final.priority_help)
        self.assertEqual(result.provider_text_status, "generated_professor_test_pending")
        self.assertEqual(narrative.validate(self.profile, result), result)
        profiles.validate_profile(result, self.final, self.ref, batch=self.batch)

    def test_foreign_refs_numbers_markup_wrong_type_and_private_example_reject(self):
        for edit in ({"fact_ids": ["unknown"]}, {"text": "누락은 0입니다."}, {"text": "<script>alert()</script>"},
                     {"text": "확률은 높습니다."}, {"text": "거리를 두고 지내는 사이"}, {"text": "견본 사례의 반응입니다."}, {"text": "누락은 ０입니다."}):
            raw = generated(self.context)
            raw["summary"][0].update(edit)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                narrative.normalize(self.profile, raw, "gemini-3.8-flash")
        raw = generated(self.context); raw["input_hash"] = "f"*64
        with self.assertRaises(ValueError):
            narrative.normalize(self.profile, raw, "gemini-3.8-flash")

    def test_numeric_slot_uses_exact_program_value_and_requires_support(self):
        fact = next(item for item in self.profile.facts if item.kind in ("metric", "survey") and type(item.value) in (float, int))
        raw = generated(self.context)
        raw["summary"] = [{"text": "고정된 계산값은 [["+fact.fact_id+"]]입니다.", "fact_ids": [fact.fact_id]}]
        result = narrative.apply(self.profile, narrative.normalize(self.profile, raw, "gemini-3.8-flash"))
        self.assertIn(str(fact.value), result.summary[0].text)
        if fact.kind == "survey":
            self.assertIn(f"{fact.value} (원척도 {fact.unit})", result.summary[0].text)
        raw["summary"][0]["fact_ids"] = ["policy:scope"]
        with self.assertRaises(ValueError):
            narrative.normalize(self.profile, raw, "gemini-3.8-flash")

    def test_numeric_slot_rejects_model_added_units(self):
        for suffix in ("%", "퍼센트", "점", " 회", "배", "명", "개", "국면", "분", "초", "세", "등급", "비율"):
            raw = generated(self.context)
            raw["summary"] = [{"text": "설문 결과는 [[survey:s01]]"+suffix+"입니다.", "fact_ids": ["survey:s01"]}]
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "unit or scale"):
                narrative.normalize(self.profile, raw, "gemini-3.8-flash")

    def test_card_rejects_another_domains_type_and_unreferenced_type(self):
        final, ref, batch = fixture({"개18": 1, "보23": 2}, opinion={"domains": [
            {"domain": "attachment", "label": "곁에서 안심하는 사이", "text": "확인한 애착 의견", "reason": "관찰 근거 확인", "evidence_codes": ["개18"], "counter_note": "반대 근거 없음"},
            {"domain": "education_attitude", "label": "허용형", "text": "확인한 교육 의견", "reason": "관찰 근거 확인", "evidence_codes": ["보23"], "counter_note": "반대 근거 없음"}]})
        profile = profiles.build(final, ref, batch=batch)
        context = narrative.context_for(profile)
        raw = generated(context)
        card = next(item for item in raw["cards"] if item["key"] == "attachment")
        card["claims"] = [{"text": "애착 유형은 허용형입니다.", "fact_ids": ["final:education_attitude"]}]
        with self.assertRaisesRegex(ValueError, "another final type"):
            narrative.normalize(profile, raw, "gemini-3.8-flash")
        raw = generated(context)
        raw["summary"] = [{"text": "허용형으로 살펴봅니다.", "fact_ids": ["policy:scope"]}]
        with self.assertRaisesRegex(ValueError, "contradictory type"):
            narrative.normalize(profile, raw, "gemini-3.8-flash")
        raw["summary"][0]["fact_ids"] = ["final:education_attitude"]
        result = narrative.apply(profile, narrative.normalize(profile, raw, "gemini-3.8-flash"))
        profiles.validate_profile(result, final, ref, batch=batch)

    def test_archived_instructions_replay_without_current_asset_and_mutation_rejects(self):
        result = narrative.apply(self.profile, narrative.normalize(self.profile, generated(self.context), "gemini-3.8-flash"))
        with patch.object(narrative, "instructions", side_effect=AssertionError("archived read")):
            narrative.validate(self.profile, result)
        changed = result.model_copy(update={"summary": self.profile.summary})
        with self.assertRaises(ValueError):
            narrative.validate(self.profile, changed)

    def test_missing_survey_has_no_action_capacity(self):
        final, ref, batch = fixture()
        profile = profiles.build(final, ref, batch=batch)
        context = narrative.context_for(profile)
        self.assertEqual(context["action_capacity"], 0)
        raw = generated(context)
        raw["actions"] = [{"text": "새 도움을 시도해 보세요.", "fact_ids": ["survey-raw:s01"]}]
        with self.assertRaises(ValueError):
            narrative.normalize(profile, raw, "gemini-3.8-flash")

    def test_valid_zero_on_zero_to_four_survey_is_not_missing(self):
        final, ref, batch = fixture(survey={"s10": 0})
        profile = profiles.build(final, ref, batch=batch)
        context = narrative.context_for(profile)
        self.assertEqual(context["action_capacity"], 3)
        narrative.normalize(profile, generated(context), "gemini-3.8-flash")


class NarrativeRunTests(unittest.TestCase):
    def setUp(self):
        self.helper = support.ReportRunV4Tests()
        self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        self.helper.historical_config.stop()
        self.store = self.helper.store
        self.calls = []

    def work(self, operation=None, failure=None):
        calls = self.calls
        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard(); self.assertEqual(files, []); calls.append(context)
                if operation: operation(context)
                if failure: raise failure
                return generated(context), {"provider_usage": {"total_tokens": 12}}
        self.assertTrue(Worker(self.store, observer=Provider()).once())

    def issue(self):
        row = self.helper.enqueue(); self.work()
        self.assertEqual(self.helper.row(row["run_id"])["status"], "succeeded")
        return row["run_id"]

    def manifest(self, run_id):
        data, _, _ = runs.download(self.store, self.helper.case_id, self.helper.session_id, run_id, "manifest", self.helper.user)
        return ReportPublicationV4.model_validate_json(data)

    def test_real_pipeline_separate_content_hash_calls_usage_and_download_no_recall(self):
        run_id = self.issue()
        source = runs.snapshot_for(self.helper.row(run_id))
        output = self.manifest(run_id)
        self.assertEqual(output.input_profile_hash, source.profile_hash)
        self.assertNotEqual(output.output.profile_hash, source.profile_hash)
        self.assertEqual(output.output.profile_hash, analysis.digest(output.profile.model_dump(mode="json")))
        self.assertIsNotNone(output.content)
        self.assertEqual(output.pending_reasons, ())
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("manifest_ref", encode(self.calls[0]))
        self.assertEqual(json.loads(self.helper.row(run_id)["input_snapshot_json"])["profile"], source.profile.model_dump(mode="json"))
        for format in ("html", "pdf", "manifest"):
            runs.download(self.store, self.helper.case_id, self.helper.session_id, run_id, format, self.helper.user)
        self.assertEqual(len(self.calls), 1)
        view = runs.view(self.store, run_id, self.helper.user)
        self.assertEqual(sum(item["provider_calls"] for item in view["steps"]), 1)
        self.assertEqual(view["steps"][0]["token_meters"], {"total_tokens": 12})
        self.assertEqual(usage.summarize(self.store)["calls_reserved"], 1)

    def test_explicit_reuse_copies_validated_narrative_without_provider(self):
        old = self.issue()
        request = self.helper.request.model_copy(update={"request_id": uid(), "reuse_run_id": old})
        new = self.helper.enqueue(request)
        self.work()
        self.assertEqual(self.helper.row(new["run_id"])["status"], "succeeded")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.manifest(new["run_id"]).profile, self.manifest(old).profile)
        self.assertNotEqual(self.manifest(new["run_id"]).content, self.manifest(old).content)

    def test_timeout_is_retry_wait_without_issued_output(self):
        created = self.helper.enqueue()
        self.work(failure=ProviderError("provider_timeout", retryable=True, uncertain=True))
        row = self.helper.row(created["run_id"])
        self.assertEqual((row["status"], row["result_ref"]), ("retry_wait", None))
        self.assertTrue(runs.view(self.store, row["run_id"], self.helper.user)["steps"][0]["billing_uncertain"])

    def test_late_stop_cannot_adopt_or_publish_generated_text(self):
        created = self.helper.enqueue()
        self.work(operation=lambda _: self.helper.action(created["run_id"]))
        row = self.helper.row(created["run_id"])
        self.assertEqual((row["status"], row["result_ref"]), ("stopped", None))

    def test_response_contract_has_one_repair_with_shared_attempt_budget(self):
        created = self.helper.enqueue()
        self.work(operation=lambda context: context["identity"].update(input_hash="f"*64))
        self.assertEqual(self.helper.row(created["run_id"])["status"], "retry_wait")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET retry_at='2000-01-01T00:00:00Z' WHERE run_id=?", (created["run_id"],))
        self.work()
        self.assertEqual(self.helper.row(created["run_id"])["status"], "succeeded")
        self.assertIn("repair", self.calls[1])
        self.assertEqual(len(self.calls), 2)

    def test_two_invalid_responses_stop_without_successful_publication(self):
        created = self.helper.enqueue()
        invalid = lambda context: context["identity"].update(input_hash="f"*64)
        self.work(operation=invalid)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET retry_at='2000-01-01T00:00:00Z' WHERE run_id=?", (created["run_id"],))
        self.work(operation=invalid)
        row = self.helper.row(created["run_id"])
        self.assertEqual((row["status"], row["result_ref"]), ("failed", None))
        self.assertEqual(len(self.calls), 2)

    def test_blocking_input_requires_review_without_provider(self):
        original = runs.profiles.from_final
        def blocked(*args, **kwargs):
            from app.domain.report_profile_v4 import ValidationIssueV4
            result = original(*args, **kwargs)
            return result.model_copy(update={"status": "review_required", "validation_issues": (ValidationIssueV4(code="synthetic", target="summary", reason="synthetic review", blocking=True),)})
        with patch.object(runs.profiles, "from_final", side_effect=blocked):
            created = self.helper.enqueue()
        self.work()
        self.assertEqual(self.helper.row(created["run_id"])["status"], "review_required")
        self.assertEqual(self.calls, [])

    def test_generated_content_survives_backup_restore_and_deleted_case_cleanup(self):
        run_id = self.issue()
        before = self.manifest(run_id)
        root = Path(self.helper.helper.temp.name)
        maintenance.backup(self.store, root/"narrative-backup", "operator")
        maintenance.restore(self.store, root/"narrative-backup", root/"narrative-restored")
        restored = Store(root/"narrative-restored")
        raw, _, _ = runs.download(restored, self.helper.case_id, self.helper.session_id, run_id, "manifest", self.helper.user)
        self.assertEqual(ReportPublicationV4.model_validate_json(raw), before)
        self.assertTrue(restored.path(before.content.ref).exists())
        with restored.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.helper.case_id,))
        maintenance.clean(restored, purge_deleted=True)
        self.assertFalse(restored.path(before.content.ref).exists())

    def test_actual_renderers_receive_exact_generated_profile(self):
        from app.report_render_v4 import render_html
        from app.report_pdf_v4 import render_pdf
        self.helper.render.side_effect = lambda profile, header, images: (render_html(profile, header, images), render_pdf(profile, header, images))
        run_id = self.issue()
        publication = self.manifest(run_id)
        html, _, _ = runs.download(self.store, self.helper.case_id, self.helper.session_id, run_id, "html", self.helper.user)
        pdf, _, _ = runs.download(self.store, self.helper.case_id, self.helper.session_id, run_id, "pdf", self.helper.user)
        self.assertIn(publication.profile.summary[0].text.encode(), html)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10000)
