"""CM05 end-to-end synthetic acceptance: two events, pairs, revisit, correction, cutoffs, exports, backup/restore."""
import csv
from io import BytesIO, StringIO
import json
import shutil
from types import SimpleNamespace
from zipfile import ZipFile

from pypdf import PdfReader

from app import cumulative_comparisons_v4 as cumulative, exports_v4 as exports, maintenance, report_runs_v4 as reports
from app.domain.report_runs_v4 import ReportPublicationV4
from app.report_render_v4 import render_html
from app.report_pdf_v4 import render_pdf
from app.storage import Store
from app.worker import Worker
from tests import test_external_comparisons_v4 as external_fixture
from tests.test_cumulative_outputs_v4 import B, C, CumulativeOutputFixture


class CumulativeAcceptanceTests(CumulativeOutputFixture):
    def setUp(self):
        super().setUp()
        self.fixture.render.side_effect = lambda profile, header, images: (render_html(profile, header, images), render_pdf(profile, header, images))

    def download(self, store, run_id, kind, user=None):
        return reports.download(store, self.fixture.case_id, self.fixture.session_id, run_id, kind, user or self.user)[0]

    def metrics(self, publication):
        return {row.metric_id: (row.individual_display, row.cumulative_display, row.cumulative_n, row.external_display)
                for row in publication.profile.survey_comparison.rows}

    def export(self, run_id, publication, request_id):
        selection = {"case_id": self.fixture.case_id, "session_id": self.fixture.session_id, "sheet": publication.profile.source.sheet.model_dump(mode="json"),
            "final": publication.final.model_dump(mode="json"), "report_run_id": run_id}
        created = exports.create(self.store, exports.ExportCreateV4.model_validate_json(json.dumps({"request_id": request_id, "format": "csv_zip",
            "reason": "SYNTHETIC acceptance export", "members": [selection]})), self.user)
        data, _, _ = exports.download(self.store, created["export_id"], self.user)
        with ZipFile(BytesIO(data)) as archive:
            return {(row["source"], row["metric_id"]): row for row in csv.DictReader(StringIO(archive.read("comparisons.csv").decode("utf-8-sig"))) if row.get("metric_id")}

    def test_end_to_end_two_events_revisit_correction_cutoffs_exports_and_restore(self):
        # Legacy rp04 issue before the new mode: its bytes and default contract must survive.
        legacy = self.fixture.request.model_copy(update={"request_id": "legacy-rp04"})
        job = reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, legacy, self.user)
        self.assertTrue(Worker(self.store, observer=self.provider()).once())
        legacy_html = self.download(self.store, job["run_id"], "html")

        # Two events, distinct guardian–dog pairs, SF/NF definitions saved by a common business account.
        self.define(external_fixture.SOURCE, "us2026-nonsocial-fear")
        b, = self.others(B, event="EVENT-ONE")
        c, = self.others(C, event="EVENT-TWO")
        self.pair(self.fixture.case_id, "a"); pb = self.pair(b, "b"); self.pair(c, "c")
        first_id, first = self.issue(request_id="cutoff-1")
        expected = {"S03": ("0.50", "1.00", 3, "0.66"), "S04": ("1.33", "1.33", 3, "1.03")}
        self.assertEqual({key: self.metrics(first)[key] for key in expected}, expected)
        self.assertEqual(self.metrics(first)["S01"], ("3.00", "3.00", 3, None))

        # A revisit with very different answers never changes n or the mean.
        self.edit(b, dict(s10=4, s11=4, s12=4, s13=4, s14=4))
        pb = self.submit(cumulative.pair_view(self.store, self.user, pb.pair_id), b, "revisit", "b-revisit")
        _, revisit = self.issue(request_id="cutoff-revisit")
        self.assertEqual({key: self.metrics(revisit)[key] for key in expected}, expected)

        # A correction by another active business account replaces the representative for new requests only.
        reviewer = SimpleNamespace(username="reviewer")
        with self.store.connect() as db:
            row = self.store.case(db, b)
        cumulative.submit(self.store, pb.pair_id, cumulative.SubmissionCreateV4(request_id="b-correction", expected_revision=pb.revision,
            kind="correction", case_id=b, session_id=row["selected_session_id"], expected_input_revision=row["input_revision"],
            evidence="SYNTHETIC guardian correction"), reviewer)
        second_id, second = self.issue(request_id="cutoff-2")
        self.assertEqual(self.metrics(second)["S03"], ("0.50", "2.00", 3, "0.66"))
        self.assertEqual(self.metrics(second)["S04"], ("1.33", "2.00", 3, "1.03"))

        # Earlier issued bytes keep their admission-time values.
        first_files = {kind: self.download(self.store, first_id, kind) for kind in ("manifest", "html", "pdf")}
        self.assertIn("우리 누적 참여견 평균 1.00 (n=3)", first_files["html"].decode())
        self.assertIn("우리 누적 참여견 평균 2.00 (n=3)", self.download(self.store, second_id, "html").decode())
        text = "".join("".join(page.extract_text().split()) for page in PdfReader(BytesIO(first_files["pdf"])).pages)
        self.assertIn("우리누적참여견평균1.00(n=3)", text)

        # Separate exports keep each report's own cutoff, values and snapshot hash.
        one, two = self.export(first_id, first, "export-cutoff-1"), self.export(second_id, second, "export-cutoff-2")
        self.assertEqual((one[("report_cumulative", "S03")]["display"], two[("report_cumulative", "S03")]["display"]), ("1.00", "2.00"))
        self.assertNotEqual(one[("report_cumulative", "S03")]["snapshot_sha256"], two[("report_cumulative", "S03")]["snapshot_sha256"])
        self.assertEqual(one[("report_external", "S04")]["n"], "42764")

        # Backup → isolated restore → download → clean; the legacy rp04 output is untouched throughout.
        backup = self.store.root.parent / (self.store.root.name + "-acceptance-backup")
        restored = self.store.root.parent / (self.store.root.name + "-acceptance-restored")
        self.addCleanup(shutil.rmtree, backup, True)
        self.addCleanup(shutil.rmtree, restored, True)
        maintenance.backup(self.store, backup, "admin")
        maintenance.restore(self.store, backup, restored)
        target = Store(restored)
        with target.connect(write=True) as db:
            db.execute("UPDATE users SET active=1")
        for kind, data in first_files.items():
            self.assertEqual(self.download(target, first_id, kind), data)
        maintenance.clean(self.store)
        for kind, data in first_files.items():
            self.assertEqual(self.download(self.store, first_id, kind), data)
        self.assertEqual(self.download(self.store, job["run_id"], "html"), legacy_html)
        legacy_config = json.loads(self.fixture.row(job["run_id"])["config_snapshot_json"])
        self.assertEqual(legacy_config["version"], "report-run-20261007-rp04")
        publication = ReportPublicationV4.model_validate_json(self.download(self.store, job["run_id"], "manifest"))
        self.assertIsNone(publication.profile.survey_comparison)

    def provider(self):
        outer = self
        from tests.test_report_narrative_v4 import generated

        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard(); outer.calls += 1
                return generated(context), {}
        return Provider()

    def test_failed_run_retry_keeps_snapshot_queued_legacy_run_and_damaged_snapshot_blocks_clean(self):
        from fastapi import HTTPException
        # An rp04 run queued before any cumulative record exists is executed only after them.
        queued = reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id,
            self.fixture.request.model_copy(update={"request_id": "queued-rp04"}), self.user)
        b, = self.others(B, event="RETRY")
        self.pair(self.fixture.case_id, "a"); pb = self.pair(b, "b")
        self.assertTrue(Worker(self.store, observer=self.provider()).once())
        self.assertEqual(self.fixture.row(queued["run_id"])["status"], "succeeded")
        legacy = ReportPublicationV4.model_validate_json(self.download(self.store, queued["run_id"], "manifest"))
        self.assertIsNone(legacy.profile.survey_comparison)
        # A cumulative run fails once, the registry changes, and an explicit retry reuses the admission snapshot.
        job = reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id,
            self.fixture.request.model_copy(update={"request_id": "retry-cumulative", "cumulative": True}), self.user)
        pinned = reports.snapshot_for(self.fixture.row(job["run_id"])).profile.survey_comparison
        real = self.fixture.render.side_effect
        self.fixture.render.side_effect = ValueError("synthetic renderer failure")
        self.assertTrue(Worker(self.store, observer=self.provider()).once())
        self.assertEqual(self.fixture.row(job["run_id"])["status"], "failed")
        self.fixture.render.side_effect = real
        with self.store.connect() as db:
            row = self.store.case(db, b)
        cumulative.submit(self.store, pb.pair_id, cumulative.SubmissionCreateV4(request_id="b-fix", expected_revision=pb.revision, kind="correction",
            case_id=b, session_id=row["selected_session_id"], expected_input_revision=row["input_revision"], evidence="SYNTHETIC"), self.user)
        reports.action(self.store, job["run_id"], reports.ReportActionV4(expected_updated_at=self.fixture.row(job["run_id"])["updated_at"],
            reason="SYNTHETIC retry"), self.user, retry=True)
        self.assertTrue(Worker(self.store, observer=self.provider()).once())
        self.assertEqual(self.fixture.row(job["run_id"])["status"], "succeeded")
        issued = ReportPublicationV4.model_validate_json(self.download(self.store, job["run_id"], "manifest"))
        self.assertEqual(issued.profile.survey_comparison, pinned, "a retry never re-aggregates the registry")
        # The same raw data cannot be selected twice in one export.
        selection = {"case_id": self.fixture.case_id, "session_id": self.fixture.session_id, "sheet": issued.profile.source.sheet.model_dump(mode="json"),
            "final": issued.final.model_dump(mode="json"), "report_run_id": job["run_id"]}
        with self.assertRaises(HTTPException) as caught:
            exports.create(self.store, exports.ExportCreateV4.model_validate_json(json.dumps({"request_id": "duplicate-raw", "format": "csv_zip",
                "reason": "SYNTHETIC", "members": [selection, {**selection, "report_run_id": queued["run_id"]}]})), self.user)
        self.assertEqual(caught.exception.status_code, 422)
        # A damaged issued snapshot is a technical error and stops clean before anything is removed.
        snapshot = self.store.path(pinned.reference.ref)
        snapshot.write_bytes(snapshot.read_bytes() + b" ")
        with self.assertRaises(HTTPException):
            maintenance.clean(self.store)
        with self.assertRaises(HTTPException):
            self.download(self.store, job["run_id"], "html")
