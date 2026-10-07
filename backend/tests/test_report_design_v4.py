"""New output keeps content while eliminating photo presentation and extraction."""
import unittest
from unittest.mock import patch

from app import report_profile_v4 as profiles, report_runs_v4 as runs
from app.domain.report_profile_v4 import ClaimV4, ReportProfileV4
from app.domain.report_render_v4 import ReportHeaderV4
from app.report_render_v4 import assets, render_html
from app.report_pdf_v4 import render_pdf
from tests.report_fixture_v4 import fixture
from tests import test_report_narrative_v4 as narrative_tests

VERSION = "report-presentation-20261007-rp04"


class DesignContractTests(unittest.TestCase):
    def test_no_photo_selection_preserves_observations_facts_and_timelines(self):
        final, ref, batch = fixture({"보23": 2}, scene_codes=("보23",), survey={"s10": 0})
        old = profiles.build(final, ref, batch=batch)
        with patch.object(profiles.scenes, "select", side_effect=AssertionError("photo selection")):
            new = profiles.build(final, ref, batch=batch, presentation_version=VERSION)
            profiles.validate_profile(new, final, ref, batch=batch)
        self.assertTrue(old.scenes)
        self.assertEqual((new.scenes, new.scene_review, new.scene_notice), ((), (), None))
        self.assertEqual((new.facts, new.cards, new.timeline, new.source, new.comparisons), (old.facts, old.cards, old.timeline, old.source, old.comparisons))

    def test_missing_long_and_action_counts_keep_all_content_and_escape_html(self):
        final, ref, batch = fixture(survey={"s10": 0})
        profile = profiles.build(final, ref, batch=batch, presentation_version=VERSION)
        header = ReportHeaderV4(dog_name="<script>합성</script>",guardian_name="합성 보호자",observed_date="2026-10-08",generated_at="2026-10-07T15:00:00Z")
        long_claim = ClaimV4(claim_id="synthetic:summary",text="긴 한국어 설명을 누락 없이 이어서 읽습니다. "*200+"마지막검증표식",fact_ids=("policy:scope",))
        action = long_claim.model_copy(update={"text": "합성 실천을 확인합니다."})
        for count in range(4):
            changed = ReportProfileV4.model_validate_json(profile.model_copy(update={"summary": (long_claim,), "actions": tuple(action.model_copy(update={"claim_id": "synthetic:"+str(i)}) for i in range(count))}).model_dump_json())
            text = render_html(changed, header).decode()
            self.assertIn("마지막검증표식", text)
            self.assertIn("&lt;script&gt;", text)
            self.assertNotIn("<script>", text)
            self.assertEqual(text.count('class="tip"'), count)
            for old in ("오늘의 장면들", "photo-missing", "선택한 관찰 장면", " / 06", "기본 여섯"):
                self.assertNotIn(old, text)
            pdf = render_pdf(changed, header)
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertGreater(len(pdf), 10000)


class DesignRunTests(unittest.TestCase):
    def test_rp03_issue_keeps_its_profile_and_bytes_after_new_design(self):
        helper = narrative_tests.NarrativeRunTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        current = runs.config
        def previous(*args):
            return current(*args).model_copy(update={"version":"report-run-20261007-rp03","template_hashes":assets()})
        with patch.object(runs,"config",side_effect=previous):
            old_id = helper.issue()
            original = runs.download(helper.store,helper.helper.case_id,helper.helper.session_id,old_id,"pdf",helper.helper.user)[0]
        publication = helper.manifest(old_id)
        self.assertIsNone(publication.profile.presentation_version)
        self.assertEqual(runs.download(helper.store,helper.helper.case_id,helper.helper.session_id,old_id,"pdf",helper.helper.user)[0],original)
        row = helper.helper.row(old_id)
        snapshot = runs.snapshot_for(row)
        # Isolate presentation change from this fixture's later consent revision.
        source = snapshot.final_document.basic_document.input_document.source.model_copy(update={"input_revision":snapshot.input_revision})
        input_document = snapshot.final_document.basic_document.input_document.model_copy(update={"source":source})
        basic = snapshot.final_document.basic_document.model_copy(update={"input_document":input_document})
        aligned = snapshot.model_copy(update={"final_document":snapshot.final_document.model_copy(update={"basic_document":basic})})
        with helper.store.connect() as db:
            case = helper.helper.current()
            with patch.object(runs,"config",side_effect=previous):
                self.assertFalse(runs._outdated(helper.store,db,row,aligned,case))
            self.assertTrue(runs._outdated(helper.store,db,row,aligned,case))
        request = helper.helper.request.model_copy(update={"request_id":"rp04-cannot-reuse-rp03","reuse_run_id":old_id})
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            helper.helper.enqueue(request)

    def test_new_run_does_not_extract_frames_and_issues_without_images(self):
        helper = narrative_tests.NarrativeRunTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        with patch.object(runs, "capture_images", side_effect=AssertionError("frame extraction")):
            run_id = helper.issue()
        publication = helper.manifest(run_id)
        self.assertEqual(publication.profile.presentation_version, VERSION)
        self.assertEqual(publication.output.images, ())
        self.assertEqual(publication.output.image_issues, {})
        self.assertEqual(len(helper.calls), 1)
