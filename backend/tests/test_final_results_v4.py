"""S1 final-domain priority, immutable publication and disclosure boundaries."""
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import final_results_v4 as finals, judgements_v4 as basics, opinions_v4 as opinions
from tests.test_opinions_v4 import model, result_reference, save_opinion, setup_case


def assemble(test, opinion=None, **changes):
    request = {"basic": test.basic_ref, "opinion": opinion["reference"] if opinion else None, "reason": "synthetic explicit selection"}
    request.update(changes)
    return finals.assemble(test.store, test.case_id, test.session_id, model(finals.AssembleFinalV4, **request), test.user)


def domains(value):
    return {item["domain"]: item for item in value["document"]["domains"]}


class FinalResultV4Tests(unittest.TestCase):
    setUp = setup_case

    def manual(self):
        value = model(basics.JudgementEditV4, expected_revision=self.basic["summary"]["revision"], reason="synthetic manual judgement",
            decisions=[{"key":"owner_type", "label":"통제형", "status":"complete", "evidence_codes":["보23"],
                        "counter_note":"synthetic opposing evidence reviewed", "reason":"synthetic evidence"}])
        self.basic = basics.revise(self.store, self.basic["summary"]["result_id"], value, self.user)
        self.basic_ref = result_reference(self.basic)

    def test_no_opinion_preserves_six_domains_missing_and_original_ratios(self):
        value = assemble(self)
        self.assertEqual(len(domains(value)), 6)
        self.assertIsNone(domains(value)["attachment"]["label"])
        self.assertEqual(domains(value)["attachment"]["status"], "policy_pending")
        self.assertEqual(value["document"]["basic_document"], self.basic["document"])
        self.assertFalse(value["document"]["independent_ai"])

    def test_only_completed_education_overrides_that_domain_manual_then_basic(self):
        self.manual()
        before = assemble(self)
        self.assertEqual(domains(before)["education_attitude"]["source"], "manual_selection")
        opinion = save_opinion(self, domains=[{"domain":"education_attitude", "text":"선택한 대응을 기다림과 함께 관찰함",
            "label":"조율형", "reason":"실제 지시 장면에 근거한 선택", "evidence_codes":["보23"], "counter_note":"상반 단서 검토"}])
        after = assemble(self, opinion)
        self.assertEqual(domains(after)["education_attitude"]["label"], "조율형")
        self.assertEqual(domains(after)["education_attitude"]["source"], "completed_opinion")
        self.assertEqual(domains(after)["attachment"], domains(before)["attachment"])
        self.assertEqual(after["document"]["basic_document"], before["document"]["basic_document"])
        self.assertEqual(self.store.path(self.basic_ref["ref"]).read_bytes(), self.store.path(after["document"]["basic"]["ref"]).read_bytes())

    def test_free_text_summary_never_becomes_fifth_attachment_type(self):
        opinion = save_opinion(self, domains=[{"domain":"attachment", "text":"찾고, 차분히 재회"}])
        result = domains(assemble(self, opinion))["attachment"]
        self.assertIsNone(result["label"])
        self.assertEqual(result["text"], "찾고, 차분히 재회")
        self.assertEqual(result["status"], "policy_pending")
        self.assertIn("D04", result["reason"])

    def test_draft_and_help_only_never_override_or_emit_completed_help(self):
        self.manual()
        draft = save_opinion(self, completion_requested=False, priority_help="도움 초안")
        value = assemble(self, draft)
        self.assertEqual(domains(value)["education_attitude"]["source"], "manual_selection")
        self.assertIsNone(value["document"]["priority_help"])
        help_only = save_opinion(self, expected_revision=draft["reference"]["revision"], domains=[], priority_help="도움만")
        self.assertIsNone(assemble(self, help_only)["document"]["priority_help"])

    def test_withdrawal_reverts_new_final_and_old_publication_stays_immutable(self):
        self.manual()
        opinion = save_opinion(self)
        old = assemble(self, opinion)
        old_bytes = self.store.path(old["reference"]["ref"]).read_bytes()
        withdrawn = opinions.action(self.store, self.case_id, self.session_id,
            model(opinions.OpinionActionV4, expected_revision=opinion["reference"]["revision"], reason="synthetic withdrawal"), self.user, "withdraw")
        latest = assemble(self, withdrawn)
        self.assertEqual(domains(latest)["education_attitude"]["source"], "manual_selection")
        self.assertEqual(self.store.path(old["reference"]["ref"]).read_bytes(), old_bytes)
        shown = finals.view(self.store, self.case_id, self.session_id, old["reference"]["final_id"], self.user)
        self.assertEqual(shown["document"]["opinion_document"]["state"], "complete")
        with self.assertRaises(HTTPException):
            assemble(self, opinion)
        with self.assertRaises(HTTPException):
            assemble(self)

    def test_modified_opinion_during_assembly_is_not_adopted(self):
        opinion = save_opinion(self)
        write = finals.write_document
        def withdraw(store, data):
            result = write(store, data)
            opinions.action(store, self.case_id, self.session_id,
                model(opinions.OpinionActionV4, expected_revision=opinion["reference"]["revision"], reason="concurrent withdrawal"), self.user, "withdraw")
            return result
        with patch.object(finals, "write_document", side_effect=withdraw), self.assertRaises(HTTPException):
            assemble(self, opinion)
        self.assertEqual(finals.list_results(self.store, self.case_id, self.session_id, self.user), [])

    def test_deletion_and_basic_corruption_block_reads(self):
        value = assemble(self)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
        with self.assertRaises(HTTPException):
            finals.view(self.store, self.case_id, self.session_id, value["reference"]["final_id"], self.user)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=0 WHERE case_id=?", (self.case_id,))
        self.store.path(self.basic_ref["ref"]).write_text("{}")
        with self.assertRaises(HTTPException):
            finals.view(self.store, self.case_id, self.session_id, value["reference"]["final_id"], self.user)

    def test_another_rater_requires_actual_grant_reveal_before_final_access(self):
        target = self.helper.assign("reviewer")
        target = self.helper.submit(target, "reviewer")
        target_basic = basics.create(self.store, target["sheet_id"], model(basics.CalculateV4,
            input={"sheet_id":target["sheet_id"], "revision":target["revision"], "ref":target["manifest_ref"], "hash":target["manifest_hash"]}), self.helper.people["reviewer"])
        target_ref = result_reference(target_basic)
        for anchor in (None, self.sheet["sheet_id"]):
            with self.assertRaises(HTTPException):
                assemble(self, basic=target_ref, viewer_sheet_id=anchor)
        self.helper.grant(self.sheet, target)
        with self.assertRaises(HTTPException):
            assemble(self, basic=target_ref, viewer_sheet_id=self.sheet["sheet_id"])
        self.helper.reveal(self.sheet, target, "operator")
        value = assemble(self, basic=target_ref, viewer_sheet_id=self.sheet["sheet_id"])
        self.assertEqual(value["document"]["basic"], target_ref | {"schema_version":"4.0"})
        with self.store.connect(write=True) as db:
            db.execute("DELETE FROM score_grants WHERE viewer_sheet_id=?", (self.sheet["sheet_id"],))
        with self.assertRaises(HTTPException):
            finals.view(self.store, self.case_id, self.session_id, value["reference"]["final_id"], self.user, self.sheet["sheet_id"])

    def test_backup_restore_and_deleted_case_cleanup_follow_both_snapshots(self):
        from app import maintenance
        from app.storage import Store
        opinion = save_opinion(self)
        final = assemble(self, opinion)
        root = Path(self.helper.temp.name)
        maintenance.backup(self.store, root/"backup", "operator")
        maintenance.restore(self.store, root/"backup", root/"restored")
        restored = Store(root/"restored")
        shown = finals.view(restored, self.case_id, self.session_id, final["reference"]["final_id"], self.user)
        self.assertEqual(shown["document"]["basic_document"], final["document"]["basic_document"])
        with restored.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
        maintenance.clean(restored, purge_deleted=True)
        for ref in (opinion["reference"]["ref"], final["reference"]["ref"]):
            self.assertFalse(restored.path(ref).exists())

    def test_source_mutation_after_validation_cannot_publish_final(self):
        write = finals.write_document
        def tamper(store, data):
            result = write(store, data)
            store.path("videos/v1.mp4").write_bytes(b"altered source")
            return result
        with patch.object(finals, "write_document", side_effect=tamper), self.assertRaises(HTTPException):
            assemble(self)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='final.s1.publish'").fetchone()[0], 0)

    def test_unsubstantiated_type_remains_pending_and_unknown_evidence_rejected(self):
        opinion = save_opinion(self, domains=[{"domain":"education_attitude", "text":"현장 대응을 기록함", "label":"허용형"}])
        value = assemble(self, opinion)
        self.assertIsNone(domains(value)["education_attitude"]["label"])
        self.assertEqual(domains(value)["education_attitude"]["status"], "policy_pending")
        opinions.action(self.store, self.case_id, self.session_id,
            model(opinions.OpinionActionV4, expected_revision=opinion["reference"]["revision"], reason="revise basis"), self.user, "reopen")
        with self.assertRaises(HTTPException):
            save_opinion(self, expected_revision=2, domains=[{"domain":"attachment", "text":"근거 확인", "evidence_codes":["개19"]}])

    def test_typed_responses_validate_and_old_final_does_not_select_new_basic(self):
        first = assemble(self)
        finals.FinalViewV4.model_validate(first)
        for summary in finals.list_results(self.store, self.case_id, self.session_id, self.user):
            finals.FinalSummaryV4.model_validate(summary)
        self.manual()
        latest = assemble(self)
        self.assertNotEqual(first["document"]["basic"], latest["document"]["basic"])
        shown = finals.view(self.store, self.case_id, self.session_id, first["reference"]["final_id"], self.user)
        self.assertEqual(shown["document"], first["document"])
