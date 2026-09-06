"""Synthetic provider/transport tests; generated color clips only, no real AI calls."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.analysis import adopt, claim, later, validated_prepared, write_output
from app.api import create_app
from app.auth import create_user
from app.gemini import BASE, GeminiObserver, ProviderError, request
from app.input_models import StoredVideo, UserCreate
from app.media import MediaError, inspect_media
from app.observation_models import MediaInfo, ObservationResponse
from app.storage import Store, encode, now, uid
from app.worker import Worker
from tests.evaluation_fixtures import FakeEvaluator


def fake_probe(path, video, prepared_path, prepared_ref):
    return MediaInfo(video_id=video.video_id, storage_ref=video.storage_ref, sha256=video.sha256,
                     size_bytes=video.size_bytes, duration_sec=4.0, codec="h264", width=320, height=240,
                     audio_status="absent", mime_type="video/mp4", quality_flags=["audio_absent"])


def response(*, end=2.0, modality="video"):
    return ObservationResponse.model_validate({"observations": [{
        "segment_id": "entry", "start_sec": 1.0, "end_sec": end, "subject": "dog", "modality": modality,
        "observation": "가상 관찰: 입장 시 이동", "candidate_item_ids": ["BS-01"], "quality_flags": [],
    }], "unconfirmed_conditions": ["synthetic_test_only"]})


class FakeObserver:
    def __init__(self):
        self.calls = []
        self.callback = None

    def observe(self, path, media, config, context, guard):
        guard()
        self.calls.append(media.video_id)
        if self.callback:
            return self.callback(media, guard)
        return response(), {"model": "synthetic-test-only", "totalTokenCount": 10}


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kdog-m2-test-")
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"KDOG_GEMINI_MODEL": "gemini-test-only", "GEMINI_API_KEY": "synthetic-secret-only"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = create_app(Path(self.temp.name))
        self.store = self.app.state.store
        with self.store.connect(write=True) as db:
            for role in ("operator", "reviewer", "developer"):
                create_user(db, UserCreate(username=role, role=role, password="Synthetic-test-only-42"))
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8000", headers={"X-KDOG-Request": "1"})
        self.addCleanup(self.client.close)
        self.login("operator")
        self.item = self.client.post("/api/cases", json={"event_id": "M2", "participant_id": "0001", "dog_name": "가상견"}).json()
        self.base = f"/api/cases/{self.item['case_id']}"
        self.access()
        for index in range(2):
            result = self.client.post(self.base + "/videos", content=f"synthetic {index}".encode(), params={
                "session_id": self.item["selected_session_id"], "camera_id": f"CAM-{index}", "filename": f"camera{index}.mp4",
                "expected_revision": self.item["input_revision"]})
            self.assertEqual(result.status_code, 201, result.text)
            self.item = result.json()
        self.observer = FakeObserver()
        self.worker = Worker(self.store, observer=self.observer, evaluator=FakeEvaluator(), probe=fake_probe)

    def login(self, role):
        self.assertEqual(self.client.post("/api/auth/login", json={"username": role, "password": "Synthetic-test-only-42"}).status_code, 200)

    def access(self, granted=True, delete=False):
        result = self.client.put(self.base + "/access", json={"expected_revision": self.item["input_revision"],
            "deletion_requested": delete, "consent": {"video_analysis": granted, "external_ai": granted,
                "result_provision": granted, "text_version": "synthetic", "recorded_at": "2026-09-06T00:00:00+00:00"}})
        self.assertEqual(result.status_code, 200, result.text)
        if not delete:
            self.item = self.client.get(self.base).json()

    def start(self, **kwargs):
        result = self.client.post(self.base + "/analysis", json={"expected_revision": self.item["input_revision"], **kwargs})
        self.assertEqual(result.status_code, 202, result.text)
        return result.json()["runs"][0]["run_id"]

    def view(self):
        result = self.client.get(self.base + "/analysis")
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["runs"][0]

    def ready_retries(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET retry_at=? WHERE status='retry_wait'", (later(-1),))

    def test_two_cameras_partial_read_restart_and_deduplicate_click(self):
        run_id = self.start()
        self.assertEqual(self.start(), run_id)
        def inspect_partial(media, guard):
            if len(self.observer.calls) == 2:
                self.assertEqual(len(self.view()["evidence"]), 1)
            return response(), {"model": "synthetic-test-only"}
        self.observer.callback = inspect_partial
        self.assertTrue(self.worker.once())
        self.assertEqual(self.view()["status"], "scored")
        evidence = self.view()["evidence"]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(len({e["evidence_id"] for e in evidence}), 2)
        self.assertTrue(all(e["event_group_id"] is None for e in evidence))
        self.assertFalse(Worker(Store(self.store.root), observer=self.observer, probe=fake_probe).once())
        self.assertEqual(len(self.observer.calls), 2)
        self.assertEqual(self.client.get(self.base).json()["analysis_status"], "scored")

    def test_invalid_time_and_silent_audio_have_one_repair_and_three_total_limit(self):
        self.start()
        self.observer.callback = lambda media, guard: (response(end=9.0, modality="audio"), {"totalTokenCount": 5})
        self.worker.once()
        self.assertEqual(self.view()["status"], "retry_wait")
        self.assertEqual(self.view()["evidence"], [])
        self.ready_retries()
        self.worker.once()
        self.assertEqual(self.view()["status"], "partial_failed")
        self.assertEqual(len(self.observer.calls), 4)
        self.assertTrue(all(s["usage"].get("totalTokenCount") == 5 for s in self.view()["steps"] if s["stage"] == "observe"))

    def test_retry_preserves_success_and_respects_retry_after(self):
        self.start()
        def flaky(media, guard):
            if media.video_id == self.item["manifest"]["sessions"][0]["videos"][1]["video_id"]:
                raise ProviderError("provider_http_429", retryable=True, delay=120)
            return response(), {}
        self.observer.callback = flaky
        self.worker.once()
        self.assertEqual(len(self.view()["evidence"]), 1)
        self.assertFalse(self.worker.once())
        self.ready_retries()
        self.observer.callback = None
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        self.assertEqual(len(self.observer.calls), 3)

    def test_other_camera_retry_does_not_repeat_permanent_failure(self):
        run_id = self.start()
        first = self.item["manifest"]["sessions"][0]["videos"][0]["video_id"]
        def errors(media, guard):
            raise ProviderError("provider_http_400" if media.video_id == first else "provider_http_429", retryable=media.video_id != first)
        self.observer.callback = errors
        self.worker.once()
        self.ready_retries()
        self.observer.callback = None
        self.worker.once()
        self.assertEqual(self.observer.calls.count(first), 1)
        self.assertEqual(self.view()["status"], "partial_failed")
        self.assertEqual(self.client.post(self.base + f"/analysis/{run_id}/retry").status_code, 200)
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")

    def test_queued_withdrawal_and_inflight_deletion_fence_late_results(self):
        self.start()
        self.access(False)
        self.assertFalse(self.worker.once())
        self.assertEqual(len(self.observer.calls), 0)
        self.access()
        self.start()
        def delete_inflight(media, guard):
            self.access(delete=True)
            return response(), {}
        self.observer.callback = delete_inflight
        self.worker.once()
        self.assertEqual(len(self.observer.calls), 1)
        self.assertEqual(self.client.get(self.base + "/analysis").status_code, 403)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM steps WHERE stage='observe' AND status='succeeded'").fetchone()[0], 0)

    def test_missing_key_never_falls_back_and_roles_are_enforced(self):
        run_id = self.start()
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            Worker(self.store, probe=fake_probe).once()
        self.assertEqual(self.view()["status"], "settings_required")
        self.assertEqual(len([s for s in self.view()["steps"] if s["stage"] == "observe"]), 1)
        self.login("reviewer")
        self.assertEqual(self.client.post(self.base + "/analysis", json={"expected_revision": self.item["input_revision"]}).status_code, 403)
        self.assertEqual(self.client.get(self.base + "/analysis").status_code, 200)
        self.login("developer")
        self.assertEqual(self.client.get(self.base + "/analysis").status_code, 403)
        self.assertNotIn("synthetic-secret-only", self.store.path("kdog.sqlite3").read_bytes().decode("utf-8", errors="ignore"))

    def test_evidence_video_uses_checked_run_and_blocks_withdrawal(self):
        run_id = self.start()
        self.worker.once()
        video_id = self.view()["evidence"][0]["video_id"]
        url = self.base + f"/analysis/{run_id}/videos/{video_id}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(self.base + f"/analysis/{run_id}/videos/unknown").status_code, 404)
        self.access(False)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_survey_only_explicit_reuse_and_wrong_video_session_rejected(self):
        run_id = self.start()
        self.worker.once()
        evidence = self.view()["evidence"]
        session = self.item["manifest"]["sessions"][0]
        saved = self.client.put(self.base + "/survey", json={"expected_revision": self.item["input_revision"],
            "session_id": session["session_id"], "survey_version": session["survey_version"],
            "answers": {f"q{i:02}": 3 for i in range(1, 31)}})
        self.item = saved.json()
        self.start(reuse_run_id=run_id)
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        self.assertEqual(self.view()["evidence"], evidence)
        self.assertEqual(len(self.observer.calls), 2)
        self.assertEqual(self.view()["reused_from"], [run_id])
        saved = self.client.put(self.base + f"/sessions/{session['session_id']}", json={"expected_revision": self.item["input_revision"],
            "capture_mode": "sequential", "route_note": "changed"})
        self.item = saved.json()
        self.assertEqual(self.client.post(self.base + "/analysis", json={"expected_revision": self.item["input_revision"], "reuse_run_id": run_id}).status_code, 409)

    def test_expired_worker_cannot_replace_new_attempt_and_orphan_recovers(self):
        run_id = self.start()
        old = claim(self.store)
        # Persist prepare output, simulating a crash immediately before DB adoption.
        step = {"step_id": uid(), "claim_token": old["claim_token"], "attempt": 1}
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,created_at,updated_at) "
                       "VALUES(?,?,'prepare','session',1,'running',?,?,?)", (step["step_id"], run_id, old["claim_token"], now(), now()))
        payload = self.worker.prepare(old, step)
        ref, sha = write_output(self.store, old, step, payload)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at=? WHERE run_id=?", (later(-1), run_id))
        self.worker.once()
        self.assertEqual(self.view()["status"], "scored")
        self.assertEqual(len([s for s in self.view()["steps"] if s["stage"] == "prepare"]), 1)
        with self.assertRaises(HTTPException):
            adopt(self.store, old, step, ref, sha, {})
        with self.assertRaises(FileExistsError):
            write_output(self.store, old, step, {"tampered": True})
        self.assertEqual(self.view()["status"], "scored")

    def test_corrupt_success_never_reused_or_recalled_implicitly(self):
        self.start()
        self.worker.once()
        with self.store.connect() as db:
            ref = db.execute("SELECT output_ref FROM steps WHERE stage='observe' LIMIT 1").fetchone()[0]
        self.store.path(ref).write_text("{}", encoding="utf-8")
        self.assertEqual(self.client.get(self.base + "/analysis").status_code, 409)
        self.assertEqual(len(self.observer.calls), 2)

    def test_late_a_output_after_b_success_does_not_change_adopted_evidence(self):
        run_id = self.start()
        old = claim(self.store)
        prepared = self.worker.stage(old, "prepare", "session", lambda p: validated_prepared(old, p),
                                     lambda step: self.worker.prepare(old, step))
        info = prepared.media[0]
        step = {"step_id": uid(), "claim_token": old["claim_token"], "attempt": 1}
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,created_at,updated_at) "
                       "VALUES(?,?,'observe',?,1,'running',?,?,?)", (step["step_id"], run_id, info.video_id, old["claim_token"], now(), now()))
        delayed = self.worker.observe(old, step, prepared, info)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET lease_expires_at=? WHERE run_id=?", (later(-1), run_id))
        self.worker.once()
        before = self.view()
        self.assertEqual(before["status"], "scored")
        ref, sha = write_output(self.store, old, step, delayed)
        with self.assertRaises(HTTPException):
            adopt(self.store, old, step, ref, sha, {})
        self.assertEqual(self.view()["evidence"], before["evidence"])
        self.assertNotIn(delayed["evidence"][0]["evidence_id"], [e["evidence_id"] for e in before["evidence"]])

    def test_older_run_completion_does_not_replace_new_input_display(self):
        old_id = self.start()
        old = claim(self.store)
        session = self.item["manifest"]["sessions"][0]
        self.item = self.client.put(self.base + "/survey", json={"expected_revision": self.item["input_revision"],
            "session_id": session["session_id"], "survey_version": session["survey_version"],
            "answers": {f"q{i:02}": 4 for i in range(1, 31)}}).json()
        new_id = self.start()
        self.worker.once()
        with patch.dict(os.environ, {"KDOG_GEMINI_MODEL": "gemini-changed-after-queue"}):
            self.worker.process(old)
        result = self.client.get(self.base + "/analysis").json()
        self.assertEqual(next(r for r in result["runs"] if r["is_current"])["run_id"], new_id)
        with self.store.connect() as db:
            frozen = json.loads(db.execute("SELECT config_snapshot_json FROM runs WHERE run_id=?", (old_id,)).fetchone()[0])
            self.assertEqual(frozen["model"], "gemini-test-only")
            self.assertTrue(db.execute("SELECT result_ref FROM runs WHERE run_id=?", (new_id,)).fetchone()[0])

    def test_transport_retry_budget_and_cancel(self):
        run_id = self.start()
        self.observer.callback = lambda media, guard: (_ for _ in ()).throw(ProviderError("provider_connection_lost", retryable=True, uncertain=True))
        for attempt in range(3):
            self.ready_retries()
            self.worker.once()
        self.assertEqual(len(self.observer.calls), 6)
        self.assertEqual(self.view()["status"], "partial_failed")
        self.assertEqual(self.client.post(self.base + f"/analysis/{run_id}/retry").status_code, 409)
        next_id = self.start()
        self.assertEqual(self.client.post(self.base + f"/analysis/{next_id}/cancel").status_code, 200)
        self.assertFalse(self.worker.once())

    def test_cross_case_and_retake_reuse_rejected(self):
        source = self.start()
        self.worker.once()
        other = self.client.post("/api/cases", json={"event_id": "M2", "participant_id": "0002", "dog_name": "가상견"}).json()
        with self.store.connect(write=True) as db:
            # Keep otherwise valid source metadata but attach a different case.
            fake = uid()
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (source,)).fetchone()
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'observed',?,?)",
                       (fake, other["case_id"], row["session_id"], row["input_revision"], row["input_snapshot_json"], row["config_snapshot_json"], now(), now()))
        self.assertEqual(self.client.post(self.base + "/analysis", json={"expected_revision": self.item["input_revision"], "reuse_run_id": fake}).status_code, 409)
        self.item = self.client.post(self.base + "/sessions", json={"expected_revision": self.item["input_revision"]}).json()
        self.assertEqual(self.client.post(self.base + "/analysis", json={"expected_revision": self.item["input_revision"], "reuse_run_id": source}).status_code, 422)


class MediaTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe not installed")
    def test_generated_silent_and_audio_clips_preserve_source_and_reject_damage(self):
        with tempfile.TemporaryDirectory(prefix="kdog-media-test-") as temp:
            root = Path(temp)
            for audio in (False, True):
                path = root / ("audio.mkv" if audio else "silent.mp4")
                args = ["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1"]
                if audio:
                    args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "pcm_s16le"]
                subprocess.run(args + ["-c:v", "libx264", "-t", "1", str(path)], check=True, capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                original = path.read_bytes()
                video = StoredVideo(video_id="v1", camera_id="c1", original_name=path.name, storage_ref="original/" + path.name,
                                    sha256=hashlib.sha256(original).hexdigest(), size_bytes=len(original))
                info = inspect_media(path, video, root / "prepared.mp4", "prepared.mp4")
                self.assertEqual(info.audio_status, "present" if audio else "absent")
                self.assertEqual(path.read_bytes(), original)
                if audio:
                    streams = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(root / "prepared.mp4")]))
                    self.assertTrue(any(s["codec_type"] == "audio" for s in streams["streams"]))
                path.write_bytes(b"damaged")
                with self.assertRaises(MediaError):
                    inspect_media(path, video, root / "unused.mp4", "unused.mp4")


class GeminiTests(unittest.TestCase):
    def test_http_failures_are_sanitized_and_off_origin_upload_rejected(self):
        for error, code, retryable in [
            (HTTPError(BASE, 401, "secret-test", {}, None), "developer_settings_required", False),
            (HTTPError(BASE, 429, "secret-test", {"Retry-After": "75"}, None), "provider_http_429", True),
            (URLError("secret-test"), "provider_connection_lost", True),
        ]:
            opener = MagicMock()
            opener.open.side_effect = error
            with patch("app.gemini.build_opener", return_value=opener):
                with self.assertRaises(ProviderError) as caught:
                    request("POST", BASE + "/test", "secret-test", data={})
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.retryable, retryable)
            self.assertNotIn("secret-test", str(caught.exception))
            if code == "provider_http_429":
                self.assertEqual(caught.exception.delay, 75)
        with self.assertRaises(ProviderError):
            request("POST", "https://example.com/upload", "secret-test")

    def test_upload_poll_generate_delete_and_guard_each_request(self):
        media = fake_probe(None, StoredVideo(video_id="v", camera_id="c", original_name="x.mp4",
                           storage_ref="x.mp4", sha256="a" * 64, size_bytes=4), None, None)
        calls, guards = [], []
        def transport(method, url, key, **kwargs):
            calls.append((method, url, kwargs))
            if "upload/v1beta" in url:
                return {}, {"X-Goog-Upload-URL": BASE + "/upload-session"}
            if "upload-session" in url:
                return {"file": {"name": "files/f1", "state": "PROCESSING"}}, {}
            if method == "GET":
                return {"name": "files/f1", "state": "ACTIVE", "uri": BASE + "/v1beta/files/f1"}, {}
            if method == "DELETE":
                return {}, {}
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": response().model_dump_json()}]}}],
                    "usageMetadata": {"totalTokenCount": 12}, "modelVersion": "gemini-test", "responseId": "test-id"}, {}
        with tempfile.TemporaryDirectory(prefix="kdog-gemini-test-") as temp:
            path = Path(temp) / "test.mp4"
            path.write_bytes(b"fake")
            from app.gemini import configuration
            with patch.dict(os.environ, {"GEMINI_API_KEY": "secret-test", "KDOG_GEMINI_MODEL": "gemini-test"}), patch("app.gemini.request", side_effect=transport), patch("app.gemini.time.sleep"):
                parsed, usage = GeminiObserver().observe(path, media, configuration(), {"items": []}, lambda: guards.append(True))
        self.assertEqual(len(parsed.observations), 1)
        self.assertEqual(usage["totalTokenCount"], 12)
        self.assertEqual(calls[-1][0], "DELETE")
        self.assertGreaterEqual(len(guards), 5)
        generated = next(c for c in calls if "generateContent" in c[1])
        self.assertNotIn("secret-test", json.dumps(generated[2]))
        self.assertIn("responseFormat", generated[2]["data"]["generationConfig"])


if __name__ == "__main__":
    unittest.main()
