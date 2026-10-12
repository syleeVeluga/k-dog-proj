"""Existing S1 Worker/report fixtures with an externally prepared MP4 provenance."""
import hashlib
import unittest
from unittest.mock import patch

from app import judgements_v4, report_runs_v4 as reports, uploads
from app.domain.media_v4 import ExternalProcessingEditV4, ExternalProcessingV4
from app.domain.report_runs_v4 import REPORT_STAGES, ReportConfigV4, ReportStageV4
from app.report_render_v4 import assets
from app.worker import Worker
from tests import test_run_v4 as helpers
from tests.test_final_results_v4 import assemble
from tests.test_opinions_v4 import model


class ExternalMediaAcceptanceV4Tests(unittest.TestCase):
    def test_prepared_provenance_through_existing_ai_basic_final_report_and_later_correction(self):
        fixture = helpers.RunV4Tests()
        self.addCleanup(fixture.doCleanups)
        original_register, original_snapshot = uploads.register_preserved_video, helpers.sample_snapshot

        def register(store, case_id, session_id, video_id, value, actor):
            return original_register(store, case_id, session_id, video_id, value.model_copy(update={
                "source_kind": "external_360_mp4", "camera_id": "EXT360", "source_original_number": None,
                "external_processing": ExternalProcessingV4(projection="flat", timeline="preserved")}), actor)

        def snapshot():
            value = original_snapshot()
            batch = value.batch.model_copy(update={
                "clips": tuple(clip.model_copy(update={"camera_id": "EXT360"}) for clip in value.batch.clips),
                "windows": tuple(window.model_copy(update={"views": tuple(view.model_copy(update={"camera_id": "EXT360"})
                    for view in window.views)}) for window in value.batch.windows)})
            return value.model_copy(update={"batch": batch})

        with patch.object(uploads, "register_preserved_video", side_effect=register), patch.object(helpers, "sample_snapshot", side_effect=snapshot):
            fixture.setUp()
        fixture.test_actual_handler_calculates_and_publishes_full_s1_with_fake_provider()
        with fixture.store.connect() as db:
            basic = db.execute("SELECT * FROM basic_results WHERE case_id=?", (fixture.case_id,)).fetchone()
            fixture.basic_ref = judgements_v4.reference(basic)
            pinned_basic = fixture.store.path(basic["manifest_ref"]).read_bytes()
            video = fixture.store.manifest(fixture.store.case(db, fixture.case_id)).sessions[0].videos[0]
        final = assemble(fixture)
        self.assertEqual(final["document"]["basic_document"]["input_document"]["source"]["session"]["videos"][0]["source_kind"], "external_360_mp4")

        def historical_config(comparison=None, external_comparison=None):
            return ReportConfigV4(stages=tuple(ReportStageV4(stage=name) for name in REPORT_STAGES), template_hashes=assets(),
                content_hashes=reports.profiles.assets()[1], comparison_snapshot=comparison, external_comparison=external_comparison)

        with patch.object(reports, "config", side_effect=historical_config), \
             patch.object(reports, "capture_images", side_effect=lambda store, source, *args:
                 ((), {scene.scene_id: "synthetic fixture: no real image" for scene in source.profile.scenes})), \
             patch.object(reports, "render_report", return_value=(b"<html>synthetic prepared MP4 report</html>", b"%PDF-1.4\nsynthetic\n%%EOF")):
            run = reports.enqueue(fixture.store, fixture.case_id, fixture.session_id, model(reports.ReportStartV4,
                expected_revision=fixture.current()["input_revision"], request_id="prepared-report", final=final["reference"]), fixture.user)
            self.assertTrue(Worker(fixture.store).once())
        self.assertEqual(reports.view(fixture.store, run["run_id"], fixture.user)["status"], "succeeded")
        pdf = reports.download(fixture.store, fixture.case_id, fixture.session_id, run["run_id"], "pdf", fixture.user)[0]
        before = hashlib.sha256(pdf).hexdigest()
        uploads.update_external_processing(fixture.store, fixture.case_id, video.video_id,
            ExternalProcessingEditV4(session_id=fixture.session_id, expected_revision=fixture.current()["input_revision"],
                external_processing=ExternalProcessingV4(projection="equirectangular", timeline="preserved")), "reviewer")
        self.assertEqual(fixture.store.path(basic["manifest_ref"]).read_bytes(), pinned_basic)
        self.assertEqual(hashlib.sha256(reports.download(fixture.store, fixture.case_id, fixture.session_id,
            run["run_id"], "pdf", fixture.user)[0]).hexdigest(), before)
        with fixture.store.connect() as db:
            self.assertEqual(db.execute("SELECT SUM(call_reserved) FROM steps WHERE run_id=?", (run["run_id"],)).fetchone()[0], 0)
