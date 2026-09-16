"""Preprocessing: confirmed segments of the reference file become hashed clips at dense/sparse frame rates (synthetic FFmpeg media)."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app import maintenance, preprocess
from app.media import MediaError, cut_clip, probe
from tests.support import AppCase

ORDER = ["entry", "baseline", "alone", "stranger", "reunion", "ignore", "walk", "exit"]
# Eight windows inside a 45-second synthetic recording; the 입장 window is shorter than the 5-second dense window.
WINDOWS = [(0.0, 3.0), (3.0, 8.0), (8.0, 15.0), (15.0, 22.0), (22.0, 30.0), (30.0, 35.0), (35.0, 42.0), (42.0, 45.0)]


def synthetic_video(path: Path, seconds=45):
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True, timeout=120)


def stream_stats(path: Path):
    raw = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], check=True, capture_output=True, timeout=60).stdout
    data = json.loads(raw)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    numerator, denominator = video["avg_frame_rate"].split("/")
    return {"duration": float(data["format"]["duration"]), "fps": round(int(numerator) / int(denominator), 1),
            "audio": any(s["codec_type"] == "audio" for s in data["streams"]), "width": video["width"], "height": video["height"]}


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for preprocessing tests")
class PreprocessTests(AppCase):
    def setUp(self):
        super().setUp()
        self.temp_media = tempfile.TemporaryDirectory(prefix="kdog-media-")
        self.addCleanup(self.temp_media.cleanup)
        self.source = Path(self.temp_media.name) / "reference.mp4"
        synthetic_video(self.source)
        self.item = self.upload(self.make_case(), self.source.read_bytes(), "reference.mp4").json()
        self.session = self.item["manifest"]["sessions"][0]
        self.video_id = self.session["videos"][0]["video_id"]

    def segments(self, windows=WINDOWS, confirm=True, expected=None):
        response = self.client.put(f"/api/cases/{self.item['case_id']}/sessions/{self.session['session_id']}/segments", json={
            "expected_revision": expected or self.item["input_revision"], "video_id": self.video_id, "confirm": confirm,
            "windows": [{"segment": name, "start_sec": start, "end_sec": end} for name, (start, end) in zip(ORDER, windows)]})
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()
        return self.item

    def test_probe_and_cut_clip_keep_audio_and_apply_frame_rate(self):
        info = probe(self.source)
        self.assertEqual((info["width"], info["height"], info["audio_status"]), (320, 240, "present"))
        self.assertAlmostEqual(info["duration_sec"], 45.0, delta=0.5)
        target = Path(self.temp_media.name) / "clip.mp4"
        cut_clip(self.source, target, 8.0, 13.0, 8, {**preprocess.RULES, "scale_height": 120})
        stats = stream_stats(target)
        self.assertAlmostEqual(stats["duration"], 5.0, delta=0.3)
        self.assertEqual((stats["fps"], stats["audio"], stats["height"]), (8.0, True, 120))
        with self.assertRaises(MediaError):
            cut_clip(self.source, Path(self.temp_media.name) / "empty.mp4", 5.0, 5.0, 8, preprocess.RULES)
        with self.assertRaises(MediaError):
            probe(Path(self.temp_media.name) / "missing.mp4")

    def test_plan_splits_stimulus_segments_into_dense_then_sparse(self):
        self.segments()
        from app.input_models import Manifest
        manifest = Manifest.model_validate(self.item["manifest"])
        clips = preprocess.plan(manifest.sessions[0])
        names = [c["name"] for c in clips]
        self.assertEqual(names, ["entry-dense", "baseline-sparse", "alone-dense", "alone-sparse", "stranger-dense", "stranger-sparse",
                                 "reunion-dense", "reunion-sparse", "ignore-sparse", "walk-sparse", "exit-sparse"])
        by_name = {c["name"]: c for c in clips}
        self.assertEqual((by_name["entry-dense"]["start_sec"], by_name["entry-dense"]["end_sec"], by_name["entry-dense"]["fps"]), (0.0, 3.0, 8))
        self.assertEqual((by_name["alone-dense"]["end_sec"], by_name["alone-sparse"]["start_sec"], by_name["alone-sparse"]["fps"]), (13.0, 13.0, 2))
        unconfirmed = manifest.sessions[0].model_copy(update={"segments": manifest.sessions[0].segments.model_copy(update={"confirmed": False})})
        with self.assertRaises(HTTPException):
            preprocess.plan(unconfirmed)

    def test_run_writes_hashed_clips_recorded_for_backup_and_cleanup(self):
        self.segments()
        result = preprocess.run(self.store, self.item["case_id"], self.session["session_id"], "operator")
        self.assertEqual((result["rules_version"], len(result["clips"]), result["source_sha256"]), ("preprocess-v1", 11, self.session["videos"][0]["sha256"]))
        for clip in result["clips"]:
            path = self.store.path(clip["ref"])
            self.assertTrue(clip["ref"].startswith(f"clips/{self.item['case_id']}/"))
            with path.open("rb") as handle:
                self.assertEqual(hashlib.file_digest(handle, "sha256").hexdigest(), clip["hash"])
            stats = stream_stats(path)
            self.assertAlmostEqual(stats["duration"], clip["end_sec"] - clip["start_sec"], delta=0.35, msg=clip["name"])
            self.assertEqual(stats["fps"], float(clip["fps"]), clip["name"])
            self.assertTrue(stats["audio"], clip["name"])
        with self.store.connect() as db:
            recorded = preprocess.latest(self.store, db, self.item["case_id"], self.session["session_id"])
            refs = maintenance.references(self.store, db)
        self.assertEqual(recorded["clips"], result["clips"])
        self.assertTrue(all(clip["ref"] in refs for clip in result["clips"]))
        orphan = self.store.path(f"clips/{self.item['case_id']}/orphan.mp4")
        orphan.write_bytes(b"orphan")
        maintenance.clean(self.store)
        self.assertFalse(orphan.exists())
        self.assertTrue(all(self.store.path(clip["ref"]).exists() for clip in result["clips"]))
        # Editing the segments makes a new batch; the old clips stay referenced by their own record.
        self.segments([(s, e) for s, e in WINDOWS[:-1]] + [(42.0, 44.0)], expected=self.item["input_revision"])
        again = preprocess.run(self.store, self.item["case_id"], self.session["session_id"], "operator")
        self.assertNotEqual(again["clips"][0]["ref"], result["clips"][0]["ref"])
        with self.store.connect() as db:
            self.assertEqual(preprocess.latest(self.store, db, self.item["case_id"], self.session["session_id"])["clips"], again["clips"])
            self.assertEqual(len(maintenance.references(self.store, db)), len(refs) + len(again["clips"]) + 1)

    def test_run_refuses_unconfirmed_segments_and_windows_beyond_the_recording(self):
        with self.assertRaises(HTTPException) as unconfirmed:
            preprocess.run(self.store, self.item["case_id"], self.session["session_id"], "operator")
        self.assertEqual(unconfirmed.exception.status_code, 409)
        self.segments([(s, e) for s, e in WINDOWS[:-1]] + [(42.0, 70.0)])
        with self.assertRaises(HTTPException) as too_long:
            preprocess.run(self.store, self.item["case_id"], self.session["session_id"], "operator")
        self.assertEqual(too_long.exception.status_code, 422)
        self.assertFalse(list(self.store.path("clips").rglob("*.mp4")) if self.store.path("clips").exists() else [])

    def test_cli_runs_preprocessing_with_an_active_operator(self):
        import sys
        self.segments()
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "app.manage", "--data-dir", str(self.root), "preprocess", self.item["case_id"], "--actor", "operator"],
                        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8", timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual((summary["clips"], summary["video_id"]), (11, self.video_id))
        denied = subprocess.run([sys.executable, "-X", "utf8", "-m", "app.manage", "--data-dir", str(self.root), "preprocess", self.item["case_id"], "--actor", "reviewer"],
                        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertNotEqual(denied.returncode, 0)


if __name__ == "__main__":
    unittest.main()
