"""Source-time plans and real synthetic FFmpeg batches, distinct from provider validation."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import maintenance, preprocess, preprocess_v3
from app.api import create_app
from app.domain.preprocess_v3 import BatchV3
from app.domain.recording_v3 import WALK_PHASES
from app.input_models_v3 import ManifestV3
from app.media import cut_clip
from tests.support import AppCase


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for synthetic clip verification")
class PreprocessV3Tests(AppCase):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.TemporaryDirectory(prefix="kdog-v3-source-")
        cls.source = Path(cls.media.name) / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc=size=96x64:rate=12:duration=100",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=100", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(cls.source)], check=True, capture_output=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        cls.media.cleanup()

    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.client_for("operator")
        self.item = self.upload(self.make_case(), self.source.read_bytes()).json()
        self.video = self.item["manifest"]["sessions"][0]["videos"][0]
        self.endpoint = f"/api/cases/{self.item['case_id']}/sessions/{self.item['selected_session_id']}"

    def recording(self):
        spans = [("entry", 0, 10), ("baseline", 10, 20), ("alone", 20, 30), ("reunion", 30, 40),
                 ("ignore", 40, 50), ("walk", 52, 64), ("stranger", 70, 80), ("exit", 82, 92)]
        return {"video_id": self.video["video_id"], "segments": [
            {"segment": segment, "video_id": self.video["video_id"], "start_sec": start, "end_sec": end}
            for segment, start, end in spans], "walk_phases": [
                {"phase": phase, "video_id": self.video["video_id"], "start_sec": 52 + i * 2, "end_sec": 54 + i * 2}
                for i, phase in enumerate(WALK_PHASES)]}

    def event(self, kind, seconds, segment="stranger", **extra):
        return {"event_id": kind, "kind": kind, "video_id": self.video["video_id"], "segment": segment,
                "seconds": seconds, "note": "독립 합성 실제 사건", **extra}

    def save_record(self, record):
        response = self.client.put(self.endpoint + "/recording", json={"expected_revision": self.item["input_revision"], "recording": record, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()
        return ManifestV3.model_validate_json(json.dumps(self.item["manifest"])).sessions[0]

    def run_preprocess(self):
        response = self.client.post(self.endpoint + "/preprocess", json={"expected_revision": self.item["input_revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]

    def test_plan_uses_actual_short_contact_call_phases_and_reuses_same_interval(self):
        record = self.recording()
        record["events"] = [self.event("stranger_name", 78), self.event("stranger_contact_start", 74),
                            self.event("stranger_contact_end", 74.25), self.event("welfare_stop", 75),
                            self.event("floor_contact", 1, "entry"), self.event("object_near", 2, "entry"),
                            self.event("object_stop", 3, "entry", end_seconds=4)]
        planned = preprocess_v3.window_plan(self.save_record(record))
        windows = {window["window_id"]: window for window in planned["windows"]}
        self.assertEqual((windows["stranger_contact"]["start_sec"], windows["stranger_contact"]["end_sec"]), (74, 74.25))
        self.assertEqual((windows["stranger_call"]["start_sec"], windows["stranger_call"]["end_sec"], windows["stranger_call"]["status"]), (78, 80, "partial"))
        self.assertEqual(windows["walk_phase_6"]["end_sec"], 64)
        self.assertEqual(windows["walk_preparation"]["start_sec"], 50)
        self.assertEqual(windows["entry_object"]["start_sec"], 2)
        self.assertEqual(windows["entry_leash"]["clip_names"], windows["entry_leash_before"]["clip_names"] + windows["entry_leash_after"]["clip_names"])
        self.assertEqual(windows["alone_initial"]["clip_names"], windows["alone"]["clip_names"])
        self.assertEqual(len({(clip["start_sec"], clip["end_sec"]) for clip in planned["clips"]}), len(planned["clips"]))
        self.assertEqual(windows["stranger_contact_plan"]["status"], "guidance_only")
        self.assertTrue(all(clip["fps"] is None for clip in planned["clips"]))

    def test_skip_short_separation_and_no_contact_keep_other_valid_windows(self):
        for length in (5, 15):
            record = self.recording()
            record["segments"][2].update(state="welfare_stopped", end_sec=20 + length, reason="즉시 복귀")
            record["segments"][3].update(start_sec=20 + length)
            planned = preprocess_v3.window_plan(self.save_record(record))
            later = next(window for window in planned["windows"] if window["window_id"] == "alone_later")
            self.assertEqual(later["status"], "unobserved" if length == 5 else "partial")
            self.assertTrue(all(clip["end_sec"] > clip["start_sec"] for clip in planned["clips"]))
        record = self.recording()
        for window in record["segments"][2:4]:
            window.update(state="not_performed", start_sec=None, end_sec=None, reason="분리 요청 없음")
        record["events"] = [self.event("stranger_contact_start", None, status="not_occurred", note="미접촉")]
        self.save_record(record)
        preview = self.client.get(self.endpoint + "/preprocess").json()
        self.assertTrue(preview["ready"])
        self.assertFalse({"alone", "reunion"} & {clip["segment"] for clip in preview["planned_clips"]})
        contact = next(window for window in preview["observation_windows"] if window["window_id"] == "stranger_contact")
        self.assertEqual(contact["status"], "no_opportunity")
        self.assertEqual(contact["clip_names"], [])
        self.assertEqual(self.client_for("reviewer").post(self.endpoint + "/preprocess", json={"expected_revision": self.item["input_revision"]}).status_code, 403)

    def test_real_batch_native_frames_audio_quality_source_mapping_backup_and_retry(self):
        record = self.recording()
        record["events"] = [self.event("stranger_contact_start", 74), self.event("stranger_contact_end", 74.25),
                            self.event("audio_loss", 72, end_seconds=73, note="녹음 손상 실제1초"),
                            self.event("occlusion", 75, end_seconds=76, affected_codes=["개51"])]
        self.save_record(record)
        result = self.run_preprocess()
        BatchV3.model_validate_json(json.dumps(result))
        contact = next(window for window in result["windows"] if window["window_id"] == "stranger_contact")
        short = next(clip for clip in result["clips"] if clip["name"] == contact["clip_names"][0])
        self.assertAlmostEqual(short["decoded_duration_sec"], .25, delta=.1)
        self.assertEqual(short["source_time_offset_sec"] + .1, 74.1)
        full = next(clip for clip in result["clips"] if "stranger" in clip["window_ids"])
        self.assertEqual(full["fps"], "12/1")
        self.assertEqual(full["audio_status"], "present")
        self.assertEqual(full["audio_available_seconds"], 9)
        self.assertIsNone(full["audio_listened_seconds"])
        self.assertIsNone(full["vocal_seconds"])
        self.assertEqual({event["kind"] for event in full["quality_events"]}, {"audio_loss", "occlusion"})
        with self.store.connect() as db:
            refs = maintenance.references(self.store, db)
        self.assertTrue(all(clip["ref"] in refs for clip in result["clips"]))
        again = self.run_preprocess()
        self.assertNotEqual(result["batch_id"], again["batch_id"])
        self.assertTrue(all(self.store.path(clip["ref"]).is_file() for clip in result["clips"]))
        backup = Path(self.temp.name).parent / (self.root.name + "-backup")
        self.addCleanup(lambda: shutil.rmtree(backup, ignore_errors=True))
        maintenance.backup(self.store, backup, "operator")
        restored = Path(self.temp.name).parent / (self.root.name + "-restored")
        self.addCleanup(lambda: shutil.rmtree(restored, ignore_errors=True))
        maintenance.restore(self.store, backup, restored)
        self.assertEqual(hashlib.sha256((restored / short["ref"]).read_bytes()).hexdigest(), short["hash"])
        record["segments"][-1]["end_sec"] = 93
        self.save_record(record)
        self.assertTrue(self.client.get(self.endpoint + "/preprocess").json()["outdated"])
        self.store.path(again["clips"][0]["ref"]).write_bytes(b"broken-clip")
        state = self.client.get(self.endpoint + "/preprocess").json()
        self.assertEqual(state["status"], "failed")
        self.assertTrue(state["ready"])
        self.assertIsNone(state["result"])
        self.assertIn("다시 전처리", state["message"])
        def retry_status_during_cut(*args):
            original_cut(*args)
            running = self.client.get(self.endpoint + "/preprocess").json()
            self.assertEqual(running["status"], "running")
            self.assertIsNone(running["result"])
        original_cut = cut_clip
        with patch("app.preprocess_v3.cut_clip", side_effect=retry_status_during_cut):
            recovery = self.run_preprocess()
        self.assertNotEqual(recovery["batch_id"], again["batch_id"])

    def test_no_audio_is_availability_zero_not_vocal_zero(self):
        no_audio = Path(self.media.name) / "no-audio.mp4"
        if not no_audio.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(self.source), "-an", "-c:v", "copy", str(no_audio)], check=True, capture_output=True)
        self.item = self.upload(self.item, no_audio.read_bytes(), "no-audio.mp4").json()
        self.video = self.item["manifest"]["sessions"][0]["videos"][-1]
        self.save_record(self.recording())
        result = self.run_preprocess()
        self.assertEqual(result["source_audio"], "absent")
        self.assertTrue(all(clip["audio_available_seconds"] == 0 and clip["vocal_seconds"] is None for clip in result["clips"]))

    def test_synchronized_other_camera_damage_does_not_reduce_reference_audio(self):
        other_source = Path(self.media.name) / "other-camera.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(self.source), "-c", "copy",
                        "-metadata", "comment=second-camera", str(other_source)], check=True, capture_output=True)
        response = self.upload(self.item, other_source.read_bytes(), "other-camera.mp4")
        self.assertEqual(response.status_code, 201, response.text)
        self.item = response.json()
        other = self.item["manifest"]["sessions"][0]["videos"][-1]
        record = self.recording()
        record["video_offsets"] = [{"video_id": other["video_id"], "offset_seconds": 5,
                                    "confirmed": True, "note": "합성 영상 동일 사건 수동 시각 대응"}]
        record["events"] = [self.event("audio_loss", 77, end_seconds=78, video_id=other["video_id"]),
                            self.event("occlusion", 78, end_seconds=79, video_id=other["video_id"])]
        self.save_record(record)
        result = self.run_preprocess()
        full = next(clip for clip in result["clips"] if "stranger" in clip["window_ids"])
        self.assertEqual(full["audio_available_seconds"], 10)
        self.assertEqual(full["quality_events"], [])
        self.assertEqual(len(result["recording"]["events"]), 2)

    def test_subframe_contact_does_not_include_later_frame_or_stop_other_windows(self):
        record = self.recording()
        record["events"] = [self.event("stranger_contact_start", 74.001), self.event("stranger_contact_end", 74.002),
                            self.event("stranger_contact_start", None, status="not_occurred", event_id="other-no-contact")]
        self.save_record(record)
        result = self.run_preprocess()
        window = next(window for window in result["windows"] if window["window_id"] == "stranger_contact")
        self.assertEqual((window["start_sec"], window["end_sec"]), (74.001, 74.002))
        self.assertEqual(window["status"], "unobserved")
        self.assertEqual(window["clip_names"], [])
        self.assertIn("프레임", window["reason"])
        self.assertTrue(any("stranger" in clip["window_ids"] for clip in result["clips"]))
        self.assertEqual(next(window for window in result["windows"] if window["window_id"] == "stranger_no_contact")["status"], "unobserved")

    def test_failure_revision_deletion_and_policy_change_never_adopt_partial_batch(self):
        self.save_record(self.recording())
        original = cut_clip
        def revision_during_cut(*args):
            original(*args)
            response = self.client.put(f"/api/cases/{self.item['case_id']}", json={
                "expected_revision": self.item["input_revision"], "participant_id": self.item["participant_id"], "dog_name": "수정견"})
            self.assertEqual(response.status_code, 200)
            self.item = response.json()
        with patch("app.preprocess_v3.cut_clip", side_effect=revision_during_cut):
            self.assertEqual(self.client.post(self.endpoint + "/preprocess", json={"expected_revision": self.item["input_revision"]}).status_code, 409)
        state = self.client.get(self.endpoint + "/preprocess").json()
        self.assertEqual(state["status"], "failed")
        self.assertIsNone(state["result"])
        with patch("app.preprocess_v3.verify_assets", side_effect=HTTPException(409, "규칙 변경")):
            self.assertEqual(self.client.post(self.endpoint + "/preprocess", json={"expected_revision": self.item["input_revision"]}).status_code, 409)
        def deleted(*args):
            original(*args)
            self.delete_case(self.item)
        with patch("app.preprocess_v3.cut_clip", side_effect=deleted):
            self.assertEqual(self.client.post(self.endpoint + "/preprocess", json={"expected_revision": self.item["input_revision"]}).status_code, 403)
        with self.store.connect() as db:
            self.assertIsNone(preprocess.latest(self.store, db, self.item["case_id"], self.item["selected_session_id"]))

    def test_asset_hash_change_requires_restart_and_audio_ranges_handle_late_start(self):
        copied = self.root / "rules.json"
        copied.write_bytes(preprocess_v3.RULE_PATH.read_bytes())
        with patch("app.preprocess_v3.RULE_PATH", copied):
            preprocess_v3.verify_assets()
            copied.write_bytes(b"changed")
            with self.assertRaises(HTTPException):
                preprocess_v3.verify_assets()
        self.assertEqual(preprocess_v3.union_duration([(1, 3), (2, 4), (5, 6)]), 4)
        from app.media import probe as media_probe
        metadata = {"format": {"duration": "10"}, "streams": [{"codec_type": "video", "width": 96, "height": 64, "avg_frame_rate": "12/1"},
                    {"codec_type": "audio", "start_time": "3", "duration": "4"}]}
        with patch("app.media.command", return_value=json.dumps(metadata)):
            self.assertEqual(media_probe(self.source)["audio_ranges"], [{"start_sec": 3, "end_sec": 7, "basis": "stream_metadata"}])
