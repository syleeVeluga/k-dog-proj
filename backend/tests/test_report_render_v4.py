"""Rendering retains pinned values, safe text, source images and missing data."""
import base64
import hashlib
import re
import unittest

from app.domain.report_profile_v4 import ReportProfileV4
from app.domain.report_render_v4 import ReportHeaderV4, SceneImageV4
from app.report_profile_v4 import build
from app.report_render_v4 import assets, comparison_rows, render_html, survey_rows
from app.report_pdf_v4 import render_pdf
from tests.report_fixture_v4 import fixture


class RenderV4Tests(unittest.TestCase):
    def setUp(self):
        final, pointer, batch = fixture({"보23":2}, scene_codes=("보23",))
        self.profile = build(final,pointer,batch=batch)
        self.header = ReportHeaderV4(dog_name="합성 반려견",guardian_name="합성 보호자",observed_date="2026-10-04",generated_at="2026-10-04T00:00:00Z")

    def changed(self, **changes):
        return ReportProfileV4.model_validate_json(self.profile.model_copy(update=changes).model_dump_json())

    def test_offline_html_escapes_names_and_verbatim_opinions(self):
        header = self.header.model_copy(update={"dog_name":"</style><script>alert(1)</script>긴이름"})
        html = render_html(self.profile,header).decode()
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)
        self.assertEqual(len(re.findall(r'<section\b[^>]*\bdata-section=',html)),6)
        self.assertIn('data:font/ttf;base64,',html)
        self.assertNotIn('https://',html)
        self.assertNotIn('sheets/case/',html)
        self.assertIn('직접 확인 과제 없음',html)
        self.assertIn('사진을 확인하지 못했습니다',html)
        self.assertEqual(len(assets()),5)
        self.assertTrue(all(len(digest)==64 for digest in assets().values()))

    def test_original_survey_scales_zero_reverse_and_denominators_are_preserved(self):
        answers={f's{i:02}':3 for i in range(1,29)}
        answers.update(s10=0,s11=0,s12=0,s13=0,s14=0,s26=1,s27=1,s28=1)
        final,pointer,batch = fixture(survey=answers)
        profile = build(final,pointer,batch=batch)
        rows = survey_rows(profile)
        fear = next(row for row in rows if row['title']=='낯선 사람 두려움')
        self.assertEqual((fear['value'],fear['minimum'],fear['maximum']),(0,0,4))
        self.assertIn('0 ÷ 2',fear['detail'])
        reverse = comparison_rows(profile)[25]
        self.assertEqual(reverse[1],'원응답 1 (1~5) / 역채점 5 (1~5)')
        plain = comparison_rows(profile)[0]
        self.assertEqual(plain[1],'3 (1~5)')
        self.assertIn('width:0.000%',render_html(profile,self.header).decode())

    def test_only_exact_selected_scene_source_time_and_photo_bytes_are_accepted(self):
        scene = self.profile.scenes[0]
        evidence = scene.evidence[0]
        data = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOioAAAAASUVORK5CYII=')
        image = SceneImageV4(scene_id=scene.scene_id,video_id=evidence.video_id,video_sha256=evidence.video_sha256,
            camera_id=evidence.camera_id,source_seconds=evidence.start_seconds,image_sha256=hashlib.sha256(data).hexdigest(),mime='image/png',data=data)
        self.assertIn('data:image/png;base64,',render_html(self.profile,self.header,(image,)).decode())
        for changed in ({'source_seconds':evidence.end_seconds+1}, {'video_sha256':'0'*64}, {'image_sha256':'0'*64}, {'scene_id':'other'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                render_html(self.profile,self.header,(image.model_copy(update=changed),))

    def test_blocking_content_is_rejected_but_pending_bank_does_not_block_verified_output(self):
        self.assertTrue(render_pdf(self.profile,self.header).startswith(b'%PDF-'))
        self.assertNotIn('검토용 미리보기',render_html(self.profile,self.header).decode())
        self.assertIn('검토용 미리보기',render_html(self.profile,self.header.model_copy(update={'preview':True})).decode())
        data=self.profile.model_dump(mode='json')
        data.update(status='review_required',validation_issues=[{'code':'wrong_number','target':'summary','reason':'합성 수치 불일치','blocking':True}])
        profile=ReportProfileV4.model_validate_json(__import__('json').dumps(data))
        for renderer in (render_html,render_pdf):
            with self.assertRaises(ValueError):
                renderer(profile,self.header)

    def test_pdf_six_page_baseline_and_long_content_continues_without_clipping(self):
        data=render_pdf(self.profile,self.header)
        # ReportLab writes page dictionaries uncompressed; full text and visual QA is separate.
        self.assertEqual(len(re.findall(br'/Type /Page\b',data)),6)
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertTrue(data.rstrip().endswith(b'%%EOF'))
        last=self.profile.summary[0].model_copy(update={'text':('긴 한국어 근거 설명을 보존합니다. '*400)+'마지막검증표식'})
        profile=self.changed(summary=(last,))
        expanded=render_pdf(profile,self.header)
        self.assertGreater(len(re.findall(br'/Type /Page\b',expanded)),6)
        self.assertIn('마지막검증표식',render_html(profile,self.header).decode())
