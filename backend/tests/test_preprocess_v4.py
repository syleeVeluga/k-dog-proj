import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import os
from pathlib import Path
import shutil
import tempfile
from threading import Barrier, Event, Lock
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import media, preprocess_v4 as preprocess, scoring_ai_v4, uploads
from app.domain.catalog_v4 import SEGMENTS, SURVEY_VERSION
from app.domain.media_v4 import ConversionV4, MediaParentV4, UploadCreateV4, UploadLinkV4
from app.domain.preprocess_v4 import PreprocessRequestV4
from app.domain.recording_v4 import RecordingV4
from app.input_models_v3 import CaseCreateV3
from app.intake import create_case
from app.maintenance import backup, clean, references, restore
from app.storage import Store
from tests import test_scoring_ai_v4 as scoring_fixture


async def chunks(data):
    yield data


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for synthetic media tests")
class PreprocessV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_temp = tempfile.TemporaryDirectory(prefix="kdog-s1-synthetic-")
        cls.samples = {}
        for name, fps, audio in (("one", 8, True), ("two", 4, True), ("silent", 8, False), ("thirty", 30, False), ("slow", 0.25, True), ("slow_silent", 0.25, False), ("mkv", 8, False)):
            path = Path(cls.media_temp.name) / (name + (".mkv" if name == "mkv" else ".mp4"))
            media.command(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i", f"testsrc2=size=64x64:rate={fps}",
                *(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000"] if audio else []),
                "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                *(["-f", "matroska"] if name == "mkv" else []), str(path)])
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
        data = changes.pop("data", self.samples.get(name, b"synthetic-original"))
        receipt = uploads.create_receipt(self.store, UploadCreateV4(request_id="upload-" + name,
            filename=changes.pop("filename", name + ".mp4"), expected_size=len(data), **changes), "op")
        asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, chunks(data), "op"))
        return uploads.link_receipt(self.store, receipt.upload_id, UploadLinkV4(case_id=self.case_id,
            session_id=self.session_id, camera_id=camera, expected_revision=self.current()["input_revision"]), "op")

    def recording(self, reference, others=(), *, start=0.2, end=4.2, events=(), coverage=(), baseline=None):
        value = {"video_id": reference, "confirmed": True, "procedure_edition": "s1_confirmed", "procedure_note": "합성 검증",
            "segments": [{"segment": segment, "video_id": reference,
                **({"start_sec": start, "end_sec": end} if segment == "entry" else
                   {"start_sec": baseline[0], "end_sec": baseline[1]} if segment == "baseline" and baseline else
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

    def test_cli_executes_s1_and_reuses_only_the_same_explicit_request(self):
        import subprocess
        import sys
        linked = self.upload()
        self.recording(linked.video_id)
        command = [sys.executable, "-X", "utf8", "-m", "app.manage", "--data-dir", str(self.store.root),
                   "preprocess", self.case_id, "--actor", "op", "--request-id", "s1-cli-request",
                   "--expected-revision", str(self.current()["input_revision"])]
        first = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                               text=True, encoding="utf-8", timeout=60)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_result = json.loads(first.stdout)
        self.assertEqual(first_result["status"], "complete")
        self.assertGreater(first_result["clips"], 0)
        repeated = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                  text=True, encoding="utf-8", timeout=30)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout), first_result)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.completed'").fetchone()[0], 1)

    @staticmethod
    def event(key, kind, video, start, end, codes=()):
        return {"event_id": key, "kind": kind, "video_id": video, "segment": "entry", "seconds": start,
                "end_seconds": end, "note": "합성 사건", "affected_codes": list(codes)}

    def test_eight_segment_csv_record_without_exit_end_or_phases_can_preprocess(self):
        video = self.upload()
        self.recording(video.video_id)
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            value = manifest.sessions[0].recording_s1.model_dump(mode="json")
            value["segments"] = [{"segment": segment, "video_id": video.video_id,
                                  "start_sec": index * 0.5 + 0.2,
                                  "end_sec": (index + 1) * 0.5 + 0.2 if index < 7 else None}
                                 for index, (segment, _, _) in enumerate(SEGMENTS)]
            manifest.sessions[0].recording_s1 = RecordingV4.model_validate_json(json.dumps(value))
            self.store.save(db, row, manifest, "op", "recording.s1.save")
        batch = self.run_batch()
        self.assertEqual(batch.status, "complete")
        self.assertTrue(batch.clips)
        windows = {value.window.window_id: value for value in batch.windows}
        for key in ("exit_whole", "walk_phase_1", "reunion_contact"):
            self.assertEqual(windows[key].window.status, "unobserved")
            self.assertIsNone(windows[key].window.start_seconds)
        self.assertEqual(windows["walk_whole"].window.status, "confirmed")

    def test_logical_windows_have_separate_clips_and_keep_actual_pts_audio(self):
        video = self.upload()
        self.recording(video.video_id, events=(self.event("free-a", "free_movement", video.video_id, 1, 2),
                                              self.event("free-b", "free_movement", video.video_id, 3, 3.5)))
        batch = self.run_batch()
        self.assertEqual(len(batch.clips), 2)
        clip = next(clip for clip in batch.clips if "entry_whole" in clip.window_ids)
        event_clip = next(clip for clip in batch.clips if "entry_free" in clip.window_ids)
        self.assertEqual((event_clip.source_start_seconds, event_clip.source_end_seconds), (1, 3.5))
        self.assertNotEqual(clip.clip_id, event_clip.clip_id)
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
        self.assertEqual(windows["entry_free"].views[0].clip_ids, (event_clip.clip_id,))
        self.assertEqual(batch.status, "complete")

    def test_window_split_preserves_full_observation_and_final_real_frame_display(self):
        video = self.upload('silent')
        self.recording(video.video_id,start=0,end=3,baseline=(3,6),
            events=(self.event('free','free_movement',video.video_id,1,2),))
        batch = self.run_batch()
        with self.store.connect() as db:
            session = self.store.manifest(self.store.case(db,self.case_id)).sessions[0]
        source = scoring_fixture.snapshot().model_copy(update={'batch':batch,'session':session})
        whole = next(c for c in batch.clips if 'entry_whole' in c.window_ids)
        self.assertEqual(whole.ai.frame_times_seconds,(0,1,2))
        self.assertEqual(whole.ai.source_frame_times_seconds,(0,1,2))
        self.assertAlmostEqual(media.probe(self.store.path(whole.ai.ref))['duration_sec'],3,delta=0.002)
        info = scoring_ai_v4.context(source,scoring_fixture.group('바6'),{'run_id':'synthetic'},'op')
        self.assertNotIn('바6',info['response_constraints']['whole_interval_unavailable_item_codes'])
        bounds = info['response_constraints']['evidence_intervals']
        self.assertEqual([(b['start_seconds'],b['end_seconds']) for b in bounds],[(0,3)])
        free = scoring_ai_v4.context(source,scoring_fixture.group('보6'),{'run_id':'synthetic'},'op')
        bounds = [b for b in free['response_constraints']['evidence_intervals'] if b['window_id']=='entry_free']
        self.assertEqual([(b['start_seconds'],b['end_seconds']) for b in bounds],[(0,1)])
        event_clip = next(c for c in batch.clips if 'entry_free' in c.window_ids)
        self.assertEqual(event_clip.ai.source_frame_times_seconds,(1,))
        self.assertAlmostEqual(media.probe(self.store.path(event_clip.ai.ref))['duration_sec'],1,delta=0.002)

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

    def test_camera_decode_failure_leave_usable_camera_output(self):
        one = self.upload()
        broken = self.upload("broken", "CAM3", data=b"invalid-synthetic-container")
        self.recording(one.video_id, ((broken.video_id, 0),))
        batch = self.run_batch()
        window = next(value for value in batch.windows if value.window.window_id == "entry_whole")
        self.assertEqual([view.availability for view in window.views], ["available", "failed"])
        self.assertEqual(len(batch.clips), 1)
        self.assertEqual(batch.clips[0].status, "complete")

    def test_four_cameras_include_silent_mkv_with_source_and_actual_one_fps_clips(self):
        one = self.upload()
        two = self.upload("two", "CAM2")
        three = self.upload("silent", "CAM3")
        four = self.upload("mkv", "CAM4", filename="6_CAM4_오른쪽.camera", source_kind="received_file")
        self.assertIsNone(self.store.view(self.current()).manifest.sessions[0].videos[-1].source_original_number)
        self.recording(one.video_id, ((two.video_id, 0), (three.video_id, 0), (four.video_id, 0)))
        batch = self.run_batch()
        self.assertEqual(batch.request.camera_priority, ("CAM1", "CAM2", "CAM3", "CAM4"))
        self.assertEqual(len(batch.clips), 4)
        for clip in batch.clips:
            self.assertEqual(clip.status, "complete")
            self.assertEqual(clip.original.fps_policy, "source_frames")
            self.assertEqual(clip.ai.fps_policy, "one_actual_frame_per_second")
            self.assertGreater(len(clip.original.frame_times_seconds), len(clip.ai.frame_times_seconds))
        window = next(value for value in batch.windows if value.window.window_id == "entry_whole")
        self.assertEqual(window.representative_audio_video_id, one.video_id)
        silent = next(view for view in window.views if view.video_id == four.video_id)
        self.assertEqual(silent.availability, "available")
        self.assertIn("audio_absent_or_unavailable", silent.reasons)

    def test_subsecond_window_without_actual_frames_does_not_duplicate_one(self):
        slow = self.upload("slow")
        self.recording(slow.video_id, start=1, end=1.5)
        batch = self.run_batch()
        self.assertEqual(batch.clips[0].status, "no_frames")
        self.assertIsNone(batch.clips[0].original)
        self.assertIsNone(batch.clips[0].ai)

    def assert_window_frame_mapping(self, name, start, end, first_source):
        video = self.upload(name)
        self.recording(video.video_id,start=0,end=5,
            events=(self.event('free-cut','free_movement',video.video_id,start,end),))
        batch = self.run_batch()
        clip = next(c for c in batch.clips if 'entry_free' in c.window_ids)
        self.assertEqual(clip.status,'complete')
        for derivative in (clip.original,clip.ai):
            self.assertAlmostEqual(derivative.source_frame_times_seconds[0],first_source,places=5)
            for local, source in zip(derivative.frame_times_seconds,derivative.source_frame_times_seconds):
                self.assertAlmostEqual(local+derivative.source_time_offset_seconds,source,delta=0.002)
            self.assertEqual(derivative.audio_ranges,())
        self.assertEqual(clip.ai.frame_times_seconds[0],clip.original.frame_times_seconds[0])
        self.assertEqual(clip.ai.source_time_offset_seconds,clip.original.source_time_offset_seconds)
        self.assertGreaterEqual(clip.ai.duration_seconds,clip.original.duration_seconds-0.002)

    def test_silent_low_fps_window_maps_first_actual_frame_to_source(self):
        self.assert_window_frame_mapping('slow_silent',1,4.1,4)

    def test_silent_fractional_window_maps_actual_frames_to_source(self):
        self.assert_window_frame_mapping('silent',1.1,1.9,1.125)

    def test_fractional_source_cut_keeps_requested_end_for_original_and_ai(self):
        video = self.upload('thirty')
        self.recording(video.video_id,start=1.602,end=4.392)
        batch = self.run_batch()
        clip = next(c for c in batch.clips if 'entry_whole' in c.window_ids)
        self.assertEqual(clip.status,'complete')
        self.assertEqual(len(clip.original.frame_times_seconds),83)
        self.assertEqual(len(clip.ai.frame_times_seconds),3)
        for derivative in (clip.original,clip.ai):
            self.assertGreaterEqual(derivative.duration_seconds+derivative.source_time_offset_seconds,4.392-1e-6)
            for local,source_time in zip(derivative.frame_times_seconds,derivative.source_frame_times_seconds):
                self.assertAlmostEqual(local+derivative.source_time_offset_seconds,source_time,delta=0.002)
        with self.store.connect() as db:
            session = self.store.manifest(self.store.case(db,self.case_id)).sessions[0]
        source = scoring_fixture.snapshot().model_copy(update={'batch':batch,'session':session})
        for variant in ('original','ai'):
            stage = scoring_fixture.group('바6').model_copy(update={'input_variant':variant})
            constraints = scoring_ai_v4.context(source,stage,{'run_id':'synthetic'},'op')['response_constraints']
            self.assertNotIn('바6',constraints['whole_interval_unavailable_item_codes'])
            bound = constraints['evidence_intervals'][0]
            self.assertAlmostEqual(bound['start_seconds']+getattr(clip,variant).source_time_offset_seconds,1.602,places=6)
            self.assertAlmostEqual(bound['end_seconds']+getattr(clip,variant).source_time_offset_seconds,4.392,places=6)

    def assert_audio_playback_end(self, name, start, end):
        video = self.upload(name)
        self.recording(video.video_id,start=start,end=end)
        clip = next(c for c in self.run_batch().clips if 'entry_whole' in c.window_ids)
        self.assertEqual(clip.status,'complete')
        for derivative in (clip.original,clip.ai):
            self.assertAlmostEqual(media.probe(self.store.path(derivative.ref))['duration_sec'],end-start,delta=0.002)
            self.assertTrue(derivative.audio_ranges)
            for local,source in zip(derivative.frame_times_seconds,derivative.source_frame_times_seconds):
                self.assertAlmostEqual(local+derivative.source_time_offset_seconds,source,delta=0.002)

    def test_audio_low_fps_cut_preserves_playback_end_without_overshoot(self):
        self.assert_audio_playback_end('slow',1,4.1)

    def test_audio_fractional_cut_preserves_playback_end_without_overshoot(self):
        self.assert_audio_playback_end('one',1.1,1.9)

    def test_idempotent_completion_reuse_and_reviewer_verification(self):
        video = self.upload()
        self.recording(video.video_id)
        batch = self.run_batch()
        state = preprocess.status(self.store, self.case_id, self.session_id, "review")
        pointer = state.result_pointer
        with patch.object(preprocess, "_source_clip", side_effect=AssertionError("must reuse immutable media")):
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
        parent = self.upload("raw", "CAM2", filename="raw.mp4")
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
                with self.store.connect() as db:
                    before_count = db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.completed'").fetchone()[0]

                def interrupted(*args):
                    selected = real(*args)
                    with self.store.connect(write=True) as db:
                        if change == "deleted":
                            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
                        else:
                            row = self.store.case(db, self.case_id)
                            self.store.save(db, row, self.store.manifest(row), "op", "synthetic.edit")
                    return selected

                with patch.object(preprocess, "_ai_clip", side_effect=interrupted):
                    if change == "revised":
                        with self.assertRaises(HTTPException): self.run_batch("interrupted-" + change)
                    else:
                        self.assertTrue(self.run_batch("interrupted-" + change).clips)
                with self.store.connect(write=True) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.completed'").fetchone()[0], before_count + int(change == "deleted"))
                    db.execute("UPDATE cases SET deletion_requested=0 WHERE case_id=?", (self.case_id,))

    def test_claim_loss_and_disabled_actor_reject_publication_and_retry(self):
        video = self.upload()
        self.recording(video.video_id)
        real = preprocess._ai_clip

        def expired(*args):
            selected = real(*args)
            with self.store.connect(write=True) as db:
                self.store.audit(db, "op", self.case_id, "preprocess_v4.started", {"session_id": self.session_id, "claim_token": "new-occupant"})
            return selected

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
        self.assertCountEqual([clip.status for clip in batch.clips], ["partial", "complete"])
        self.assertEqual({clip.video_id for clip in batch.clips}, {one.video_id, two.video_id})
        failed = next(clip for clip in batch.clips if clip.status == "partial")
        self.assertIsNotNone(failed.original)
        self.assertIsNone(failed.ai)
        self.assertEqual(batch.status, "partial")

    def test_shared_decode_checks_frames_once_per_encoded_variant(self):
        video = self.upload()
        self.recording(video.video_id)
        with patch.object(media, "command", wraps=media.command) as commands:
            batch = self.run_batch()
        self.assertEqual(batch.clips[0].status, "complete")
        arguments = [call.args[0] for call in commands.call_args_list]
        encodes = [args for args in arguments if args[0] == "ffmpeg" and "libx264" in args]
        self.assertEqual(len(encodes), 1)
        self.assertEqual(encodes[0].count("libx264"), 2)
        self.assertEqual(sum("-show_frames" in args for args in arguments), 3)
        self.assertEqual(sum("-show_packets" in args for args in arguments), 2)

    def test_shared_encoding_error_rechecks_original_and_completes_ai_separately(self):
        video = self.upload()
        self.recording(video.video_id)
        real, failed = media.command, []
        def command(arguments, **kwargs):
            if arguments[0] == "ffmpeg" and arguments.count("libx264") == 2:
                failed.append(True)
                raise media.MediaError("synthetic shared output error")
            return real(arguments, **kwargs)
        with patch.object(media, "command", side_effect=command):
            batch = self.run_batch()
        self.assertEqual(failed, [True])
        self.assertEqual(batch.clips[0].status, "complete")
        self.assertIsNotNone(batch.clips[0].original)
        self.assertIsNotNone(batch.clips[0].ai)

    def test_parallel_clip_jobs_overlap_with_a_bound_of_two(self):
        video = self.upload()
        self.recording(video.video_id, start=0, end=2, baseline=(2, 4),
            events=(self.event("free", "free_movement", video.video_id, 0.5, 1),))
        real, release, ready, lock = preprocess._source_clip, Event(), Barrier(3), Lock()
        counts = {"started":0, "active":0, "maximum":0}
        def blocked(*args):
            with lock:
                counts["started"] += 1
                counts["active"] += 1
                counts["maximum"] = max(counts["maximum"], counts["active"])
                first = counts["started"] <= 2
            try:
                if first:
                    ready.wait(timeout=10)
                    self.assertTrue(release.wait(timeout=10))
                return real(*args)
            finally:
                with lock: counts["active"] -= 1
        with patch.object(preprocess, "_source_clip", side_effect=blocked), ThreadPoolExecutor(max_workers=1) as runner:
            future = runner.submit(self.run_batch)
            try:
                ready.wait(timeout=10)
                self.assertEqual(counts["started"], 2)
            finally:
                release.set()
            batch = future.result(timeout=30)
        self.assertEqual(counts["started"], 3)
        self.assertEqual(counts["maximum"], 2)
        self.assertEqual([clip.status for clip in batch.clips], ["complete"]*3)

    def test_fatal_child_drains_peer_before_failure_and_stops_new_jobs(self):
        video = self.upload()
        self.recording(video.video_id, start=0, end=2, baseline=(2, 4),
            events=(self.event("free", "free_movement", video.video_id, 0.5, 1),))
        ready, release, raised, lock = Barrier(3), Event(), Event(), Lock()
        started = []
        def blocked(*args):
            with lock:
                started.append(args)
                first = len(started) == 1
            ready.wait(timeout=10)
            if first:
                raised.set()
                raise HTTPException(409, "synthetic lost claim")
            self.assertTrue(release.wait(timeout=10))
            raise HTTPException(409, "synthetic peer drained")
        with patch.object(preprocess, "_source_clip", side_effect=blocked), ThreadPoolExecutor(max_workers=1) as runner:
            future = runner.submit(self.run_batch)
            try:
                ready.wait(timeout=10)
                self.assertTrue(raised.wait(timeout=10))
                with self.assertRaises(TimeoutError): future.result(timeout=0.1)
                with self.store.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.failed'").fetchone()[0], 0)
                self.assertEqual(len(started), 2)
            finally:
                release.set()
            with self.assertRaises(HTTPException): future.result(timeout=10)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.completed'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.failed'").fetchone()[0], 1)
        self.assertEqual(len(started), 2)

    def test_derivative_change_during_hash_is_rejected_before_publication(self):
        video = self.upload()
        self.recording(video.video_id)
        real = preprocess.file_hash
        def changed(path):
            value = real(path)
            if str(path).endswith("-ai.mp4"):
                raw = Path(path).read_bytes()
                Path(path).write_bytes(raw[:-1] + bytes([raw[-1]^1]))
            return value
        with patch.object(preprocess, "file_hash", side_effect=changed):
            with self.assertRaises(HTTPException): self.run_batch()
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.completed'").fetchone()[0], 0)

    def test_clock_cache_is_bound_to_the_file_before_metadata_hash(self):
        video = self.upload("silent")
        self.recording(video.video_id, start=0, end=3)
        real = preprocess._clip_file
        def shifted(store, path, *args):
            replacement = path.with_name(path.stem+"-changed.mp4")
            media.command(["ffmpeg", "-v", "error", "-nostdin", "-n", "-i", str(path),
                "-c", "copy", "-output_ts_offset", "1", str(replacement)])
            replacement.replace(path)
            return real(store, path, *args)
        with patch.object(preprocess, "_clip_file", side_effect=shifted):
            with self.assertRaises(HTTPException) as error: self.run_batch()
        self.assertEqual(error.exception.status_code, 409)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.completed'").fetchone()[0], 0)

    def test_peer_failure_after_success_snapshot_prevents_refill(self):
        video = self.upload()
        self.recording(video.video_id, start=0, end=2, baseline=(2,4),
            events=(self.event("free", "free_movement", video.video_id, 0.5, 1),))
        real_source, real_wait = preprocess._source_clip, preprocess.wait
        release, lock, started, submitted, snapshots = Event(), Lock(), [], [], []
        class Pool(ThreadPoolExecutor):
            def submit(self, *args, **kwargs):
                submitted.append(True)
                return super().submit(*args, **kwargs)
        def source(*args):
            with lock:
                started.append(True)
                second = len(started) == 2
            if second:
                self.assertTrue(release.wait(timeout=10))
                raise HTTPException(409, "synthetic fatal peer")
            return real_source(*args)
        def snapshot(futures, **kwargs):
            done, pending = real_wait(futures, **kwargs)
            if not snapshots:
                snapshots.append(True)
                self.assertEqual(len(done), 1)
                self.assertIsNone(next(iter(done)).exception())
                release.set()
                real_wait(pending, timeout=10)
                self.assertTrue(any(f.exception() is not None for f in pending))
            return done, pending
        try:
            with patch.object(preprocess, "ThreadPoolExecutor", Pool), \
                    patch.object(preprocess, "_source_clip", side_effect=source), \
                    patch.object(preprocess, "wait", side_effect=snapshot):
                with self.assertRaises(HTTPException): self.run_batch()
        finally:
            release.set()
        self.assertEqual(len(submitted), 2)
        self.assertEqual(len(started), 2)

    @unittest.skipUnless(os.name == "nt", "Windows timestamp restoration")
    def test_windows_content_fingerprint_rejects_all_restored_timestamps(self):
        import ctypes
        import msvcrt
        class FileBasicInfo(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in ("CreationTime", "LastAccessTime", "LastWriteTime", "ChangeTime")] + [
                ("FileAttributes", ctypes.c_uint32)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        query, update = kernel.GetFileInformationByHandleEx, kernel.SetFileInformationByHandle
        for function in (query, update):
            function.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
            function.restype = ctypes.c_int
        path = self.store.root/"synthetic-identity.bin"
        path.write_bytes(b"first-value")
        before, info = preprocess._file_identity(path), FileBasicInfo()
        with path.open("rb") as handle:
            self.assertTrue(query(ctypes.c_void_p(msvcrt.get_osfhandle(handle.fileno())), 0,
                                  ctypes.byref(info), ctypes.sizeof(info)))
        path.write_bytes(b"other-value")
        with path.open("r+b") as handle:
            self.assertTrue(update(ctypes.c_void_p(msvcrt.get_osfhandle(handle.fileno())), 0,
                                   ctypes.byref(info), ctypes.sizeof(info)))
        after = preprocess._file_identity(path)
        self.assertEqual(after[:-1], before[:-1])
        self.assertNotEqual(path.read_bytes(), b"first-value")
        self.assertNotEqual(after, before)
        with self.assertRaises(HTTPException): preprocess._check_identity(path, before)

    def test_restored_mtime_between_clock_and_hash_cannot_publish(self):
        video = self.upload("silent")
        self.recording(video.video_id, start=0, end=3)
        real = preprocess._clip_file
        def changed(store, path, *args):
            stat, raw = path.stat(), path.read_bytes()
            path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            return real(store, path, *args)
        with patch.object(preprocess, "_clip_file", side_effect=changed):
            with self.assertRaises(HTTPException) as error: self.run_batch()
        self.assertEqual(error.exception.status_code, 409)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='preprocess_v4.completed'").fetchone()[0], 0)

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
        self.assertEqual(preprocess.verified_batch(self.store, self.case_id, self.session_id, state.result_pointer, "review",
            expected_input=batch.input, expected_revision=batch.input_revision).batch_id, batch.batch_id)

    def test_backup_restore_explicit_reuse_and_deletion_ledger_cover_typed_artifacts_only(self):
        parent = self.upload("raw", "CAM2", filename="raw.mp4")
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
        clean(self.store)
        erased_path = self.store.root.parent / "restored-after-deletion"
        restore(self.store, destination, erased_path)
        erased = Store(erased_path)
        self.assertEqual(preprocess.verified_batch(erased, self.case_id, self.session_id, pointer, "review").batch_id, reused.batch_id)
        with erased.connect() as db:
            self.assertTrue(erased.case(db, self.case_id))
            references(erased, db)
