"""Independent regressions for interpretation exposure and immutable blind originals."""
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import disclosures_v4 as disclosure, final_results_v4 as finals, opinions_v4 as opinions, sheets_v4 as sheets
from app import judgements_v4 as basics, maintenance
from app.storage import Store
from tests.test_opinions_v4 import model, setup_case


class DisclosureV4Tests(unittest.TestCase):
    def setUp(self):
        setup_case(self)
        self.admin = self.helper.people["admin"]
        self.admin_sheet = self.helper.assign("admin")
        self.admin_sheet = self.helper.submit(self.admin_sheet, "admin")
        self.helper.grant(self.admin_sheet, self.sheet)
        self.admin_sheet = self.helper.reveal(self.admin_sheet, self.sheet, "admin")["viewer"]
        self.opinion = opinions.save(self.store, self.case_id, self.session_id, model(opinions.OpinionWriteV4,
            expected_revision=0, basic=self.basic_ref, viewer_sheet_id=self.admin_sheet["sheet_id"], evaluator="Other synthetic evaluator",
            completion_requested=True, domains=[{"domain":"education_attitude", "text":"Other evaluator's synthetic interpretation"}],
            reason="synthetic interpretation"), self.admin)

    def request(self, pointer=None, row=None):
        row = row or self.sheet
        return model(disclosure.InterpretationRevealV4, target=(pointer or disclosure.target("opinion", self.opinion["reference"])).model_dump(mode="json"),
            viewer_sheet_id=row["sheet_id"], expected_viewer_revision=row["revision"], reason="explicit synthetic interpretation reveal")

    def reveal(self, request=None):
        return disclosure.reveal(self.store, self.case_id, self.session_id, request or self.request(), self.user)

    def test_own_basic_does_not_bypass_other_opinion_disclosure_and_original_survives(self):
        old = self.store.path(self.sheet["manifest_ref"]).read_bytes()
        meta = opinions.metadata(self.store, self.case_id, self.session_id, self.user)
        opinions.OpinionMetadataV4.model_validate(meta)
        self.assertTrue(meta["requires_reveal"])
        self.assertNotIn("domains", meta)
        with self.assertRaises(HTTPException):
            opinions.view(self.store, self.case_id, self.session_id, self.user)
        with self.assertRaises(HTTPException):
            finals.assemble(self.store, self.case_id, self.session_id, model(finals.AssembleFinalV4,
                basic=self.basic_ref, opinion=self.opinion["reference"], reason="must reveal first"), self.user)
        with self.assertRaises(HTTPException):
            opinions.action(self.store, self.case_id, self.session_id, model(opinions.OpinionActionV4,
                expected_revision=1, reason="cannot relabel another author through reopen"), self.user, "reopen")
        result = self.reveal()
        disclosure.InterpretationRevealResultV4.model_validate(result)
        shown = opinions.view(self.store, self.case_id, self.session_id, self.user)
        self.assertEqual(shown["document"]["actor"], "admin")
        current = self.helper.view(result["viewer"], "operator")
        sheets.SheetViewV4.model_validate(current)
        self.assertEqual((current["document"]["purpose"], current["effective_purpose"]), ("review", "review"))
        self.assertEqual(current["document"]["exposures"], [])
        self.assertEqual(current["document"]["initial_submission"]["ref"], self.sheet["manifest_ref"])
        self.assertEqual(current["document"]["interpretation_exposures"][0]["target"]["hash"], self.opinion["reference"]["hash"])
        self.assertEqual(self.store.path(self.sheet["manifest_ref"]).read_bytes(), old)
        self.assertEqual(sheets.read_document(self.store, self.sheet["manifest_ref"], self.sheet["manifest_hash"]).purpose, "independent")
        with self.store.connect() as db:
            context = basics.evaluation_context(self.store, db, sheets.row_for(self.store, db, self.sheet["sheet_id"]))
        self.assertEqual(context["purpose"], "review")
        self.assertEqual(len(context["interpretation_exposures"]), 1)

    def test_final_content_requires_its_exact_reveal_and_supports_report_parent_guard(self):
        final = finals.assemble(self.store, self.case_id, self.session_id, model(finals.AssembleFinalV4,
            basic=self.basic_ref, opinion=self.opinion["reference"], viewer_sheet_id=self.admin_sheet["sheet_id"], reason="synthetic final"), self.admin)
        listed = finals.list_results(self.store, self.case_id, self.session_id, self.user)
        self.assertTrue(listed[0]["requires_reveal"])
        self.assertNotIn("document", listed[0])
        with self.assertRaises(HTTPException):
            finals.view(self.store, self.case_id, self.session_id, final["reference"]["final_id"], self.user)
        self.reveal(self.request(disclosure.target("final", final["reference"])))
        viewed = finals.view(self.store, self.case_id, self.session_id, final["reference"]["final_id"], self.user)
        self.assertEqual(viewed["document"], final["document"])
        with self.assertRaises(HTTPException):
            opinions.view(self.store, self.case_id, self.session_id, self.user)

    def test_exact_hash_viewer_revision_and_submission_are_required(self):
        pointer = disclosure.target("opinion", self.opinion["reference"]).model_copy(update={"hash":"0"*64})
        with self.assertRaises(HTTPException):
            self.reveal(self.request(pointer))
        reopened = sheets.revise(self.store, self.sheet["sheet_id"], model(sheets.SheetReasonV4,
            expected_revision=self.sheet["revision"], reason="synthetic reopen"), self.user, "reopen")
        with self.assertRaises(HTTPException):
            self.reveal()
        with self.assertRaises(HTTPException):
            self.reveal(self.request(row=reopened))
        with self.store.connect() as db:
            self.assertEqual(list(disclosure.records(db, self.case_id, self.session_id)), [])

    def test_late_deletion_or_new_viewer_blob_damage_never_adopts(self):
        write = sheets.write_document
        def deleted(store, data):
            result = write(store, data)
            with store.connect(write=True) as db:
                db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
            return result
        with patch.object(sheets, "write_document", side_effect=deleted), self.assertRaises(HTTPException):
            self.reveal()
        with self.store.connect(write=True) as db:
            self.assertEqual(list(disclosure.records(db, self.case_id, self.session_id)), [])
            db.execute("UPDATE cases SET deletion_requested=0 WHERE case_id=?", (self.case_id,))
        def damaged(store, data):
            result = write(store, data)
            store.path(result[0]).write_bytes(b"{}")
            return result
        with patch.object(sheets, "write_document", side_effect=damaged), self.assertRaises(HTTPException):
            self.reveal()
        self.assertEqual(self.helper.view(self.sheet, "operator")["document"]["revision"], self.sheet["revision"])
        with self.store.connect() as db:
            self.assertEqual(list(disclosure.records(db, self.case_id, self.session_id)), [])

    def test_future_batch_and_other_sheet_revisions_inherit_interpretation_exposure(self):
        other = self.helper.assign("operator", purpose="consensus")
        self.reveal()
        before = self.helper.view(other, "operator")
        self.assertEqual(len(before["interpretation_exposures"]), 1)
        changed = self.helper.save(other, [], "operator")
        self.assertEqual(len(self.helper.view(changed, "operator")["document"]["interpretation_exposures"]), 1)
        fresh = self.helper.assign("operator", batch="synthetic-new-batch")
        self.assertEqual(fresh["purpose"], "review")
        self.assertEqual(len(self.helper.view(fresh, "operator")["document"]["interpretation_exposures"]), 1)

    def test_disclosure_racing_another_sheet_save_requires_retry(self):
        other = self.helper.assign("operator", purpose="consensus")
        write = sheets.write_document
        def reveal_during_write(store, data):
            result = write(store, data)
            if data["sheet"]["sheet_id"] == other["sheet_id"]:
                self.reveal()
            return result
        with patch.object(sheets, "write_document", side_effect=reveal_during_write), self.assertRaises(HTTPException):
            self.helper.save(other, [], "operator")
        self.assertEqual(self.helper.view(other, "operator")["document"]["revision"], other["revision"])

    def test_backup_restore_preserves_ledger_and_deleted_case_purges_it(self):
        self.reveal()
        root = Path(self.helper.temp.name)
        maintenance.backup(self.store, root/"disclosure-backup", "operator")
        maintenance.restore(self.store, root/"disclosure-backup", root/"disclosure-restored")
        restored = Store(root/"disclosure-restored")
        opinions.view(restored, self.case_id, self.session_id, self.user)
        with restored.connect(write=True) as db:
            self.assertEqual(len(list(disclosure.records(db, self.case_id, self.session_id))), 1)
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
        maintenance.clean(restored, purge_deleted=True)
        with restored.connect() as db:
            self.assertEqual(list(disclosure.records(db, self.case_id, self.session_id)), [])


if __name__ == "__main__":
    unittest.main()
