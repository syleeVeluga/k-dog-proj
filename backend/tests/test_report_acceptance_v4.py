"""Synthetic RP01–RP04 flow; provider responses and physical probe are fixtures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import final_results_v4 as finals, judgements_v4 as judgements, maintenance
from app import opinions_v4 as opinions, report_runs_v4 as reports, sheets_v4 as sheets
from app.domain.contracts_v4 import ATTACHMENT_TYPES
from app.domain.report_runs_v4 import ReportPublicationV4
from app.storage import Store, uid
from app.worker import Worker
from tests import test_attachment_ai_v4 as support
from tests.test_opinions_v4 import model
from tests.test_report_narrative_v4 import generated


class ReportAcceptanceV4Tests(unittest.TestCase):
    def test_input_to_ai_human_override_narrative_issued_bytes_reuse_and_restore(self):
        helper = support.AttachmentPipelineTests()
        original_save = Store.save

        def save_input(store, db, row, manifest, actor, action):
            if action == "synthetic.recording":
                manifest.sessions[0].survey.update(s10=0, s11=None, s12=0, s13=0, s14=0,
                    s26=1, s27=3, s28=5)
            return original_save(store, db, row, manifest, actor, action)

        with patch.object(Store, "save", save_input):
            helper.setUp()
        self.addCleanup(helper.doCleanups)
        store, source = helper.store, helper.helper
        user, case_id, session_id = source.user, source.case_id, source.session_id
        status, basic, calls = helper.pipeline()
        self.assertEqual((status["status"], status["reserved_calls"], len(calls)), ("succeeded", 43, 43))
        self.assertEqual(basic.attachment_assessment.response.label, ATTACHMENT_TYPES[0])
        input_bytes = store.path(basic.input.ref).read_bytes()
        self.assertEqual(basic.input_document.source.session.survey["s10"], 0)
        self.assertIsNone(basic.input_document.source.session.survey["s11"])

        # Real assignment/submission/grant/reveal; only the synthetic file's probe is replaced.
        with patch.object(sheets, "validate_recording_media_v4", return_value={"v1": 300.0}):
            viewer = sheets.assign(store, case_id, session_id, model(sheets.SheetAssignmentV4,
                expected_revision=source.current()["input_revision"], assigned_username="operator",
                rater_id="synthetic-rp05-viewer", rater_name="합성 독립 검토자", source_sheet_id=basic.input.sheet_id), user)
            rows = [{"code": item.code, "value": None, "status": "unobserved", "reason": "synthetic independent missing"}
                for item in basic.input_document.sheet.observations]
            viewer = sheets.revise(store, viewer["sheet_id"], model(sheets.SheetEditV4,
                expected_revision=viewer["revision"], observations=rows, reason="synthetic independent input"), user, "save")
            viewer = sheets.revise(store, viewer["sheet_id"], model(sheets.SheetReasonV4,
                expected_revision=viewer["revision"], reason="synthetic independent submit"), user, "submit")
            sheets.grant(store, viewer["sheet_id"], model(sheets.SheetGrantV4, expected_revision=viewer["revision"],
                target_sheet_id=basic.input.sheet_id, target_revision=basic.input.revision, reason="synthetic explicit grant"), user)
            sheets.revise(store, viewer["sheet_id"], model(sheets.SheetRevealV4,
                expected_revision=viewer["revision"], ref=basic.input.ref), user, "reveal")
        with store.connect() as db:
            basic_row = db.execute("SELECT * FROM basic_results WHERE result_id=?", (basic.result_id,)).fetchone()
            basic_ref = judgements.reference(basic_row)
            basic_bytes = store.path(basic_row["manifest_ref"]).read_bytes()
        base_final = finals.assemble(store, case_id, session_id, model(finals.AssembleFinalV4,
            basic=basic_ref, viewer_sheet_id=viewer["sheet_id"], reason="synthetic original AI final"), user)
        narrative_calls = []

        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard()
                self.assertEqual(files, [])
                narrative_calls.append(context)
                return generated(context), {"provider_usage": {"total_tokens": 12}}

        def issue(final, reuse=None):
            request = model(reports.ReportStartV4, expected_revision=source.current()["input_revision"],
                request_id=uid(), final=final["reference"], viewer_sheet_id=viewer["sheet_id"], reuse_run_id=reuse)
            row = reports.enqueue(store, case_id, session_id, request, user)
            self.assertEqual(reports.enqueue(store, case_id, session_id, request, user)["run_id"], row["run_id"])
            with patch.object(reports, "capture_images", side_effect=AssertionError("new reports must not extract frames")):
                self.assertTrue(Worker(store, observer=Provider()).once())
            current = reports.view(store, row["run_id"], user, viewer["sheet_id"])
            self.assertEqual(current["status"], "succeeded")
            self.assertFalse(current["outdated"])
            raw, _, _ = reports.download(store, case_id, session_id, row["run_id"], "manifest", user, viewer["sheet_id"])
            publication = ReportPublicationV4.model_validate_json(raw)
            self.assertEqual(publication.final.final_id, final["reference"]["final_id"])
            self.assertEqual(publication.profile.presentation_version, "report-presentation-20261007-rp04")
            self.assertEqual(publication.output.image_issues, {})
            return row["run_id"], publication

        first_id, first = issue(base_final)
        first_pdf, _, _ = reports.download(store, case_id, session_id, first_id, "pdf", user, viewer["sheet_id"])
        original = "합성 완료 의견 원문: 재회 반응과 관찰 범위를 함께 검토했습니다."
        help_text = "합성 우선 도움: 기록된 범위에서 차분히 확인해 주세요."
        opinion = opinions.save(store, case_id, session_id, model(opinions.OpinionWriteV4,
            expected_revision=0, basic=basic_ref, viewer_sheet_id=viewer["sheet_id"], evaluator="Synthetic professor fixture",
            completion_requested=True, domains=[{"domain": "attachment", "text": original,
                "label": ATTACHMENT_TYPES[1], "reason": "synthetic explicit override", "evidence_codes": ["개18"],
                "counter_note": "합성 반대 근거 검토 완료"}],
            priority_help=help_text, reason="synthetic completed opinion"), user)
        final = finals.assemble(store, case_id, session_id, model(finals.AssembleFinalV4,
            basic=basic_ref, opinion=opinion["reference"], viewer_sheet_id=viewer["sheet_id"], reason="synthetic human priority"), user)
        run_id, publication = issue(final)
        card = next(item for item in publication.profile.cards if item.key == "attachment")
        self.assertEqual(card.label, ATTACHMENT_TYPES[1])
        self.assertIn(original, [claim.text for claim in card.claims])
        self.assertEqual(publication.profile.actions[0].text, help_text)
        self.assertEqual(publication.profile.actions[0].validation, "human_verbatim")
        self.assertEqual(store.path(basic.input.ref).read_bytes(), input_bytes)
        self.assertEqual(store.path(basic_row["manifest_ref"]).read_bytes(), basic_bytes)
        facts = {fact.fact_id: fact for fact in publication.profile.facts}
        self.assertEqual(facts["survey:s10"].value, 0)
        self.assertIsNone(facts["survey:s11"].value)
        self.assertNotIn("attachment:reason", facts)
        html, _, _ = reports.download(store, case_id, session_id, run_id, "html", user, viewer["sheet_id"])
        pdf, _, _ = reports.download(store, case_id, session_id, run_id, "pdf", user, viewer["sheet_id"])
        self.assertIn(original.encode(), html)
        self.assertIn(help_text.encode(), html)
        self.assertNotIn("오늘의 장면들".encode(), html)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10000)
        self.assertEqual(reports.download(store, case_id, session_id, first_id, "pdf", user, viewer["sheet_id"])[0], first_pdf)
        self.assertTrue(reports.view(store, first_id, user, viewer["sheet_id"])["outdated"])
        reused_id, reused = issue(final, run_id)
        self.assertEqual(len(narrative_calls), 2)
        self.assertEqual(reused.profile, publication.profile)

        with tempfile.TemporaryDirectory(prefix="kdog-rp05-backup-") as temporary:
            root = Path(temporary)
            maintenance.backup(store, root/"backup", user.username)
            maintenance.restore(store, root/"backup", root/"restored")
            restored = Store(root/"restored")
            self.assertEqual(reports.download(restored, case_id, session_id, run_id, "pdf", user, viewer["sheet_id"])[0], pdf)
            self.assertEqual(reports.download(restored, case_id, session_id, reused_id, "manifest", user, viewer["sheet_id"])[0], reused.model_dump_json().encode())
            with restored.connect(write=True) as db:
                db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (case_id,))
            with self.assertRaises(HTTPException):
                reports.download(restored, case_id, session_id, run_id, "pdf", user, viewer["sheet_id"])
            maintenance.clean(restored, purge_deleted=True)
            for ref in (publication.content.ref, publication.output.html.ref, publication.output.pdf.ref):
                self.assertFalse(restored.path(ref).exists())
