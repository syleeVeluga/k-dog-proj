"""Independent regressions for interpretation exposure and immutable blind originals."""
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import disclosures_v4 as disclosure, final_results_v4 as finals, opinions_v4 as opinions, sheets_v4 as sheets
from app import judgements_v4 as basics, maintenance
from app.storage import Store
from app.domain.results_v4 import ResultReferenceV4
from app.storage import encode
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

    def test_all_accounts_read_other_opinion_and_final_without_viewer(self):
        final = finals.assemble(self.store, self.case_id, self.session_id,
            model(finals.AssembleFinalV4, basic=self.basic_ref, opinion=self.opinion["reference"], reason="synthetic common final"), self.admin)
        original = self.store.path(self.sheet["manifest_ref"]).read_bytes()
        for user in self.helper.people.values():
            self.assertFalse(opinions.metadata(self.store, self.case_id, self.session_id, user)["requires_reveal"])
            self.assertEqual(opinions.view(self.store, self.case_id, self.session_id, user)["reference"], self.opinion["reference"])
            self.assertEqual(finals.view(self.store, self.case_id, self.session_id, final["reference"]["final_id"], user)["reference"], {k: final["reference"][k] for k in ("final_id", "ref", "hash")})
        self.assertEqual(self.store.path(self.sheet["manifest_ref"]).read_bytes(), original)

    def test_explicit_opinion_read_preserves_first_submission_and_marks_only_later_edit(self):
        from app.activity_v4 import opened
        value = opinions.view(self.store, self.case_id, self.session_id, self.user)
        opened(self.store, self.user, self.case_id, "opinion.open", value, "open", session_id=self.session_id, revision=value["reference"]["revision"])
        self.assertEqual(sheets.view(self.store, self.sheet["sheet_id"], self.user)["effective_purpose"], "independent")
        changed = self.helper.save(self.sheet, [self.helper.observe()], "operator")
        view = sheets.view(self.store, changed["sheet_id"], self.user)
        self.assertEqual(changed["purpose"], "review")
        self.assertEqual(len(view["activity_exposures"]), 1)
        self.assertEqual(sheets.revision(self.store, self.sheet["sheet_id"], self.sheet["revision"], self.admin).purpose, "independent")

    def test_pre_submission_read_and_racing_read_are_not_blind(self):
        from app.activity_v4 import opened
        draft = self.helper.assign("other", source=self.sheet["sheet_id"])
        value = opinions.view(self.store, self.case_id, self.session_id, self.helper.people["other"])
        def open_opinion():
            opened(self.store, self.helper.people["other"], self.case_id, "opinion.open", value, "open", session_id=self.session_id, revision=value["reference"]["revision"])
        write = sheets.write_document
        triggered = False
        def racing(store, data):
            nonlocal triggered
            result = write(store, data)
            if data["sheet"]["sheet_id"] == draft["sheet_id"] and not triggered:
                triggered = True
                open_opinion()
            return result
        with patch.object(sheets, "write_document", side_effect=racing), self.assertRaises(HTTPException) as caught:
            self.helper.save(draft, [self.helper.observe()], "other")
        self.assertEqual(caught.exception.status_code, 409)
        submitted = self.helper.submit(draft, "other")
        self.assertEqual(submitted["purpose"], "review")
        self.assertEqual(len(sheets.view(self.store, draft["sheet_id"], self.admin)["activity_exposures"]), 1)

    def test_exact_hash_damage_is_rejected_for_all_accounts(self):
        wrong = {**self.basic_ref, "hash": "0" * 64}
        with self.store.connect() as db, self.assertRaises(HTTPException) as caught:
            opinions.selected_basic(self.store, db, self.case_id, self.session_id, ResultReferenceV4.model_validate_json(encode(wrong)), self.admin)
        self.assertEqual(caught.exception.status_code, 409)
        self.store.path(self.opinion["reference"]["ref"]).write_bytes(b"{}")
        with self.assertRaises(HTTPException):
            opinions.view(self.store, self.case_id, self.session_id, self.user)

    def test_old_exposure_ledger_remains_read_only_history(self):
        from app.domain.disclosures_v4 import InterpretationExposureV4
        from app.storage import now, uid
        exposure = InterpretationExposureV4(exposure_id=uid(), target=disclosure.target("opinion", self.opinion["reference"]),
            case_id=self.case_id, session_id=self.session_id, source_actor="admin", viewer_username=self.user.username,
            viewer_rater_id="rater-operator", basic_result_id=self.basic_ref["result_id"], basic_revision=self.basic_ref["revision"],
            basic_ref=self.basic_ref["ref"], basic_hash=self.basic_ref["hash"], video_hashes=(self.helper.video_hash,), recorded_at=now(), reason="historical fixture")
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", self.case_id, disclosure.ACTION, {"exposure": exposure.model_dump(mode="json")})
        with self.store.connect() as db:
            self.assertEqual(list(disclosure.records(db, self.case_id, self.session_id)), [exposure])
            self.assertIn(exposure.exposure_id, disclosure.inherited(db, self.case_id, self.session_id, "operator", "rater-operator", sheets.document_for(self.store, sheets.row_for(self.store, db, self.sheet["sheet_id"])).source))

    def test_self_assembled_final_of_other_rater_is_still_an_exposure(self):
        from app.activity_v4 import opened
        reader = self.helper.people["reviewer"]
        draft = self.helper.assign("reviewer", source=self.sheet["sheet_id"])
        final = finals.assemble(self.store, self.case_id, self.session_id,
            model(finals.AssembleFinalV4, basic=self.basic_ref, opinion=self.opinion["reference"], reason="synthetic other source"), reader)
        opened(self.store, reader, final["reference"]["final_id"], "final.open", final, "open", case_id=self.case_id, session_id=self.session_id)
        view = sheets.view(self.store, draft["sheet_id"], reader)
        self.assertEqual(view["effective_purpose"], "review")
        self.assertEqual(len(view["activity_exposures"]), 1)
