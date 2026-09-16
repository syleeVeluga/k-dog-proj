"""Preprocessing: confirmed segments of the reference file become hashed clips at dense/sparse frame rates (synthetic FFmpeg media)."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi import HTTPException

from app import maintenance, preprocess
from app.media import MediaError, cut_clip, probe
from tests.support import AppCase, PASSWORD

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
        # Old stored confirmations with empty windows must never become successful zero-clip batches.
        for empty_indices in ([0], list(range(8))):
            damaged = manifest.sessions[0].model_copy(deep=True)
            for index in empty_indices:
                damaged.segments.windows[index].end_sec = damaged.segments.windows[index].start_sec
            with self.assertRaises(HTTPException) as rejected:
                preprocess.plan(damaged)
            self.assertEqual(rejected.exception.status_code, 422)

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

    def test_manual_request_permissions_failure_interruption_and_lock(self):
        path = f"/api/cases/{self.item['case_id']}/sessions/{self.session['session_id']}/preprocess"
        self.assertEqual(self.client.get(path).json()["status"], "not_ready")
        self.assertEqual(self.client.post(path, json={"expected_revision": self.item["input_revision"]}).status_code, 409)
        self.segments()
        revision = {"expected_revision": self.item["input_revision"]}
        reviewer = self.client_for("reviewer")
        self.assertEqual(reviewer.get(path).json()["status"], "ready")
        self.assertEqual(reviewer.post(path, json=revision).status_code, 403)
        with maintenance.runtime_lock(self.store, "preprocess"):
            self.assertEqual(self.client.post(path, json=revision).status_code, 409)
            with self.assertRaises(HTTPException):
                maintenance.clean(self.store)
        with patch("app.preprocess.cut_clip", side_effect=MediaError("synthetic failure")):
            self.assertEqual(self.client.post(path, json=revision).status_code, 422)
        failed = self.client.get(path).json()
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["result"])
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", self.item["case_id"], "preprocess.started", {
                "request_id": "interrupted-test", "session_id": self.session["session_id"], "input_revision": self.item["input_revision"]})
        with maintenance.runtime_lock(self.store, "preprocess"):
            self.assertEqual(self.client.get(path).json()["status"], "running")
        self.assertEqual(self.client.get(path).json()["status"], "interrupted")

    def test_stimulus_times_are_explicit_versioned_and_do_not_define_windows(self):
        self.segments()
        path = f"/api/cases/{self.item['case_id']}/sessions/{self.session['session_id']}/stimuli"
        self.assertIsNone(self.item["manifest"]["sessions"][0]["stimuli"])
        payload = {"expected_revision": self.item["input_revision"], "video_id": self.video_id,
                   "moments": {"entry": 0.0, "alone": None, "stranger": 15.0, "reunion": 30.0}}
        self.assertEqual(self.client_for("reviewer").put(path, json=payload).status_code, 403)
        self.assertEqual(self.client.put(path, json={**payload, "video_id": "unknown"}).status_code, 422)
        for invalid in (-1.0, 46.0, "NaN"):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.client.put(path, json={**payload, "moments": {"reunion": invalid}}).status_code, 422)
        saved = self.client.put(path, json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.item = saved.json()
        stored = self.item["manifest"]["sessions"][0]["stimuli"]
        self.assertEqual((stored["video_id"], stored["input_revision"], stored["source"]),
                         (self.video_id, self.item["input_revision"], "operator_confirmed"))
        self.assertEqual(stored["moments"]["reunion"], 30.0)  # 8 seconds after reunion segment start.
        self.assertIsNone(stored["moments"]["alone"])
        self.assertEqual(self.client.put(path, json=payload).status_code, 409)
        with self.store.connect() as db:
            self.assertIsNone(preprocess.latest(self.store, db, self.item["case_id"], self.session["session_id"]))
        # The unconfirmed placement rule must NOT pretend to use the recorded event.
        from app.input_models import Manifest
        clips = preprocess.plan(Manifest.model_validate(self.item["manifest"]).sessions[0])
        self.assertEqual(next(c["start_sec"] for c in clips if c["name"] == "reunion-dense"), 22.0)
        # Existing manifests need no fabricated timing during upgrade/read.
        old = json.loads(json.dumps(self.item["manifest"]))
        del old["sessions"][0]["stimuli"]
        self.assertIsNone(Manifest.model_validate(old).sessions[0].stimuli)
        self.delete_case(self.item)
        self.assertEqual(self.client.put(path, json={**payload, "expected_revision": self.item["input_revision"]}).status_code, 403)

    def test_changed_or_deleted_input_during_cut_never_publishes_success(self):
        self.segments()
        path = f"/api/cases/{self.item['case_id']}/sessions/{self.session['session_id']}/preprocess"
        for action in ("edit", "delete"):
            changed = False
            def cut_and_change(*args):
                nonlocal changed
                cut_clip(*args)
                if not changed:
                    changed = True
                    if action == "edit":
                        self.segments(WINDOWS[:-1] + [(42.0, 44.0)])
                    else:
                        self.delete_case(self.item)
            with patch("app.preprocess.cut_clip", side_effect=cut_and_change):
                response = self.client.post(path, json={"expected_revision": self.item["input_revision"]})
            self.assertEqual(response.status_code, 409 if action == "edit" else 403, response.text)
            with self.store.connect() as db:
                self.assertIsNone(preprocess.latest(self.store, db, self.item["case_id"], self.session["session_id"]))

    def test_real_launcher_worker_and_manual_preprocess_coexist(self):
        import threading
        import httpx
        from app.launcher import launch
        from tests.test_packaging import free_port
        self.segments()
        port, stop = free_port(), threading.Event()
        path = f"/api/cases/{self.item['case_id']}/sessions/{self.session['session_id']}/preprocess"
        def ready(_children):
            try:
                with maintenance.runtime_lock(self.store, "worker"):
                    self.fail("launcher worker must hold its lock")
            except HTTPException:
                pass
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"X-KDOG-Request": "1"}, timeout=120, trust_env=False) as client:
                self.assertEqual(client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD}).status_code, 200)
                self.assertIsNone(client.get(path).json()["result"])
                response = client.post(path, json={"expected_revision": self.item["input_revision"]})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual((result["status"], len(result["result"]["clips"]), result["outdated"]), ("complete", 11, False))
                first = result["result"]["clips"][0]["ref"]
                again = client.post(path, json={"expected_revision": self.item["input_revision"]}).json()
                self.assertNotEqual(first, again["result"]["clips"][0]["ref"])
                self.client = client
                self.segments(WINDOWS[:-1] + [(42.0, 44.0)])
                self.assertTrue(client.get(path).json()["outdated"])
                self.assertEqual(client.post(path, json={"expected_revision": self.item["input_revision"] - 1}).status_code, 409)
            stop.set()
        launch(self.root, port, open_browser=False, stop_event=stop, ready=ready)


if __name__ == "__main__":
    unittest.main()
