"""Conditional synthetic mechanisms only; no professor table approval."""
import unittest
from io import BytesIO
from types import SimpleNamespace

from fastapi import HTTPException
from pypdf import PdfReader

from app import comparisons_v4 as comparisons, report_runs_v4 as reports
from app.domain.report_runs_v4 import ReportPublicationV4
from app.report_render_v4 import render_html
from app.report_pdf_v4 import render_pdf
from app.worker import Worker
from tests import test_external_comparisons_v4 as support
from tests.test_report_narrative_v4 import generated


class ExternalNewReportPreflightTests(unittest.TestCase):
    def setUp(self):
        self.support = support.ExternalReportTests()
        self.support.setUp()
        self.addCleanup(self.support.doCleanups)
        self.fixture = self.support.fixture
        self.fixture.historical_config.stop()
        self.fixture.render.side_effect = lambda profile, header, images: (
            render_html(profile, header, images), render_pdf(profile, header, images))
        self.calls = []

    def withdraw(self):
        comparisons.activate_external(self.support.store, comparisons.ActivateExternalV4(source_id=support.SOURCE,
            expected_revision=1, confirmation=self.support.research, enabled=False, reason="SYNTHETIC WITHDRAWAL"),
            SimpleNamespace(username="admin"))

    def work(self, withdraw=False):
        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard()
                self.assertEqual(files, [])
                self.calls.append(context)
                if withdraw:
                    self.withdraw()
                return generated(context), {}
        self.assertTrue(Worker(self.support.store, observer=Provider()).once())

    def test_current_narrative_and_photo_free_output_keep_exact_conditional_scope(self):
        job = self.fixture.enqueue()
        self.work()
        run_id = job["run_id"]
        raw, _, _ = reports.download(self.support.store, self.fixture.case_id, self.fixture.session_id, run_id, "manifest", self.support.user)
        publication = ReportPublicationV4.model_validate_json(raw)
        self.assertEqual(publication.profile.presentation_version, "report-presentation-20261007-rp04")
        self.assertIsNotNone(publication.profile.narrative)
        self.assertEqual(publication.profile.external_comparison.reference, self.support.external.reference)
        self.assertEqual(publication.profile.external_comparison.target, self.support.external.target)
        entry = publication.profile.external_comparison.entries[0]
        self.assertEqual((entry.local_mean, entry.local_n), (0, 2))
        self.assertEqual(entry.gate.scope.question_ids, ("s10", "s11"))
        self.assertEqual(entry.gate.scope.policy_version, "survey-policy-20261007-rp01")
        self.assertEqual((entry.gate.values.mean, entry.gate.values.valid_n), (0.66, 42926))
        html, _, _ = reports.download(self.support.store, self.fixture.case_id, self.fixture.session_id, run_id, "html", self.support.user)
        pdf, _, _ = reports.download(self.support.store, self.fixture.case_id, self.fixture.session_id, run_id, "pdf", self.support.user)
        for text in ("본인 설문 평균 0", "0.66", "42926", "외부 유효 표본"):
            self.assertIn(text, html.decode())
        self.assertNotIn("오늘의 장면들", html.decode())
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10000)
        pdf_text = "".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        compact = "".join(pdf_text.split())
        for text in ("본인 설문 평균 0", "0.66", "42926", "외부 유효 표본"):
            self.assertIn("".join(text.split()), compact)
        self.assertEqual(len(self.calls), 1)
        self.withdraw()
        for kind in ("manifest", "html", "pdf"):
            with self.assertRaises(HTTPException):
                reports.download(self.support.store, self.fixture.case_id, self.fixture.session_id, run_id, kind, self.support.user)
        self.assertEqual(self.support.store.path(self.fixture.row(run_id)["result_ref"]).read_bytes(), raw)
        self.assertEqual(self.support.store.path(publication.output.html.ref).read_bytes(), html)
        self.assertEqual(self.support.store.path(publication.output.pdf.ref).read_bytes(), pdf)
        self.assertEqual(reports.view(self.support.store, run_id, self.support.user)["external_comparison_status"], "blocked")

    def test_withdrawal_during_narrative_call_cannot_publish_new_comparison(self):
        job = self.fixture.enqueue()
        self.work(withdraw=True)
        self.assertEqual(len(self.calls), 1)
        row = self.fixture.row(job["run_id"])
        self.assertNotEqual(row["status"], "succeeded")
        self.assertIsNone(row["result_ref"])
        with self.assertRaises(HTTPException):
            reports.download(self.support.store, self.fixture.case_id, self.fixture.session_id, job["run_id"], "manifest", self.support.user)
