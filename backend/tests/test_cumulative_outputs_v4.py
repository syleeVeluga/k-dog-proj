"""CM03 cumulative snapshots pinned into report outputs; every participant and answer is synthetic."""
import csv
from io import BytesIO, StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import HTTPException

from app import comparison_mapping_v4 as mapping, cumulative_comparisons_v4 as cumulative, exports_v4 as exports
from app import forms_v4 as forms, report_runs_v4 as reports
from app.domain.cumulative_comparisons_v4 import CumulativeMemberV4, MemberMetricV4
from app.domain.report_runs_v4 import ReportPublicationV4
from app.domain.sheets_v4 import InputPointerV4
from app.worker import Worker
from tests import test_external_comparisons_v4 as external_fixture
from tests import test_report_runs_v4 as report_fixture
from tests import test_sheets_v4 as sheet_fixture
from tests.test_forms_import_v4 import csv_bytes
from tests.test_report_narrative_v4 import generated

# Example A/B/C/D from the delivered workbook §14–15 (synthetic; never product values).
A = dict(s10=0, s11=1, s12=1, s13=1, s14=2)
B = dict(s10=0, s11=2, s12=1, s13=2, s14=3)
C = dict(s10=1, s11=2, s12=0, s13=1, s14=1)
D = dict(s10=3, s11=3, s12=3, s13=3, s14=3)


def answers(fear):
    value = {f"s{n:02}": 3 for n in range(1, 29)}
    value.update(fear)
    return value


class CumulativeOutputFixture(unittest.TestCase):
    target = A

    def setUp(self):
        original = sheet_fixture.SheetsV4Tests.setUp
        target = self.target

        def survey_before_scores(helper):
            original(helper)
            with helper.store.connect(write=True) as db:
                case = helper.store.case(db, helper.case_id)
                manifest = helper.store.manifest(case)
                manifest.consents.analysis_feedback = "confirmed"
                manifest.sessions[0].survey.update(answers(target))
                helper.store.save(db, case, manifest, "operator", "synthetic.survey")
        self.fixture = report_fixture.ReportRunV4Tests()
        with patch.object(sheet_fixture.SheetsV4Tests, "setUp", survey_before_scores):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.historical_config.stop()
        self.store, self.user = self.fixture.store, self.fixture.user
        self.reviewer = SimpleNamespace(username="reviewer")
        with self.store.connect(write=True) as db:
            if not db.execute("SELECT 1 FROM users WHERE username='reviewer'").fetchone():
                db.execute("INSERT INTO users(username,password_hash,role) VALUES ('reviewer','unused','reviewer')")
        self.calls = 0

    def others(self, *values, event="CUMULATIVE"):
        keys = ["participant_id", "dog_name", "consent_analysis_feedback"] + [f"s{n:02}" for n in range(1, 29)]
        rows = [[f"{event}-{index}", f"SyntheticDog{index}", "confirmed", *[answers(value).get(key) for key in keys[3:]]] for index, value in enumerate(values)]
        preview = forms.preview(self.store, csv_bytes([keys] + rows), forms.FormsPreviewRequestV4(request_id="p-" + event, event_id=event,
            filename="synthetic.csv", format="csv", mapping=forms.FormsMappingV4(version="synthetic", source_profile="synthetic only",
            survey_version="survey-20260929-v3", columns={key: key for key in keys})), self.user.username)
        self.assertEqual(preview.errors, [])
        result = forms.commit(self.store, forms.FormsCommitRequestV4(request_id="c-" + event, preview_id=preview.preview_id,
            preview_hash=preview.preview_hash), self.user.username)
        return [row.case_id for row in result.rows]

    def pair(self, case_id, request):
        view = cumulative.link(self.store, cumulative.PairLinkV4(request_id="link-" + request, case_id=case_id, expected_revision=0,
            reason="SYNTHETIC pair"), self.user)
        return self.submit(view, case_id, "first", request)

    def submit(self, view, case_id, kind, request):
        with self.store.connect() as db:
            row = self.store.case(db, case_id)
        return cumulative.submit(self.store, view.pair_id, cumulative.SubmissionCreateV4(request_id=kind + "-" + request,
            expected_revision=view.revision, kind=kind, case_id=case_id, session_id=row["selected_session_id"],
            expected_input_revision=row["input_revision"], evidence="SYNTHETIC submission"), self.user)

    def edit(self, case_id, update):
        with self.store.connect(write=True) as db:
            row = self.store.case(db, case_id); manifest = self.store.manifest(row)
            manifest.sessions[0].survey.update(update)
            self.store.save(db, row, manifest, self.user.username, "synthetic.edit")

    def define(self, *sources):
        for source in sources:
            external_fixture.define(self.store, source_id=source)

    def issue(self, request_id=None):
        request = self.fixture.request.model_copy(update={"cumulative": True, **({"request_id": request_id} if request_id else {})})
        job = reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, request, self.user)

        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard(); self.calls += 1
                return generated(context), {}
        self.assertTrue(Worker(self.store, observer=Provider()).once())
        self.assertEqual(self.fixture.row(job["run_id"])["status"], "succeeded")
        raw, _, _ = reports.download(self.store, self.fixture.case_id, self.fixture.session_id, job["run_id"], "manifest", self.user)
        return job["run_id"], ReportPublicationV4.model_validate_json(raw)

    @staticmethod
    def rows(publication):
        return {row.metric_id: row for row in publication.profile.survey_comparison.rows}


class WorkedExampleTests(CumulativeOutputFixture):
    def test_t04_t05_t14_t19_c01_c02_values_pins_exports_and_old_bytes(self):
        self.define(external_fixture.SOURCE, "us2026-nonsocial-fear")
        b, c = self.others(B, C)
        self.pair(self.fixture.case_id, "a"); self.pair(b, "b"); self.pair(c, "c")
        run_id, publication = self.issue()
        rows = self.rows(publication)
        sf, nf = rows["S03"], rows["S04"]
        self.assertEqual((sf.cumulative_display, sf.cumulative_n, sf.individual_display, sf.external_display), ("1.00", 3, "0.50", "0.66"))
        self.assertEqual((nf.cumulative_display, nf.cumulative_n, nf.individual_display, nf.external_display), ("1.33", 3, "1.33", "1.03"))
        self.assertEqual((sf.external_sentence_id, nf.external_sentence_id), ("TXT-L", "TXT-H"))
        self.assertEqual(sf.external_sentence, "낯선 사람 두려움 설문 점수는 0.50점으로, 미국 연구 참고 평균 0.66점보다 낮게 나타났습니다.")
        self.assertEqual(nf.cumulative_comparison, "equal_display", "same displayed value keeps the same position")
        self.assertEqual((nf.cumulative_numerator, nf.cumulative_denominator), (12, 9))
        self.assertEqual({key: row.external_status for key, row in rows.items() if key not in ("S03", "S04")}, {key: "not_mapped" for key in
            ("S01", "S02", "S05", "S06", "S07", "S08", "S09")})
        self.assertEqual((rows["S01"].cumulative_display, rows["S01"].cumulative_n, rows["S01"].external_mean), ("3.00", 3, None))
        self.assertEqual(rows["S08"].question_ids, ("s25",))
        self.assertEqual(publication.profile.presentation_version, "report-presentation-20261021-cm")
        config = json.loads(self.fixture.row(run_id)["config_snapshot_json"])
        self.assertEqual((config["version"], config["cumulative_comparison"]), ("report-run-20261021-cm",
            publication.profile.survey_comparison.reference.model_dump(mode="json")))
        self.assertEqual(config["content_hashes"][mapping.ASSET], mapping.asset_hash())
        before = {kind: reports.download(self.store, self.fixture.case_id, self.fixture.session_id, run_id, kind, self.user)[0] for kind in ("manifest", "html", "pdf")}
        d, = self.others(D, event="LATER")
        self.pair(d, "d")
        _, later = self.issue(request_id="later-request")
        rows = self.rows(later)
        self.assertEqual((rows["S03"].cumulative_display, rows["S03"].cumulative_n, rows["S04"].cumulative_display, rows["S04"].cumulative_n),
                         ("1.50", 4, "1.75", 4))
        for kind, data in before.items():
            self.assertEqual(reports.download(self.store, self.fixture.case_id, self.fixture.session_id, run_id, kind, self.user)[0], data,
                             "an issued report keeps its admission-time cumulative values")
        export = self.export(run_id, publication)
        values = {(row["source"], row["metric_id"]): row for row in export if row.get("metric_id")}
        self.assertEqual(values[("report_cumulative", "S03")]["display"], "1.00")
        self.assertEqual(values[("report_cumulative", "S03")]["n"], "3")
        self.assertEqual(values[("report_external", "S04")]["display"], "1.03")
        self.assertEqual(values[("report_individual", "S04")]["display"], "1.33")
        self.assertEqual(values[("report_cumulative", "S04")]["snapshot_sha256"], publication.profile.survey_comparison.reference.hash)

    def export(self, run_id, publication):
        selection = {"case_id": self.fixture.case_id, "session_id": self.fixture.session_id, "sheet": publication.profile.source.sheet.model_dump(mode="json"),
            "final": publication.final.model_dump(mode="json"), "report_run_id": run_id}
        created = exports.create(self.store, exports.ExportCreateV4.model_validate_json(json.dumps({"request_id": "export-cm", "format": "csv_zip",
            "reason": "SYNTHETIC cumulative export", "members": [selection]})), self.user)
        data, _, _ = exports.download(self.store, created["export_id"], self.user)
        with ZipFile(BytesIO(data)) as archive:
            return list(csv.DictReader(StringIO(archive.read("comparisons.csv").decode("utf-8-sig"))))

    def test_t07_t08_t16_t17_revisit_correction_exclusion_replay_and_pinned_retry(self):
        b, c = self.others(B, C)
        self.pair(self.fixture.case_id, "a"); pb = self.pair(b, "b"); self.pair(c, "c")
        self.edit(b, dict(s10=4, s11=4))
        self.submit(pb, b, "revisit", "b2")
        first = reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, self.fixture.request.model_copy(update={"cumulative": True}), self.user)
        replay = reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, self.fixture.request.model_copy(update={"cumulative": True}), self.user)
        self.assertEqual(first["run_id"], replay["run_id"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action=?", (cumulative.SNAPSHOT_ACTION,)).fetchone()[0], 1)
        snapshot = reports.snapshot_for(self.fixture.row(first["run_id"])).profile.survey_comparison
        self.assertEqual({row.metric_id: (row.cumulative_display, row.cumulative_n) for row in snapshot.rows}["S03"], ("1.00", 3),
                         "a revisit never adds a second contribution")
        pb = cumulative.pair_view(self.store, self.user, pb.pair_id)
        corrected = self.submit(pb, b, "correction", "b3")
        self.assertTrue(Worker(self.store, observer=self.provider()).once())
        self.assertEqual(self.fixture.row(first["run_id"])["status"], "succeeded")
        raw, _, _ = reports.download(self.store, self.fixture.case_id, self.fixture.session_id, first["run_id"], "manifest", self.user)
        pinned = ReportPublicationV4.model_validate_json(raw).profile.survey_comparison
        self.assertEqual(pinned, snapshot, "worker execution after a registry change keeps the admission snapshot")
        _, later = self.issue(request_id="after-correction")
        self.assertEqual({row.metric_id: (row.cumulative_display, row.cumulative_n) for row in later.profile.survey_comparison.rows}["S03"],
                         ("2.00", 3), "a correction replaces the representative for new requests only")
        pc = next(view for view in cumulative.inventory(self.store, self.user).pairs if any(case.case_id == c for case in view.cases))
        cumulative.set_status(self.store, pc.pair_id, cumulative.PairStatusV4(request_id="exclude-c", expected_revision=pc.revision,
            status="excluded", reason="SYNTHETIC"), self.user)
        _, excluded = self.issue(request_id="after-exclusion")
        self.assertEqual({row.metric_id: row.cumulative_n for row in excluded.profile.survey_comparison.rows}["S03"], 2)
        self.assertEqual(excluded.profile.survey_comparison.exclusion_counts, {"excluded": 1})

    def provider(self):
        outer = self

        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard(); outer.calls += 1
                return generated(context), {}
        return Provider()

    def test_t16_registry_change_during_admission_conflicts_without_partial_adoption(self):
        b, = self.others(B)
        self.pair(b, "b")
        original = cumulative.build_snapshot

        def racing(*args, **kwargs):
            result = original(*args, **kwargs)
            self.pair(self.fixture.case_id, "late")
            return result
        with patch.object(cumulative, "build_snapshot", side_effect=racing):
            with self.assertRaises(HTTPException) as caught:
                reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, self.fixture.request.model_copy(update={"cumulative": True}), self.user)
        self.assertEqual(caught.exception.status_code, 409)
        with self.store.connect() as db:
            self.assertFalse(db.execute("SELECT 1 FROM changes WHERE action=?", (cumulative.SNAPSHOT_ACTION,)).fetchone())
            self.assertFalse(db.execute("SELECT 1 FROM runs WHERE kind='report_v4'").fetchone())

    def test_t18_corrupted_snapshot_parent_is_a_technical_error(self):
        self.pair(self.fixture.case_id, "a")
        run_id, publication = self.issue()
        doc = cumulative.snapshot_document(self.store, publication.profile.survey_comparison.reference)
        state = self.store.path(doc.members[0].state.ref)
        state.write_bytes(state.read_bytes() + b" ")
        with self.assertRaises(HTTPException) as caught:
            reports.download(self.store, self.fixture.case_id, self.fixture.session_id, run_id, "html", self.user)
        self.assertEqual(caught.exception.status_code, 409)

    def test_t21_snapshot_parents_survive_clean_after_registry_moves_on(self):
        from app import maintenance
        self.pair(self.fixture.case_id, "a")
        _, publication = self.issue()
        pinned = publication.profile.survey_comparison.reference
        view = next(item for item in cumulative.inventory(self.store, self.user).pairs)
        self.edit(self.fixture.case_id, dict(s10=4))
        cumulative.set_status(self.store, view.pair_id, cumulative.PairStatusV4(request_id="later-exclusion", expected_revision=view.revision,
            status="excluded", reason="SYNTHETIC"), self.user)
        files = cumulative.snapshot_files(self.store, pinned)
        with self.store.connect() as db:
            refs = maintenance.references(self.store, db)
        self.assertTrue(all(item.ref in refs for item in files))
        maintenance.clean(self.store)
        self.assertTrue(all(self.store.path(item.ref).exists() for item in files))
        self.assertEqual(cumulative.snapshot_document(self.store, pinned).members[0].pair_id, view.pair_id)

    def test_issued_report_opens_in_its_own_edition_after_mapping_change(self):
        self.pair(self.fixture.case_id, "a")
        run_id, publication = self.issue()
        before = reports.download(self.store, self.fixture.case_id, self.fixture.session_id, run_id, "html", self.user)[0]
        with patch.object(mapping, "asset_hash", return_value="f" * 64):
            self.assertEqual(reports.download(self.store, self.fixture.case_id, self.fixture.session_id, run_id, "html", self.user)[0], before)
            with self.assertRaises(HTTPException):
                cumulative.snapshot_document(self.store, publication.profile.survey_comparison.reference)

    def test_definition_saved_during_admission_conflicts(self):
        self.pair(self.fixture.case_id, "a")
        original = cumulative.build_snapshot

        def racing(*args, **kwargs):
            result = original(*args, **kwargs)
            self.define(external_fixture.SOURCE)
            return result
        with patch.object(cumulative, "build_snapshot", side_effect=racing):
            with self.assertRaises(HTTPException) as caught:
                reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, self.fixture.request.model_copy(update={"cumulative": True}), self.user)
        self.assertEqual(caught.exception.status_code, 409)
        with self.store.connect() as db:
            self.assertFalse(db.execute("SELECT 1 FROM runs WHERE kind='report_v4'").fetchone())

    def test_t22_default_requests_keep_the_rp04_contract(self):
        job = reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, self.fixture.request, self.user)
        config = json.loads(self.fixture.row(job["run_id"])["config_snapshot_json"])
        self.assertEqual(config["version"], "report-run-20261007-rp04")
        self.assertNotIn("cumulative_comparison", config)
        self.assertNotIn(mapping.ASSET, config["content_hashes"])
        self.assertNotIn("cumulative", json.dumps(self.fixture.request.model_dump(mode="json")))
        with self.assertRaises(HTTPException) as caught:
            reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, self.fixture.request.model_copy(update={
                "cumulative": True, "request_id": "both", "external_comparison": {"snapshot_id": "x", "revision": 1, "ref": "comparisons/x.json", "hash": "0" * 64}}), self.user)
        self.assertEqual(caught.exception.status_code, 422)


class MissingAnswerTests(CumulativeOutputFixture):
    target = dict(A, s11=None)

    def test_t06_t15_missing_sf_shows_notice_and_keeps_other_metrics(self):
        self.define("us2026-nonsocial-fear")
        b, c = self.others(B, C)
        self.pair(self.fixture.case_id, "a"); self.pair(b, "b"); self.pair(c, "c")
        _, publication = self.issue()
        rows = self.rows(publication)
        sf, nf = rows["S03"], rows["S04"]
        self.assertEqual((sf.individual_status, sf.notice_id, sf.cumulative_display, sf.cumulative_n, sf.cumulative_shown),
                         ("insufficient", "TXT-M", "1.25", 2, False))
        self.assertEqual(sf.notice, "낯선 사람 두려움은 응답이 부족하여 이번에는 점수와 연구 평균 비교를 표시하지 않았습니다.")
        self.assertEqual((sf.external_status, sf.external_mean), ("individual_unavailable", None))
        self.assertEqual((nf.individual_display, nf.cumulative_display, nf.cumulative_n, nf.external_status), ("1.33", "1.33", 3, "ready"))
        self.assertEqual(publication.profile.external_comparison.entries[0].gate.source_id, "us2026-nonsocial-fear")


class AggregationUnitTests(unittest.TestCase):
    def members(self, values):
        loaded = mapping.load()
        result = []
        for index, value in enumerate(values):
            metrics = mapping.evaluate(answers(dict(s10=value, s11=value)) if value is not None else answers(dict(s10=None)), loaded)
            pointer = {"ref": "comparisons/x.json", "hash": "0" * 64}
            result.append(CumulativeMemberV4(pair_id=f"p{index:03}", state={**pointer, "pair_id": f"p{index:03}", "revision": 1},
                submission={**pointer, "submission_id": f"s{index}"}, case_id="c", session_id="s", input_revision=1,
                input=InputPointerV4(manifest_ref="inputs/x.json", manifest_hash="0" * 64),
                metrics=tuple(MemberMetricV4(metric_id=key, **metrics[key]) for key in mapping.METRIC_IDS)))
        return result

    def test_t09_weighted_by_actual_valid_pairs(self):
        aggregate = cumulative._aggregate(self.members([1] * 10 + [2] * 90), mapping.load())
        self.assertEqual((aggregate[2].display, aggregate[2].n), ("1.90", 100))
        partial = cumulative._aggregate(self.members([1] * 83 + [None] * 17), mapping.load())
        self.assertEqual((partial[2].n, partial[2].numerator, partial[2].denominator, len(partial[2].response_excluded)), (83, 166, 166, 17))
        self.assertEqual(partial[0].n, 100, "other metrics keep their own n")

    def test_t10_n0_n1_n2_markers(self):
        loaded = mapping.load()
        for count, shown in ((0, False), (1, False), (2, True)):
            members = self.members([2] * count)
            doc = SimpleNamespace(metrics=cumulative._aggregate(members, loaded), exclusions=(), members=members, recorded_at="2026-10-21T00:00:00+00:00",
                                  mapping_version=loaded.version, mapping_hash=mapping.asset_hash())
            survey = SimpleNamespace(survey_version=loaded.survey_version, policy_version=loaded.policy_version,
                items=[SimpleNamespace(item_id=key, raw=value) for key, value in answers(dict(s10=1, s11=1)).items()])
            pointer = {"snapshot_id": "x", "ref": "comparisons/x.json", "hash": "0" * 64}
            rows = {row.metric_id: row for row in cumulative.public_rows(doc, pointer, survey).rows}
            self.assertEqual(rows["S03"].cumulative_shown, shown)
            self.assertEqual(rows["S03"].cumulative_n, count)
            self.assertIsNone(rows["S03"].cumulative_display if count == 0 else None)
            self.assertEqual((rows["S03"].external_status, rows["S01"].external_status), ("not_ready", "not_mapped"))

    def test_reference_date_is_korea_time(self):
        self.assertEqual(cumulative.local_date("2026-10-21T16:30:00+00:00"), "2026-10-22")
        self.assertEqual(cumulative.local_date("2026-10-21T14:59:59+00:00"), "2026-10-21")

    def test_t12_t13_exact_half_up_and_display_comparison(self):
        self.assertEqual(cumulative.display(9, 8), "1.13")
        self.assertEqual(cumulative.display(1, 8), "0.13")
        self.assertEqual(cumulative.display(4, 3), "1.33")
        self.assertEqual(round(1.125, 2), 1.12, "binary float rounding would have shown 1.12")
        self.assertEqual(cumulative.compare(cumulative.display(4, 3), cumulative.display(133, 100)), "equal_display")
        self.assertEqual(cumulative.compare("0.50", "0.66"), "lower")
