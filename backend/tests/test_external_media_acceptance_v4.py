"""Existing S1 Worker/report fixtures with an externally prepared MP4 provenance."""
import hashlib
import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import judgements_v4, media, preprocess_executions_v4 as queries, preprocess_v4, report_runs_v4 as reports, run_v4, scoring_ai_v4, settings_v4, uploads
from app.domain.preprocess_v4 import PreprocessRequestV4
from app.domain.media_v4 import ExternalProcessingEditV4, ExternalProcessingV4
from app.domain.report_runs_v4 import REPORT_STAGES, ReportConfigV4, ReportStageV4
from app.domain.runs_v4 import StartV4
from app.report_render_v4 import assets
from app.worker import Worker
from tests import test_run_v4 as helpers
from tests import test_preprocess_v4 as media_helpers
from tests.test_final_results_v4 import assemble
from tests.test_opinions_v4 import model


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Actual synthetic MP4 decode required")
class ExternalMediaAcceptanceV4Tests(unittest.TestCase):
    def test_prepared_provenance_through_existing_ai_basic_final_report_and_later_correction(self):
        prepared = media_helpers.PreprocessV4Tests()
        prepared.samples = {}
        self.addCleanup(prepared.doCleanups)
        prepared.setUp()
        path = prepared.store.root.parent / "prepared.mp4"
        media.command(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "310", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)])
        linked = prepared.upload("prepared", "EXT360", data=path.read_bytes(), source_kind="external_360_mp4",
            external_processing={"projection": "flat", "timeline": "preserved"})
        capture = helpers.sample_snapshot().session.recording_s1
        capture = capture.model_copy(update={"video_id": linked.video_id,
            "segments": tuple(value.model_copy(update={"video_id": linked.video_id}) for value in capture.segments),
            "walk_phases": tuple(value.model_copy(update={"video_id": linked.video_id}) for value in capture.walk_phases),
            "events": tuple(value.model_copy(update={"video_id": linked.video_id}) for value in capture.events),
            "coverage": tuple(value.model_copy(update={"video_id": linked.video_id}) for value in capture.coverage)})
        with prepared.store.connect(write=True) as db:
            row = prepared.store.case(db, prepared.case_id)
            manifest = prepared.store.manifest(row)
            manifest.sessions[0].recording_s1 = capture
            prepared.store.save(db, row, manifest, "op", "synthetic.recording")
        batch = preprocess_v4.execute(prepared.store, prepared.case_id, prepared.session_id, "review",
            PreprocessRequestV4(request_id="prepared-by-review", expected_revision=prepared.current()["input_revision"]))
        self.assertEqual(batch.status, "complete")
        self.assertTrue(batch.clips)
        self.assertTrue(all(clip.camera_id == "EXT360" and clip.ai.frame_times_seconds and clip.ai.audio_ranges for clip in batch.clips))
        fixture = helpers.RunV4Tests()
        fixture.store, fixture.case_id, fixture.session_id = prepared.store, prepared.case_id, prepared.session_id
        fixture.user = SimpleNamespace(username="review", role="reviewer")
        pointer = media_helpers.preprocess.status(prepared.store, prepared.case_id, prepared.session_id, "op").result_pointer
        fixture.request = StartV4(expected_revision=batch.input_revision, request_id="prepared-ai", preprocess_ref=pointer.ref, preprocess_hash=pointer.hash)
        expected = {prepared.store.path(value.ref): value.hash for clip in batch.clips for value in (clip.original, clip.ai)}
        seen, calls, test = set(), [], self
        class FakeProvider:
            def request_v4(self, files, config, context, schema, guard):
                guard(); calls.append(context)
                for path, _ in files:
                    test.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected[path])
                    seen.add(path)
                return {**context["identity"], "observations": [{"code": item["code"], "value": None,
                    "status": "unobserved", "reason": "synthetic fixture: no actual observation"} for item in context["items"]]}, {"cost_usd": None}
        pipeline = settings_v4.defaults(); pipeline.raw_observation_scope_confirmed = True
        run = fixture.enqueue(config=scoring_ai_v4.configuration(None, pipeline))
        self.assertTrue(Worker(fixture.store, observer=FakeProvider()).once())
        shown = run_v4.view(fixture.store, run["run_id"], fixture.user)
        self.assertEqual(shown["status"], "succeeded")
        self.assertTrue(shown["result_available"])
        self.assertEqual(shown["reserved_calls"], len(calls))
        self.assertTrue(seen)
        with fixture.store.connect() as db:
            basic = db.execute("SELECT * FROM basic_results WHERE case_id=?", (fixture.case_id,)).fetchone()
            fixture.basic_ref = judgements_v4.reference(basic)
            pinned_basic = fixture.store.path(basic["manifest_ref"]).read_bytes()
            video = fixture.store.manifest(fixture.store.case(db, fixture.case_id)).sessions[0].videos[0]
        final = assemble(fixture)
        self.assertEqual(len(final["document"]["basic_document"]["input_document"]["sheet"]["observations"]), 86)
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
                external_processing=ExternalProcessingV4(projection="equirectangular", timeline="preserved")), "dev")
        self.assertEqual(fixture.store.path(basic["manifest_ref"]).read_bytes(), pinned_basic)
        self.assertEqual(hashlib.sha256(reports.download(fixture.store, fixture.case_id, fixture.session_id,
            run["run_id"], "pdf", fixture.user)[0]).hexdigest(), before)
        with fixture.store.connect() as db:
            self.assertEqual(db.execute("SELECT SUM(call_reserved) FROM steps WHERE run_id=?", (run["run_id"],)).fetchone()[0], 0)
        old = queries.execution(prepared.store, prepared.case_id, prepared.session_id, batch.batch_id, "dev")
        self.assertEqual(old.requested_by, "review")
        self.assertTrue(old.outdated)
        fresh = preprocess_v4.execute(prepared.store, prepared.case_id, prepared.session_id, "review",
            PreprocessRequestV4(request_id="explicit-after-correction", expected_revision=prepared.current()["input_revision"]))
        self.assertNotEqual(fresh.batch_id, batch.batch_id)
        self.assertEqual(fresh.status, "partial")
        self.assertFalse(fresh.clips)
        self.assertEqual({item.requested_by for item in queries.executions(prepared.store, "review").items}, {"review"})
