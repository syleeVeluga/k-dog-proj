"""CM04 rendered comparison panels in HTML/PDF; every participant and answer is synthetic."""
from io import BytesIO
import re

from pypdf import PdfReader

from app import report_runs_v4 as reports
from app.report_render_v4 import CM_ASSETS, NEW_ASSETS, assets, render_html
from app.report_pdf_v4 import render_pdf
from tests import test_external_comparisons_v4 as external_fixture
from tests.test_cumulative_outputs_v4 import A, B, C, CumulativeOutputFixture


class RenderedComparisonFixture(CumulativeOutputFixture):
    def setUp(self):
        super().setUp()
        self.fixture.render.side_effect = lambda profile, header, images: (render_html(profile, header, images), render_pdf(profile, header, images))

    def files(self, run_id):
        html = reports.download(self.store, self.fixture.case_id, self.fixture.session_id, run_id, "html", self.user)[0].decode()
        pdf = reports.download(self.store, self.fixture.case_id, self.fixture.session_id, run_id, "pdf", self.user)[0]
        text = "".join("".join(page.extract_text().split()) for page in PdfReader(BytesIO(pdf)).pages)
        return html, pdf, text

    @staticmethod
    def panel(html, metric):
        return re.search(rf'<article class="metric" data-metric="{metric}">(.*?)</article>', html, re.S).group(1)


class RenderedComparisonTests(RenderedComparisonFixture):
    def test_t01_t04_t14_t19_nine_panels_three_and_two_points_same_position_and_sources(self):
        self.define(external_fixture.SOURCE, "us2026-nonsocial-fear")
        b, c = self.others(B, C)
        self.pair(self.fixture.case_id, "a"); self.pair(b, "b"); self.pair(c, "c")
        run_id, publication = self.issue()
        html, pdf, text = self.files(run_id)
        self.assertEqual(len(re.findall(r'<article class="metric"', html)), 9)
        sf, nf, s01 = self.panel(html, "S03"), self.panel(html, "S04"), self.panel(html, "S01")
        self.assertEqual(len(re.findall(r'<i class="mark ', sf)), 3)
        self.assertEqual(len(re.findall(r'<i class="mark ', s01)), 2)
        self.assertNotIn("mark us", s01, "metrics without a mapped reference draw no grey marker")
        positions = dict(re.findall(r'<i class="mark (\w+)" style="left:([\d.]+)%"', nf))
        self.assertEqual(positions["cumulative"], positions["individual"], "equal displayed values share one x position on separate lanes")
        self.assertEqual(positions["us"], "25.750")
        self.assertEqual(dict(re.findall(r'<i class="mark (\w+)" style="left:([\d.]+)%"', sf)), {"us": "16.500", "cumulative": "25.000", "individual": "12.500"})
        for value in ("미국 연구 평균 0.66 (유효 n=42,926)", "우리 누적 참여견 평균 1.00 (n=3)", "우리 아이 0.50",
                      "낯선 사람 두려움 설문 점수는 0.50점으로, 미국 연구 참고 평균 0.66점보다 낮게 나타났습니다."):
            self.assertIn(value, sf)
        self.assertIn("소수 둘째 자리 표시 기준에서 우리 누적 참여견 평균(n=3)과 같습니다", nf)
        self.assertIn("Serpell &amp; Powell (2026)", html)
        self.assertIn("10.1016/j.jveb.2025.11.005", html)
        self.assertIn("국내 표준이나 진단 기준은 아닙니다", html)
        self.assertIn(f"집계 기준일 {publication.profile.survey_comparison.as_of}", html)
        self.assertNotIn("백분위", html)
        for value in ("미국연구평균0.66", "우리누적참여견평균1.00(n=3)", "우리아이0.50", "미국연구참고평균0.66점보다낮게", "DOI10.1016/j.jveb.2025.11.005"):
            self.assertIn(value, text)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        for identifier in (publication.profile.survey_comparison.reference.snapshot_id, publication.profile.survey_comparison.reference.hash):
            self.assertNotIn(identifier, html, "internal identifiers stay out of the guardian report")

    def test_t10_t15_single_pair_and_missing_definitions_keep_valid_points(self):
        self.pair(self.fixture.case_id, "a")
        run_id, _ = self.issue()
        html, _, text = self.files(run_id)
        sf = self.panel(html, "S03")
        self.assertEqual(re.findall(r'<i class="mark (\w+)"', sf), ["individual"])
        self.assertIn("현재 n=1", sf)
        self.assertIn("미국 연구 참고 평균은 이번 발급에 연결하지 않았습니다", sf)
        self.assertNotIn("mark us", html)
        self.assertIn("현재n=1", text)

    def test_manual_cohort_with_cumulative_run_keeps_its_checks_and_values(self):
        from app import comparisons_v4 as comparisons
        from app.domain.comparisons_v4 import CohortSelectionV4
        from app.domain.sheets_v4 import InputPointerV4
        b, c = self.others(B, C)
        self.pair(self.fixture.case_id, "a")
        members = []
        for case_id in (b, c):
            with self.store.connect() as db:
                row = self.store.case(db, case_id)
            members.append(CohortSelectionV4(case_id=case_id, session_id=row["selected_session_id"], expected_revision=row["input_revision"],
                input=InputPointerV4(manifest_ref=row["manifest_ref"], manifest_hash=row["manifest_hash"])))
        cohort = comparisons.create(self.store, comparisons.CohortCreateV4(request_id="manual", title="SYNTHETIC manual group",
            reason="SYNTHETIC", members=members), self.user)
        self.fixture.render.side_effect = lambda profile, header, images, **options: (render_html(profile, header, images, **options),
            render_pdf(profile, header, images, **options))
        self.fixture.request = self.fixture.request.model_copy(update={"comparison": cohort.reference})
        run_id, _ = self.issue()
        html, _, text = self.files(run_id)
        self.assertIn("명시 선택 자체 비교 집단(SYNTHETIC manual group) 평균 1.25 (유효 n=2, 제외 0)", self.panel(html, "S03"))
        self.assertIn("우리 누적 참여견 평균은 해당 지표의 유효 참여쌍이 2쌍 이상일 때 표시합니다(현재 n=1)", self.panel(html, "S03"))
        self.assertNotIn('<i class="us">', html, "no US legend entry when no reference is attached")
        self.assertIn("명시선택자체비교집단(SYNTHETICmanualgroup)평균1.25", text)

    def test_t22_rp04_template_bytes_and_hashes_are_preserved(self):
        self.assertNotEqual(set(assets(True)), set(assets(True, cumulative=True)))
        self.assertTrue(set(CM_ASSETS[3:]) == set(NEW_ASSETS[3:]))
        job = reports.enqueue(self.store, self.fixture.case_id, self.fixture.session_id, self.fixture.request, self.user)
        config = reports.ReportConfigV4.model_validate_json(self.fixture.row(job["run_id"])["config_snapshot_json"])
        self.assertEqual(config.template_hashes, assets(True))
        self.assertTrue(all(name in NEW_ASSETS for name in config.template_hashes))


class RenderedMissingTests(RenderedComparisonFixture):
    target = dict(A, s11=None)

    def test_t06_t23_missing_metric_keeps_its_panel_with_a_notice(self):
        b, c = self.others(B, C)
        self.pair(self.fixture.case_id, "a"); self.pair(b, "b"); self.pair(c, "c")
        run_id, _ = self.issue()
        html, _, text = self.files(run_id)
        sf = self.panel(html, "S03")
        self.assertNotIn('<i class="mark', sf, "an insufficient metric draws no marker at zero")
        self.assertIn("응답이 부족하여 이번에는 점수와 연구 평균 비교를 표시하지 않았습니다", sf)
        self.assertEqual(len(re.findall(r'<i class="mark ', self.panel(html, "S04"))), 2)
        self.assertIn("낯선사람두려움은응답이부족하여", text)
