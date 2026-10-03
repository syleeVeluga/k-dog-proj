"""Program-only report lifecycle with synthetic inputs and no provider requests."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import analysis, maintenance, media, report_runs_v4 as reports, uploads
from app.domain.media_v4 import UploadCreateV4
from app.domain.report_runs_v4 import ReportPublicationV4, ReportPreparedV4
from app.storage import Store, encode, now, uid
from app.worker import Worker
from tests.test_opinions_v4 import setup_case, model, save_opinion
from tests.test_final_results_v4 import assemble


class ReportRunV4Tests(unittest.TestCase):
    def setUp(self):
        setup_case(self)
        with self.store.connect(write=True) as db:
            case = self.store.case(db, self.case_id)
            manifest = self.store.manifest(case)
            manifest.consents.analysis_feedback = "confirmed"
            self.store.save(db, case, manifest, self.user.username, "synthetic.report.consent")
            # The scoring fixture creates immutable synthetic media directly. Add its
            # matching receipt so report download exercises the real live lineage guard.
            for video in manifest.sessions[0].videos:
                request = UploadCreateV4(request_id=uid(), filename=video.original_name, expected_size=video.size_bytes,
                    expected_sha256=video.sha256, case_id=self.case_id, session_id=self.session_id, source_kind="original")
                db.execute("INSERT INTO upload_receipts(upload_id,creator,request_id,request_hash,request_json,state,"
                    "scope_case_id,scope_session_id,storage_ref,sha256,size_bytes,linked_case_id,linked_session_id,video_id,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'linked',?,?,?,?,?,?,?,?,?,?)",
                    (video.upload_id, self.user.username, request.request_id, analysis.digest(request.model_dump(mode="json")), request.model_dump_json(),
                        self.case_id, self.session_id, video.storage_ref, video.sha256, video.size_bytes, self.case_id, self.session_id, video.video_id, now(), now()))
        self.final = assemble(self)
        self.request = model(reports.ReportStartV4, expected_revision=self.current()["input_revision"],
            request_id=uid(), final=self.final["reference"])
        self.capture = self.enterContext(patch.object(reports, "capture_images", side_effect=lambda store, snapshot, *args:
            ((), {scene.scene_id: "synthetic fixture has no actual image" for scene in snapshot.profile.scenes})))
        self.render = self.enterContext(patch.object(reports, "render_report", side_effect=lambda profile, header, images:
            (f"<html><body>{header.dog_name} / {header.guardian_name}</body></html>".encode(), b"%PDF-1.4\nsynthetic PDF\n%%EOF")))

    def current(self):
        with self.store.connect() as db:
            return dict(self.store.case(db, self.case_id))

    def enqueue(self, request=None):
        return reports.enqueue(self.store, self.case_id, self.session_id, request or self.request, self.user)

    def row(self, run_id):
        with self.store.connect() as db:
            return dict(reports.row_for(self.store, db, run_id))

    def action(self, run_id, *, retry=False):
        return reports.action(self.store, run_id, reports.ReportActionV4(
            expected_updated_at=self.row(run_id)["updated_at"], reason="synthetic explicit action"), self.user, retry=retry)

    def work(self):
        self.assertTrue(Worker(self.store).once())

    def publish(self):
        created = self.enqueue()
        self.work()
        self.assertEqual(self.row(created["run_id"])["status"], "succeeded")
        return created["run_id"]

    def test_idempotent_admission_pins_names_final_versions_and_no_get_side_effect(self):
        first = self.enqueue()
        self.assertFalse(first["normal_publish_available"])
        self.assertEqual(self.enqueue()["run_id"], first["run_id"])
        changed = self.request.model_copy(update={"expected_revision": self.request.expected_revision + 1})
        with self.assertRaises(HTTPException):
            self.enqueue(changed)
        snapshot = reports.snapshot_for(self.row(first["run_id"]))
        self.assertEqual(snapshot.header.dog_name, self.current()["dog_name"])
        self.assertEqual(snapshot.final.final_id, self.final["reference"]["final_id"])
        self.assertFalse(snapshot.header.preview)
        self.assertEqual(len(reports.list_runs(self.store, self.case_id, self.session_id, self.user)), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps").fetchone()[0], 0)

    def test_real_worker_atomic_issued_files_and_no_provider_calls(self):
        run_id = self.publish()
        shown = reports.ReportRunViewV4.model_validate_json(encode(reports.view(self.store, run_id, self.user)))
        self.assertEqual(len(shown.steps), 5)
        self.assertEqual(shown.publication_state, "issued")
        self.assertTrue(shown.normal_publish_available)
        self.assertEqual(shown.pending_reasons, ["G02"])
        for kind in ("html", "pdf", "manifest"):
            content, mime, filename = reports.download(self.store, self.case_id, self.session_id, run_id, kind, self.user)
            self.assertTrue(content)
            self.assertTrue(mime)
            self.assertIn(run_id, filename)
        raw, _, _ = reports.download(self.store, self.case_id, self.session_id, run_id, "manifest", self.user)
        doc = ReportPublicationV4.model_validate_json(raw)
        self.assertEqual(doc.profile.source.final, self.request.final)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT SUM(call_reserved) FROM steps WHERE run_id=?", (run_id,)).fetchone()[0], 0)
            self.assertIsNone(self.store.case(db, self.case_id)["display_run_id"])

    def test_stopped_run_cannot_adopt_late_outputs_and_explicit_retry_uses_fixed_input(self):
        created = self.enqueue(); run_id = created["run_id"]
        real_render = self.render.side_effect
        def stopped(*args):
            self.action(run_id)
            return real_render(*args)
        self.render.side_effect = stopped
        self.work()
        self.assertEqual(self.row(run_id)["status"], "stopped")
        self.assertIsNone(self.row(run_id)["result_ref"])
        self.render.side_effect = real_render
        before = self.row(run_id)["input_snapshot_json"]
        self.action(run_id, retry=True)
        self.work()
        self.assertEqual(self.row(run_id)["status"], "succeeded")
        self.assertEqual(self.row(run_id)["input_snapshot_json"], before)

    def test_three_render_attempts_and_no_partial_publication(self):
        created = self.enqueue(); run_id = created["run_id"]
        self.render.side_effect = ValueError("synthetic renderer failure")
        for attempt in range(3):
            self.work()
            self.assertEqual(self.row(run_id)["status"], "failed")
            self.assertFalse(reports.view(self.store, run_id, self.user)["normal_publish_available"])
            self.assertIsNone(self.row(run_id)["result_ref"])
            self.action(run_id, retry=True)
        self.work()
        self.assertEqual(self.render.call_count, 3)
        self.assertIsNone(self.row(run_id)["result_ref"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps WHERE stage='render_v4'").fetchone()[0], 3)

    def test_lost_adoption_response_recovers_exact_files_without_rendering_twice(self):
        created = self.enqueue(); run_id = created["run_id"]
        adopt = analysis.adopt
        def interrupted(store, row, step, *args):
            if step["stage"] == "render_v4":
                raise OSError("synthetic interruption after immutable output")
            return adopt(store, row, step, *args)
        with patch("app.worker.adopt", side_effect=interrupted):
            self.work()
        self.assertEqual(self.row(run_id)["status"], "failed")
        self.action(run_id, retry=True)
        self.work()
        self.assertEqual(self.row(run_id)["status"], "succeeded")
        self.assertEqual(self.render.call_count, 1)

    def test_mutated_output_between_validation_and_adoption_is_rejected(self):
        created = self.enqueue(); run_id = created["run_id"]
        write = analysis.write_output
        def tamper(store, row, step, payload):
            result = write(store, row, step, payload)
            if step["stage"] == "render_v4":
                store.path(payload["rendered"]["pdf"]["ref"]).write_bytes(b"%PDF-1.4\nchanged\n%%EOF")
            return result
        with patch("app.worker.write_output", side_effect=tamper):
            self.work()
        self.assertEqual(self.row(run_id)["status"], "failed")
        self.assertIsNone(self.row(run_id)["result_ref"])

    def test_explicit_content_reuse_requires_exact_source_and_keeps_new_html_pdf(self):
        first = self.publish()
        request = self.request.model_copy(update={"request_id": uid(), "reuse_run_id": first})
        second = self.enqueue(request)["run_id"]
        self.work()
        self.assertEqual(self.row(second)["status"], "succeeded")
        self.assertEqual(self.capture.call_count, 1)
        self.assertEqual(self.render.call_count, 2)
        self.assertTrue(reports.view(self.store, second, self.user)["steps"][0]["reused"])
        self.assertNotEqual(self.row(first)["result_ref"], self.row(second)["result_ref"])
        with self.store.connect(write=True) as db:
            case = self.store.case(db, self.case_id); manifest = self.store.manifest(case)
            manifest.participant_id = "synthetic-revised"
            self.store.save(db, case, manifest, self.user.username, "synthetic.change")
        changed = request.model_copy(update={"request_id": uid(), "expected_revision": self.current()["input_revision"]})
        with self.assertRaises(HTTPException):
            self.enqueue(changed)

    def test_late_opinion_or_input_change_stops_claim_but_preserves_historical_issued_report(self):
        first = self.publish()
        before, _, _ = reports.download(self.store, self.case_id, self.session_id, first, "html", self.user)
        pending = self.enqueue(self.request.model_copy(update={"request_id": uid()}))["run_id"]
        save_opinion(self)
        self.assertFalse(Worker(self.store).once())
        self.assertEqual(self.row(pending)["status"], "stopped")
        self.assertTrue(reports.view(self.store, first, self.user)["outdated"])
        after, _, _ = reports.download(self.store, self.case_id, self.session_id, first, "html", self.user)
        self.assertEqual(before, after)

    def test_download_checks_wrong_case_all_files_consent_and_late_deletion(self):
        run_id = self.publish()
        with self.assertRaises(HTTPException):
            reports.download(self.store, "not-this-case", self.session_id, run_id, "pdf", self.user)
        row = self.row(run_id)
        doc = ReportPublicationV4.model_validate_json(self.store.path(row["result_ref"]).read_bytes())
        raw = self.store.path(doc.output.pdf.ref).read_bytes()
        self.store.path(doc.output.pdf.ref).write_bytes(raw + b"mutation")
        with self.assertRaises(HTTPException):
            reports.download(self.store, self.case_id, self.session_id, run_id, "html", self.user)
        self.store.path(doc.output.pdf.ref).write_bytes(raw)
        read = reports._read_file
        def deleted(store, pointer, stamps=None):
            data = read(store, pointer, stamps)
            if pointer.ref == doc.output.html.ref:
                with store.connect(write=True) as db:
                    db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
            return data
        with patch.object(reports, "_read_file", side_effect=deleted), self.assertRaises(HTTPException):
            reports.download(self.store, self.case_id, self.session_id, run_id, "html", self.user)

    def test_consent_revocation_and_actor_role_change_block_queue_and_existing_download(self):
        run_id = self.publish()
        with self.store.connect(write=True) as db:
            case = self.store.case(db, self.case_id); manifest = self.store.manifest(case)
            manifest.consents.analysis_feedback = "declined"
            self.store.save(db, case, manifest, self.user.username, "synthetic.withdrawal")
        with self.assertRaises(HTTPException):
            reports.download(self.store, self.case_id, self.session_id, run_id, "html", self.user)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET role='reviewer' WHERE username=?", (self.user.username,))
        with self.assertRaises(HTTPException):
            reports.view(self.store, run_id, self.user)

    def test_backup_restore_and_deleted_case_cleanup_preserve_or_purge_full_report(self):
        run_id = self.publish()
        root = Path(self.helper.temp.name)
        maintenance.backup(self.store, root/"backup", "operator")
        maintenance.restore(self.store, root/"backup", root/"restored")
        restored = Store(root/"restored")
        output, _, _ = reports.download(restored, self.case_id, self.session_id, run_id, "pdf", self.user)
        self.assertTrue(output.startswith(b"%PDF-"))
        with restored.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
        maintenance.clean(restored, purge_deleted=True)
        self.assertFalse(any((root/"restored"/"runs"/run_id).rglob("*.*")))

    def test_simultaneous_identical_request_creates_one_run(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: self.enqueue(), (1, 2)))
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(len(reports.list_runs(self.store, self.case_id, self.session_id, self.user)), 1)

    def test_input_changed_after_expensive_hash_prevents_admission(self):
        verify = reports.verify_files
        def changed(store, snapshot):
            stamps = verify(store, snapshot)
            with store.connect(write=True) as db:
                case = store.case(db, self.case_id); manifest = store.manifest(case)
                manifest.sessions[0].note = "synthetic revised input"
                store.save(db, case, manifest, self.user.username, "synthetic.concurrent")
            return stamps
        with patch.object(reports, "verify_files", side_effect=changed), self.assertRaises(HTTPException):
            self.enqueue()
        self.assertEqual(reports.list_runs(self.store, self.case_id, self.session_id, self.user), [])

    def test_template_identity_change_between_hash_and_admission_rolls_back(self):
        check = reports.check_asset_stamps
        seen = []
        def changed(stamps):
            seen.append(True)
            if len(seen) == 2:
                raise HTTPException(409, "synthetic asset replaced after hashing")
            return check(stamps)
        with patch.object(reports, "check_asset_stamps", side_effect=changed), self.assertRaises(HTTPException):
            self.enqueue()
        self.assertEqual(reports.list_runs(self.store, self.case_id, self.session_id, self.user), [])

    def test_blocking_content_stays_review_required_without_rendering(self):
        from app.domain.report_profile_v4 import ValidationIssueV4
        make = reports.profiles.from_final
        def blocked(*args):
            profile = make(*args)
            return profile.model_copy(update={"status": "review_required", "validation_issues": (
                ValidationIssueV4(code="synthetic_conflict", target="summary", reason="synthetic contradictory source", blocking=True),)})
        with patch.object(reports.profiles, "from_final", side_effect=blocked):
            created = self.enqueue()
        self.work()
        self.assertEqual(self.row(created["run_id"])["status"], "review_required")
        self.assertFalse(reports.view(self.store, created["run_id"], self.user)["normal_publish_available"])
        self.assertIsNone(self.row(created["run_id"])["result_ref"])
        self.render.assert_not_called()

    def test_actual_renderer_integration_uses_pinned_header_and_valid_pdf(self):
        from app.report_render_v4 import render_html
        from app.report_pdf_v4 import render_pdf
        self.render.side_effect = lambda profile, header, images: (render_html(profile, header, images), render_pdf(profile, header, images))
        run_id = self.publish()
        html, _, _ = reports.download(self.store, self.case_id, self.session_id, run_id, "html", self.user)
        pdf, _, _ = reports.download(self.store, self.case_id, self.session_id, run_id, "pdf", self.user)
        self.assertIn(self.current()["dog_name"].encode(), html)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10000)

    def test_receipt_cancellation_and_template_change_do_not_rewrite_issued_output(self):
        run_id = self.publish()
        before = self.store.path(self.row(run_id)["result_ref"]).read_bytes()
        with patch.object(reports, "verify_assets", side_effect=HTTPException(409, "synthetic new template")):
            self.assertTrue(reports.view(self.store, run_id, self.user)["outdated"])
            reports.download(self.store, self.case_id, self.session_id, run_id, "pdf", self.user)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE upload_receipts SET state='failed',failure_code='cancelled'")
        with self.assertRaises(HTTPException):
            reports.download(self.store, self.case_id, self.session_id, run_id, "pdf", self.user)
        self.assertEqual(self.store.path(self.row(run_id)["result_ref"]).read_bytes(), before)

    def test_explicit_cohort_is_pinned_and_renderer_receives_only_public_aggregate(self):
        from app import comparisons_v4 as comparisons
        from app.domain.comparisons_v4 import CohortSelectionV4
        from app.domain.sheets_v4 import InputPointerV4
        row = self.current()
        cohort = comparisons.create(self.store, comparisons.CohortCreateV4(request_id="synthetic-cohort",
            title="Synthetic selected group", reason="synthetic explicit source", members=[CohortSelectionV4(
                case_id=self.case_id, session_id=self.session_id, expected_revision=row["input_revision"],
                input=InputPointerV4(manifest_ref=row["manifest_ref"], manifest_hash=row["manifest_hash"]))]), self.user)
        self.request = self.request.model_copy(update={"comparison": cohort.reference})
        from app.report_render_v4 import render_html
        from app.report_pdf_v4 import render_pdf
        def with_cohort(profile, header, images, *, cohort):
            self.assertFalse(hasattr(cohort, "members"))
            self.assertEqual(cohort.selection_count, 1)
            return render_html(profile, header, images, cohort=cohort), render_pdf(profile, header, images, cohort=cohort)
        self.render.side_effect = with_cohort
        run_id = self.publish()
        raw, _, _ = reports.download(self.store, self.case_id, self.session_id, run_id, "manifest", self.user)
        doc = ReportPublicationV4.model_validate_json(raw)
        self.assertEqual(doc.cohort.reference, cohort.reference)
        self.assertEqual(doc.cohort.domains, comparisons.for_report(self.store, cohort.reference, self.user).domains)
        with self.store.connect(write=True) as db:
            purged = reports.purge_comparisons(db, {"different-snapshot"})
            self.assertEqual(purged, set())
        with self.store.connect(write=True) as db:
            case = self.store.case(db, self.case_id); manifest = self.store.manifest(case)
            manifest.consents.analysis_feedback = "declined"
            self.store.save(db, case, manifest, self.user.username, "synthetic.decline")
        with self.assertRaises(HTTPException):
            reports.download(self.store, self.case_id, self.session_id, run_id, "pdf", self.user)
        with self.store.connect(write=True) as db:
            self.assertEqual(reports.purge_comparisons(db, {cohort.reference.snapshot_id}), {run_id})
            self.assertIsNone(db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone())


class ReportFrameV4Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-s1-report-frame-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        self.path = self.store.path("videos/synthetic.mp4")
        media.command(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=4:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.path)], timeout=30)
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        video = SimpleNamespace(video_id="synthetic", storage_ref="videos/synthetic.mp4", sha256=self.sha, camera_id="CAM2")
        self.evidence = SimpleNamespace(video_id="synthetic", video_sha256=self.sha, camera_id="CAM2", start_seconds=.6, end_seconds=1.2)
        self.snapshot = SimpleNamespace(final_document=SimpleNamespace(basic_document=SimpleNamespace(input_document=
            SimpleNamespace(source=SimpleNamespace(session=SimpleNamespace(videos=(video,)))))),
            profile=SimpleNamespace(scenes=(SimpleNamespace(scene_id="scene-synthetic", evidence=(self.evidence,)),)))
        self.enterContext(patch.object(reports, "verify_files", side_effect=lambda store, snapshot:
            {"videos/synthetic.mp4": analysis.file_stamp(self.path)}))

    def test_actual_frame_pts_and_hash_remain_inside_exact_source_evidence(self):
        images, issues = reports.capture_images(self.store, self.snapshot, "run-synthetic", "step-synthetic", lambda: None)
        self.assertEqual(issues, {})
        self.assertEqual(len(images), 1)
        image = images[0]
        self.assertIn(image.source_seconds, (.75, 1.0))
        self.assertEqual((image.video_sha256, image.camera_id), (self.sha, "CAM2"))
        raw = self.store.path(image.file.ref).read_bytes()
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), image.file.hash)

    def test_no_actual_frame_is_explicit_missing_and_source_mutation_aborts(self):
        self.evidence.start_seconds, self.evidence.end_seconds = .01, .02
        images, issues = reports.capture_images(self.store, self.snapshot, "run-synthetic", "step-missing", lambda: None)
        self.assertEqual(images, ())
        self.assertIn("scene-synthetic", issues)
        self.evidence.start_seconds, self.evidence.end_seconds = .6, 1.2
        calls = []
        def changed():
            calls.append(True)
            if len(calls) == 2:
                self.path.write_bytes(self.path.read_bytes() + b"tampered")
        with self.assertRaises(HTTPException):
            reports.capture_images(self.store, self.snapshot, "run-synthetic", "step-mutated", changed)
