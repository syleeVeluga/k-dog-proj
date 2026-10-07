"""Synthetic attachment contracts, actual pipeline and opinion-revision fences."""
import copy
import json
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app import analysis, attachment_ai_v4 as attachment, attachment_runs_v4 as runs, final_results_v4 as finals
from app import judgements_v4 as judgements, opinions_v4 as opinions, report_profile_v4 as reports, scoring_ai_v4 as scoring, settings_v4 as settings, sheets_v4 as sheets
from app.domain.attachment_v4 import AttachmentAssessmentV4, AttachmentReferenceV4
from app.domain.contracts_v4 import ATTACHMENT_TYPES
from app.domain.final_results_v4 import FinalReferenceV4, FinalResultV4
from app.domain.results_v4 import BasicResultV4
from app.domain.sheets_v4 import SheetReferenceV4
from app.gemini import ProviderError
from app.storage import encode, uid
from app.worker import Worker
from tests.report_fixture_v4 import fixture
from tests.test_opinions_v4 import model, setup_case, save_opinion, result_reference
from tests import test_run_v4 as run_support


def selected(context, label=ATTACHMENT_TYPES[0], refs=("개18:0",)):
    return {**context["identity"], "status": "selected", "label": label, "reason": "재회에서 실제 접근을 확인하고 반대 근거를 함께 검토했습니다.",
        "evidence_refs": list(refs), "counter_evidence_refs": [], "counter_note": "입력된 다른 유효 근거를 검토했으며 뚜렷한 반대 양상을 확인하지 못했습니다.", "hold_reason": None}


class AttachmentContractTests(unittest.TestCase):
    def setUp(self):
        self.final, self.pointer, self.batch = fixture({"개18": 1})
        self.basic = self.final.basic_document
        self.context = attachment.context_for(self.basic.input_document, self.basic.input, self.basic.calculations.model_dump(mode="json"))

    def test_four_types_are_evidence_linked_and_report_consumes_same_type(self):
        for label in ATTACHMENT_TYPES:
            with self.subTest(label=label):
                assessment = attachment.normalize(self.context, selected(self.context, label), "gemini-3.8-flash")
                decision = attachment.validate(assessment, self.basic.input_document, self.basic.input, self.basic.calculations.model_dump(mode="json"))
                data = self.basic.model_dump(mode="json")
                decisions = [item.model_dump(mode="json") if item.key != "attachment_type" else decision.model_dump(mode="json") for item in self.basic.decisions]
                data.update(attachment_assessment=assessment.model_dump(mode="json"), automatic_decisions=decisions, decisions=decisions,
                    decision_sources={"owner_type": "automatic", "attachment_type": "ai"})
                basic = BasicResultV4.model_validate_json(encode(data))
                final = self.final.model_copy(update={"basic_document": basic, "domains": finals.domains_for(basic, None), "interpretation_policy": attachment.VERSION})
                profile = reports.build(final, self.pointer, batch=self.batch)
                card = next(item for item in profile.cards if item.key == "attachment")
                self.assertEqual(card.label, label)
                self.assertIn("card-judgement:attachment", {claim.claim_id for claim in card.claims})
                self.assertEqual(basic.calculations, self.basic.calculations)

    def test_unknown_type_foreign_input_absent_refs_conflict_and_unreviewed_counter_reject(self):
        for edit in ({"label": "안정형"}, {"input_hash": "f"*64}, {"instruction_hash": "f"*64}, {"evidence_refs": ["개18:99"]},
                     {"counter_evidence_refs": ["개18:0"]}, {"counter_note": None}, {"evidence_refs": []}, {"hold_reason": "conflicting hold"}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                attachment.normalize(self.context, {**selected(self.context), **edit}, "gemini-3.8-flash")

    def test_missing_data_held_is_not_a_fifth_type_and_instructions_are_immutable(self):
        held = attachment.held(self.context, "기회·관찰 부족")
        self.assertIsNone(held.response.label)
        self.assertEqual(held.response.status, "held")
        damaged = held.model_copy(update={"instruction_snapshot": {**held.instruction_snapshot, "source": "modified"}})
        with self.assertRaises(ValueError):
            attachment.validate(damaged, self.basic.input_document, self.basic.input, self.basic.calculations.model_dump(mode="json"))
        with patch.object(attachment, "instructions", side_effect=AssertionError("archived read must not load new instructions")):
            attachment.validate(held, self.basic.input_document, self.basic.input, self.basic.calculations.model_dump(mode="json"))

    def test_opportunity_absence_cannot_be_support(self):
        doc = self.basic.input_document
        rows = tuple(item.model_copy(update={"status": "no_opportunity", "opportunity": "absent", "value": None, "reason": "no contact"}) if item.code == "개18" else item for item in doc.sheet.observations)
        changed = doc.model_copy(update={"sheet": doc.sheet.model_copy(update={"observations": rows})})
        context = attachment.context_for(changed, self.basic.input, self.basic.calculations.model_dump(mode="json"))
        with self.assertRaises(ValueError):
            attachment.normalize(context, selected(context), "gemini-3.8-flash")


class AttachmentOpinionTests(unittest.TestCase):
    def setUp(self):
        setup_case(self)
        # Reopen only synthetic source to add an actual attachment evidence row.
        opened = sheets.revise(self.store, self.sheet["sheet_id"], model(sheets.SheetReasonV4, expected_revision=self.sheet["revision"], reason="synthetic attachment"), self.user, "reopen")
        raw = [item.model_dump(mode="json") for item in sheets.document_for(self.store, opened).sheet.observations]
        recording = sheets.document_for(self.store, opened).source.session.recording_s1
        from app.recording_v4 import build_windows_v4
        from app.domain.catalog_v4 import load_catalog_v4
        window_id = next(item for item in load_catalog_v4().rated_items() if item.code == "개18").windows[0]
        window = next(item for item in build_windows_v4(recording) if item.window_id == window_id)
        raw = [self.helper.observe("개18", 1, window_id, window.start_seconds, window.end_seconds, True) if item["code"] == "개18" else item for item in raw]
        updated = self.helper.save(opened, raw, "operator")
        submitted = sheets.revise(self.store, updated["sheet_id"], model(sheets.SheetReasonV4, expected_revision=updated["revision"], reason="synthetic submit"), self.user, "submit")
        self.basic = judgements.create(self.store, submitted["sheet_id"], model(judgements.CalculateV4, input={"sheet_id": submitted["sheet_id"], "revision": submitted["revision"], "ref": submitted["manifest_ref"], "hash": submitted["manifest_hash"]}), self.user)
        self.basic_ref = result_reference(self.basic)
        self.opinion = save_opinion(self, domains=[{"domain": "attachment", "text": "재회 후 다가와 곁에서 몸이 편안해졌습니다."}])
        with self.store.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO users(username,role,password_hash) VALUES('developer','developer','synthetic')")
            case = self.store.case(db, self.case_id)
            manifest = self.store.manifest(case)
            manifest.consents.analysis_feedback = "confirmed"
            self.store.save(db, case, manifest, "operator", "synthetic.consent")
        pipeline = settings.defaults().model_dump(mode="json")
        pipeline["raw_observation_scope_confirmed"] = True
        draft = settings.save(self.store, model(settings.AiDraftV4, expected_active="inactive", config=pipeline), "developer")
        settings.activate(self.store, draft["version"], settings.AiActivateV4(expected_active="inactive"), "developer")

    def start(self):
        return runs.enqueue(self.store, self.case_id, self.session_id, model(runs.AttachmentStartV4, request_id=uid(), basic=self.basic_ref, opinion=self.opinion["reference"]), self.user)

    def complete(self, operation=None):
        calls = []
        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard(); calls.append(context)
                self.assertEqual(files, [])
                if operation:
                    operation(context)
                return selected(context), {"provider_usage": {"total_tokens": 8}}
        run = self.start()
        Worker(self.store, observer=Provider()).once()
        return runs.view(self.store, self.case_id, self.session_id, run["run_id"], self.user), calls

    def test_opinion_interpretation_preserves_basic_and_original_text_withdrawal_blocks_reuse(self):
        before = copy.deepcopy(self.basic)
        run, calls = self.complete()
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual((len(calls), run["reserved_calls"]), (1, 1))
        self.assertEqual(calls[0]["source"], "completed_opinion_inference")
        value = model(finals.AssembleFinalV4, basic=self.basic_ref, opinion=self.opinion["reference"], attachment_inference=run["reference"], reason="synthetic inference")
        result = finals.assemble(self.store, self.case_id, self.session_id, value, self.user)
        domain = next(item for item in result["document"]["domains"] if item["domain"] == "attachment")
        self.assertEqual(domain["source"], "completed_opinion_inference")
        self.assertEqual(domain["label"], ATTACHMENT_TYPES[0])
        self.assertEqual(domain["text"], self.opinion["document"]["domains"][0]["text"])
        self.assertFalse(result["document"]["independent_ai"])
        self.assertEqual(judgements.view(self.store, before["document"]["result_id"], self.user)["document"], before["document"])
        withdrawn = opinions.action(self.store, self.case_id, self.session_id, model(opinions.OpinionActionV4, expected_revision=1, reason="synthetic withdraw"), self.user, "withdraw")
        with self.assertRaises(HTTPException):
            finals.assemble(self.store, self.case_id, self.session_id, value, self.user)
        changed = value.model_copy(update={"opinion": model(type(value.opinion), **withdrawn["reference"])})
        with self.assertRaises(HTTPException):
            finals.assemble(self.store, self.case_id, self.session_id, changed, self.user)
        link = result["reference"]
        self.assertEqual(finals.read_document(self.store, link["ref"], link["hash"]).final_id, link["final_id"])

    def test_opinion_withdrawn_during_provider_cannot_adopt(self):
        def withdraw(context):
            opinions.action(self.store, self.case_id, self.session_id, model(opinions.OpinionActionV4, expected_revision=1, reason="synthetic late withdraw"), self.user, "withdraw")
        run, calls = self.complete(withdraw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(run["status"], "failed")
        self.assertIsNone(run["reference"])

    def test_revoked_actor_cannot_adopt_opinion_inference(self):
        def revoke(context):
            with self.store.connect(write=True) as db:
                db.execute("UPDATE users SET active=0 WHERE username='operator'")
        run = self.start()
        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard(); revoke(context)
                return selected(context), {}
        Worker(self.store, observer=Provider()).once()
        with self.store.connect() as db:
            row = runs.row_for(db, run["run_id"])
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["result_ref"])

    def test_media_hash_change_during_opinion_provider_blocks_adoption(self):
        def tamper(context):
            path = self.store.path(self.basic["document"]["input_document"]["source"]["session"]["videos"][0]["storage_ref"])
            path.write_bytes(b"changed synthetic source")
        run, calls = self.complete(tamper)
        self.assertEqual((run["status"], run["reference"]), ("failed", None))

    def test_explicit_type_is_not_overwritten_and_new_opinion_revision_needs_new_inference(self):
        run, calls = self.complete()
        reopened = opinions.action(self.store, self.case_id, self.session_id, model(opinions.OpinionActionV4, expected_revision=1, reason="synthetic clarify"), self.user, "reopen")
        self.opinion = save_opinion(self, expected_revision=reopened["reference"]["revision"], domains=[{"domain": "attachment", "text": "거리 양상을 다시 검토한 완료 의견", "label": ATTACHMENT_TYPES[2], "reason": "유효 원관찰을 확인한 명시 선택", "evidence_codes": ["개18"], "counter_note": "반대 근거 검토 완료"}])
        with self.assertRaises(HTTPException):
            self.start()
        result = finals.assemble(self.store, self.case_id, self.session_id, model(finals.AssembleFinalV4, basic=self.basic_ref, opinion=self.opinion["reference"], reason="synthetic explicit priority"), self.user)
        domain = next(item for item in result["document"]["domains"] if item["domain"] == "attachment")
        self.assertEqual((domain["source"], domain["label"]), ("completed_opinion", ATTACHMENT_TYPES[2]))


class AttachmentPipelineTests(unittest.TestCase):
    def setUp(self):
        self.helper = run_support.RunV4Tests(); self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        self.store = self.helper.store

    def pipeline(self, failure=None):
        pipeline = settings.defaults(); pipeline.raw_observation_scope_confirmed = True
        config = scoring.configuration(None, pipeline).model_copy(update={"max_attempts": 1})
        run = self.helper.enqueue(config=config)
        calls = []
        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard(); calls.append(context)
                if context.get("task") == "attachment_v4":
                    if failure:
                        raise ProviderError(failure, retryable=False)
                    return selected(context), {}
                observations = [{"code": item["code"], "value": None, "status": "unobserved", "reason": "synthetic missing"} for item in context["items"]]
                for item in observations:
                    if item["code"] == "개18":
                        definition = next(value for value in context["items"] if value["code"] == "개18")
                        window = next(value["window"] for value in context["windows"] if value["window"]["window_id"] == definition["windows"][0])
                        item.update(value=1, status="observed", opportunity="present", validity="valid", evidence=[{"clip_id": "c1", "window_id": window["window_id"], "start_seconds": window["start_seconds"], "end_seconds": window["end_seconds"], "observed_seconds": window["end_seconds"]-window["start_seconds"], "note": "synthetic reunion approach"}])
                return {**context["identity"], "observations": observations}, {}
        Worker(self.store, observer=Provider()).once()
        status = __import__('app.run_v4', fromlist=['view']).view(self.store, run["run_id"], self.helper.user)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM basic_results WHERE case_id=?", (self.helper.case_id,)).fetchone()
        self.assertIsNotNone(row)
        basic = judgements.document_for(self.store, row)
        return status, basic, calls

    def test_actual_provider_to_basic_final_and_report_evidence(self):
        status, basic, calls = self.pipeline()
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(status["reserved_calls"], 43)
        self.assertEqual(basic.attachment_assessment.response.label, ATTACHMENT_TYPES[0])
        self.assertNotIn("completed_opinion", calls[-1]["facts"])
        self.assertEqual(finals.domains_for(basic, None)[0].label, ATTACHMENT_TYPES[0])
        # Physical media probing is synthetic; disclosure, parent pins and assembly are real.
        with patch.object(sheets, "validate_recording_media_v4", return_value={"v1": 300.0}):
            viewer = sheets.assign(self.store, self.helper.case_id, self.helper.session_id, model(sheets.SheetAssignmentV4,
                expected_revision=self.helper.current()["input_revision"], assigned_username="operator", rater_id="synthetic-independent-viewer",
                rater_name="합성 독립 검토자", source_sheet_id=basic.input.sheet_id), self.helper.user)
            rows = [{"code": item.code, "value": None, "status": "unobserved", "reason": "synthetic independent missing"} for item in basic.input_document.sheet.observations]
            viewer = sheets.revise(self.store, viewer["sheet_id"], model(sheets.SheetEditV4, expected_revision=viewer["revision"], observations=rows, reason="synthetic independent input"), self.helper.user, "save")
            viewer = sheets.revise(self.store, viewer["sheet_id"], model(sheets.SheetReasonV4, expected_revision=viewer["revision"], reason="synthetic independent submit"), self.helper.user, "submit")
            sheets.grant(self.store, viewer["sheet_id"], model(sheets.SheetGrantV4, expected_revision=viewer["revision"], target_sheet_id=basic.input.sheet_id, target_revision=basic.input.revision, reason="synthetic explicit AI grant"), self.helper.user)
            sheets.revise(self.store, viewer["sheet_id"], model(sheets.SheetRevealV4, expected_revision=viewer["revision"], ref=basic.input.ref), self.helper.user, "reveal")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM basic_results WHERE result_id=?", (basic.result_id,)).fetchone()
        result = finals.assemble(self.store, self.helper.case_id, self.helper.session_id, model(finals.AssembleFinalV4,
            basic=judgements.reference(row), viewer_sheet_id=viewer["sheet_id"], reason="synthetic AI final via real disclosure"), self.helper.user)
        pinned = finals.read_document(self.store, result["reference"]["ref"], result["reference"]["hash"])
        profile = reports.build(pinned, model(FinalReferenceV4, **result["reference"]), batch=self.helper.batch)
        card = next(item for item in profile.cards if item.key == "attachment")
        self.assertEqual(card.label, ATTACHMENT_TYPES[0])
        fact = next(item for item in profile.facts if item.fact_id == "attachment:reason")
        self.assertEqual(fact.item_codes, ("개18",))

    def test_timeout_preserves_valid_raw_calculation_with_attachment_held_and_partial_status(self):
        status, basic, calls = self.pipeline("provider_timeout")
        self.assertEqual((status["status"], status["result_available"]), ("partial_failed", True))
        self.assertIsNone(basic.attachment_assessment.response.label)
        self.assertIn("provider_timeout", basic.attachment_assessment.response.hold_reason)
        self.assertEqual(next(item for item in basic.input_document.sheet.observations if item.code == "개18").value, 1)


if __name__ == "__main__":
    unittest.main()
