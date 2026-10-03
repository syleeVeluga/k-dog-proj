import asyncio
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import media, preprocess_v4 as preprocess, uploads
from app.domain.catalog_v4 import SEGMENTS, SURVEY_VERSION
from app.domain.media_v4 import ConversionV4, MediaParentV4, UploadCreateV4, UploadLinkV4
from app.domain.preprocess_v4 import PreprocessRequestV4
from app.domain.recording_v4 import RecordingV4
from app.input_models_v3 import CaseCreateV3
from app.intake import create_case
from app.maintenance import backup, clean, references, restore
from app.storage import Store


async def chunks(data):
    yield data


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for synthetic media tests")
class PreprocessV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_temp = tempfile.TemporaryDirectory(prefix="kdog-s1-synthetic-")
        cls.samples = {}
        for name, fps, audio in (("one", 8, True), ("two", 4, True), ("silent", 8, False), ("slow", 0.25, True)):
            path = Path(cls.media_temp.name) / (name + ".mp4")
            media.command(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", f"testsrc2=size=64x64:rate={fps}",
                *(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000"] if audio else []),
                "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)])
            cls.samples[name] = path.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.media_temp.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-s1-preprocess-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "data")
        with self.store.connect(write=True) as db:
            for actor, role in (("op", "operator"), ("review", "reviewer"), ("dev", "developer")):
                db.execute("INSERT INTO users(username,password_hash,role,session_hash) VALUES(?,?,?,?)",
                           (actor, "synthetic", role, "synthetic-" + actor))
            self.case_id = create_case(self.store, db, CaseCreateV3(event_id="SYNTHETIC", participant_id="1", dog_name="합성견"), "op", SURVEY_VERSION)
            self.session_id = self.store.case(db, self.case_id)["selected_session_id"]

    def current(self):
        with self.store.connect() as db:
            return dict(self.store.case(db, self.case_id))

    def upload(self, name="one", camera="CAM1", **changes):
        data = changes.pop("data", self.samples.get(name, b"synthetic-insv"))
        receipt = uploads.create_receipt(self.store, UploadCreateV4(request_id="upload-" + name,
            filename=changes.pop("filename", name + ".mp4"), expected_size=len(data), **changes), "op")
        asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, chunks(data), "op"))
        return uploads.link_receipt(self.store, receipt.upload_id, UploadLinkV4(case_id=self.case_id,
            session_id=self.session_id, camera_id=camera, expected_revision=self.current()["input_revision"]), "op")

    def recording(self, reference, others=(), *, start=0.2, end=4.2, events=(), coverage=()):
        value = {"video_id": reference, "confirmed": True, "procedure_edition": "s1_confirmed", "procedure_note": "합성 검증",
            "segments": [{"segment": segment, "video_id": reference,
                **({"start_sec": start, "end_sec": end} if segment == "entry" else
                   {"state": "not_performed", "reason": "합성 시험에서 생략"})} for segment, _, _ in SEGMENTS],
            "video_offsets": [{"video_id": video, "offset_seconds": offset, "confirmed": offset is not None, "note": "합성 오프셋"}
                              for video, offset in others], "events": list(events), "coverage": list(coverage)}
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            manifest.sessions[0].recording_s1 = RecordingV4.model_validate_json(json.dumps(value))
            self.store.save(db, row, manifest, "op", "recording.s1.save")
        return self.current()["input_revision"]

    def run_batch(self, request_id="batch-request", **changes):
        request = PreprocessRequestV4(request_id=request_id, expected_revision=self.current()["input_revision"], **changes)
        return preprocess.execute(self.store, self.case_id, self.session_id, "op", request)

    @staticmethod
    def event(key, kind, video, start, end, codes=()):
        return {"event_id": key, "kind": kind, "video_id": video, "segment": "entry", "seconds": start,
                "end_seconds": end, "note": "합성 사건", "affected_codes": list(codes)}

    def test_overlapping_logical_windows_merge_physical_clips_and_keep_actual_pts_audio(self):
        video = self.upload()
        self.recording(video.video_id, events=(self.event("free-a", "free_movement", video.video_id, 1, 2),
                                              self.event("free-b", "free_movement", video.video_id, 3, 3.5)))
        batch = self.run_batch()
        self.assertEqual(len(batch.clips), 1)
        clip = batch.clips[0]
        self.assertEqual(clip.status, "complete")
        self.assertEqual(clip.original.fps_policy, "source_frames")
        self.assertEqual(clip.ai.fps_policy, "one_actual_frame_per_second")
        self.assertEqual(len(clip.original.frame_times_seconds), 32)
        self.assertEqual(len(clip.ai.frame_times_seconds), 4)
        self.assertEqual(clip.original.source_frame_times_seconds[0], 0.25)
        self.assertAlmostEqual(clip.original.frame_times_seconds[0] + clip.source_start_seconds, 0.25, delta=0.002)
        self.assertEqual(len({int(t) for t in clip.ai.frame_times_seconds}), len(clip.ai.frame_times_seconds))
        for time in clip.ai.frame_times_seconds:
            self.assertTrue(any(abs(time - original) < 0.0001 for original in clip.original.frame_times_seconds))
        self.assertTrue(set(clip.ai.source_frame_times_seconds) <= set(clip.original.source_frame_times_seconds))
        windows = {value.window.window_id: value for value in batch.windows}
        self.assertEqual(windows["entry_free"].media_available_seconds, 1.5)
        self.assertEqual(windows["entry_whole"].media_available_seconds, 4)
        self.assertAlmostEqual(windows["entry_whole"].audio_available_seconds, 4, places=2)
        self.assertIsNone(windows["entry_whole"].audio_listened_seconds)
        self.assertIsNone(windows["entry_whole"].vocal_seconds)
        self.assertEqual(windows["entry_free"].views[0].clip_ids, (clip.clip_id,))
        self.assertEqual(batch.status, "complete")

    def test_three_cameras_offsets_quality_and_audio_are_not_summed(self):
        one, two, third = self.upload(), self.upload("two", "CAM2"), self.upload("silent", "CAM3")
        events = (self.event("hidden", "body_not_visible", one.video_id, 1, 2),
                  self.event("occluded", "occlusion", two.video_id, 2, 3),
                  self.event("lost", "audio_loss", one.video_id, 1, 2))
        self.recording(one.video_id, ((two.video_id, 1), (third.video_id, None)), events=events)
        batch = self.run_batch(audio_video_id=one.video_id)
        window = next(value for value in batch.windows if value.window.window_id == "entry_whole")
        views = {view.video_id: view for view in window.views}
        self.assertEqual(len(batch.clips), 2)
        self.assertEqual(views[third.video_id].availability, "offset_unconfirmed")
        self.assertEqual(views[one.video_id].visual_state, "body_unobserved")
        self.assertEqual(views[two.video_id].visual_state, "occluded")
        self.assertEqual(window.media_available_seconds, 4)
        self.assertAlmostEqual(window.audio_available_seconds, 3, places=2)
        self.assertEqual([(x.start_seconds, x.end_seconds) for x in window.audio_loss_ranges], [(1, 2)])
        self.assertEqual(window.representative_audio_video_id, one.video_id)
        self.assertEqual(batch.status, "partial")

    def test_insv_and_camera_decode_failure_leave_usable_camera_output(self):
        one = self.upload()
        insv = self.upload("raw", "CAM2", filename="raw.insv")
        broken = self.upload("broken", "CAM3", data=b"invalid-synthetic-container")
        self.recording(one.video_id, ((insv.video_id, 0), (broken.video_id, 0)))
        batch = self.run_batch()
        window = next(value for value in batch.windows if value.window.window_id == "entry_whole")
        self.assertEqual([view.availability for view in window.views], ["available", "conversion_required", "failed"])
        self.assertEqual(len(batch.clips), 1)
        self.assertEqual(batch.clips[0].status, "complete")

    def test_subsecond_window_without_actual_frames_does_not_duplicate_one(self):
        slow = self.upload("slow")
        self.recording(slow.video_id, start=1, end=1.5)
        batch = self.run_batch()
        self.assertEqual(batch.clips[0].status, "no_frames")
        self.assertIsNone(batch.clips[0].original)
        self.assertIsNone(batch.clips[0].ai)

    def test_idempotent_completion_reuse_and_reviewer_verification(self):
        video = self.upload()
        self.recording(video.video_id)
        batch = self.run_batch()
        state = preprocess.status(self.store, self.case_id, self.session_id, "review")
        pointer = state.result_pointer
        with patch.object(media, "cut_clip", side_effect=AssertionError("must reuse immutable media")):
            self.assertEqual(self.run_batch().batch_id, batch.batch_id)
            reused = self.run_batch("reuse-request", reuse=pointer)
        self.assertNotEqual(reused.batch_id, batch.batch_id)
        self.assertNotEqual(reused.claim_token, batch.claim_token)
        self.assertEqual(reused.clips, batch.clips)
        self.assertEqual(reused.reuse_manifest, pointer)
        self.assertEqual(preprocess.verified_batch(self.store, self.case_id, self.session_id, pointer, "review").batch_id, batch.batch_id)
        with self.assertRaises(HTTPException) as invalid:
            self.run_batch("different-camera", reuse=pointer, camera_priority=("CAM2", "CAM1"))
        self.assertEqual(invalid.exception.status_code, 409)

    def test_same_size_source_tamper_and_conversion_parent_tamper_are_rejected(self):
        parent = self.upload("raw", "CAM2", filename="raw.insv")
        converted = self.upload("one", "CAM1", source_kind="received_conversion",
            parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256, video_id=parent.video_id)],
            conversion=ConversionV4(tool="synthetic converter", tool_version="1", settings={"ref": "literal-not-a-link"}))
        self.recording(converted.video_id, ((parent.video_id, 0),))
        batch = self.run_batch()
        pointer = preprocess.status(self.store, self.case_id, self.session_id, "op").result_pointer
        with self.store.connect() as db:
            row = db.execute("SELECT storage_ref FROM upload_receipts WHERE upload_id=?", (parent.upload_id,)).fetchone()
        path = self.store.path(row[0])
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaises(HTTPException) as invalid:
            preprocess.verified_batch(self.store, self.case_id, self.session_id, pointer, "review")
        self.assertEqual(invalid.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            self.run_batch("changed-source")
        self.assertTrue(batch.source_files)

    def test_deletion_and_revision_changes_before_publish_do_not_adopt_batch(self):
        for change in ("deleted", "revised"):
            with self.subTest(change=change):
                video = self.upload("one" + change, data=self.samples["one"])
                self.recording(video.video_id)
                real = preprocess._ai_clip

                def interrupted(*args):
                    real(*args)
                    with self.store.connect(write=True) as db:
                        if change == "deleted":
                            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
                        else:
                            row = self.store.case(db, self.case_id)
                            self.store.save(db, row, self.store.manifest(row), "op", "synthetic.edit")

                with patch.object(preprocess, "_ai_clip", side_effect=interrupted):
                    with self.assertRaises(HTTPException):
                        self.run_batch("interrupted-" + change)
                with self.store.connect(write=True) as db:
                    self.assertFalse(db.execute("SELECT 1 FROM changes WHERE action='preprocess_v4.completed'").fetchone())
                    db.execute("UPDATE cases SET deletion_requested=0 WHERE case_id=?", (self.case_id,))

    def test_claim_loss_and_disabled_actor_reject_publication_and_retry(self):
        video = self.upload()
        self.recording(video.video_id)
        real = preprocess._ai_clip

        def expired(*args):
            real(*args)
            with self.store.connect(write=True) as db:
                self.store.audit(db, "op", self.case_id, "preprocess_v4.started", {"session_id": self.session_id, "claim_token": "new-occupant"})

        with patch.object(preprocess, "_ai_clip", side_effect=expired):
            with self.assertRaises(HTTPException) as error:
                self.run_batch()
        self.assertEqual(error.exception.status_code, 409)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='op'")
        with self.assertRaises(HTTPException) as disabled:
            self.run_batch()
        self.assertEqual(disabled.exception.status_code, 403)

    def test_missing_audio_is_separate_from_visual_availability_and_zero_is_not_inferred(self):
        video = self.upload("silent")
        self.recording(video.video_id)
        batch = self.run_batch()
        window = next(value for value in batch.windows if value.window.window_id == "entry_whole")
        self.assertEqual(window.views[0].availability, "available")
        self.assertEqual(window.media_available_seconds, 4)
        self.assertEqual(window.audio_available_seconds, 0)
        self.assertIsNone(window.vocal_seconds)
        self.assertEqual(window.audio_selection_reason, "no_usable_audio")

    def test_ai_failure_retains_source_clip_and_other_camera_completes(self):
        one, two = self.upload(), self.upload("two", "CAM2")
        self.recording(one.video_id, ((two.video_id, 0),))
        real, attempts = preprocess._ai_clip, []

        def once(*args):
            attempts.append(args)
            if len(attempts) == 1:
                raise media.MediaError("synthetic encoding interruption")
            return real(*args)

        with patch.object(preprocess, "_ai_clip", side_effect=once):
            batch = self.run_batch()
        self.assertEqual([clip.status for clip in batch.clips], ["partial", "complete"])
        self.assertIsNotNone(batch.clips[0].original)
        self.assertIsNone(batch.clips[0].ai)
        self.assertEqual(batch.status, "partial")

    def test_artifact_tamper_and_post_hash_source_race_cannot_be_adopted(self):
        video = self.upload()
        self.recording(video.video_id)
        batch = self.run_batch()
        pointer = preprocess.status(self.store, self.case_id, self.session_id, "op").result_pointer
        artifact = self.store.path(batch.clips[0].ai.ref)
        raw = artifact.read_bytes()
        artifact.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(HTTPException):
            preprocess.verified_batch(self.store, self.case_id, self.session_id, pointer, "review")
        artifact.write_bytes(raw)
        real = preprocess._assert_files

        def mutate_before_publication(store, identities):
            source = store.path(batch.source_files[0].ref)
            raw_source = source.read_bytes()
            source.write_bytes(raw_source[:-1] + bytes([raw_source[-1] ^ 1]))
            return real(store, identities)

        with patch.object(preprocess, "_assert_files", side_effect=mutate_before_publication):
            with self.assertRaises(HTTPException) as error:
                self.run_batch("race-request")
        self.assertEqual(error.exception.status_code, 409)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.completed'").fetchone()[0], 1)

    def test_revision_stale_status_and_request_identity_mismatch(self):
        video = self.upload()
        self.recording(video.video_id)
        batch = self.run_batch()
        with self.assertRaises(HTTPException) as conflict:
            self.run_batch(audio_video_id=video.video_id)
        self.assertEqual(conflict.exception.status_code, 409)
        self.recording(video.video_id, start=0.3)
        state = preprocess.status(self.store, self.case_id, self.session_id, "review")
        self.assertTrue(state.outdated)
        self.assertEqual(state.result.batch_id, batch.batch_id)
        with self.assertRaises(HTTPException):
            self.run_batch("stale-reuse", reuse=state.result_pointer)
        pinned = preprocess.verified_batch(self.store, self.case_id, self.session_id, state.result_pointer, "review",
            expected_input=batch.input, expected_revision=batch.input_revision)
        self.assertEqual(pinned.batch_id, batch.batch_id)
        with self.assertRaises(HTTPException):
            preprocess.verified_batch(self.store, self.case_id, self.session_id, state.result_pointer, "review", expected_input=batch.input)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
        with self.assertRaises(HTTPException) as removed:
            preprocess.verified_batch(self.store, self.case_id, self.session_id, state.result_pointer, "review",
                expected_input=batch.input, expected_revision=batch.input_revision)
        self.assertEqual(removed.exception.status_code, 403)

    def test_backup_restore_explicit_reuse_and_deletion_ledger_cover_typed_artifacts_only(self):
        parent = self.upload("raw", "CAM2", filename="raw.insv")
        video = self.upload("one", "CAM1", source_kind="received_conversion",
            parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256, video_id=parent.video_id)],
            conversion=ConversionV4(tool="synthetic", tool_version="1", settings={
                "ref": "participant supplied literal, not file", "metadata_json": "not JSON"}))
        self.recording(video.video_id, ((parent.video_id, 0),))
        batch = self.run_batch()
        state = preprocess.status(self.store, self.case_id, self.session_id, "review")
        reused = self.run_batch("reuse-for-backup", reuse=state.result_pointer)
        pointer = preprocess.status(self.store, self.case_id, self.session_id, "review").result_pointer
        with self.store.connect() as db:
            found = references(self.store, db)
        self.assertIn(batch.clips[0].original.ref, found)
        self.assertIn(batch.clips[0].ai.ref, found)
        self.assertIn(state.result_pointer.ref, found)
        self.assertIn(pointer.ref, found)
        destination = self.store.root.parent / "backup"
        backup(self.store, destination, "op")
        restored_path = self.store.root.parent / "restored"
        restore(self.store, destination, restored_path)
        restored = Store(restored_path)
        self.assertEqual(preprocess.verified_batch(restored, self.case_id, self.session_id, pointer, "review").batch_id, reused.batch_id)
        after_restore = preprocess.execute(restored, self.case_id, self.session_id, "op",
            PreprocessRequestV4(request_id="after-restore", expected_revision=batch.input_revision, reuse=pointer))
        self.assertEqual(after_restore.clips, batch.clips)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
        clean(self.store, purge_deleted=True)
        erased_path = self.store.root.parent / "restored-after-deletion"
        restore(self.store, destination, erased_path)
        erased = Store(erased_path)
        with erased.connect() as db:
            self.assertFalse(db.execute("SELECT 1 FROM cases").fetchone())
            self.assertFalse(db.execute("SELECT 1 FROM upload_receipts").fetchone())
        for directory in ("inputs", "videos", "clips"):
            self.assertFalse([path for path in erased.path(directory).rglob("*") if path.is_file()])
