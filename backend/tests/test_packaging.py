"""M6 real process supervision and attempt accounting regressions."""

import contextlib
import hashlib
import io
import json
import os
import importlib.util
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import build_opener, ProxyHandler

from fastapi import HTTPException

from app import media
from app.launcher import REQUIRED, launch, preflight, process_group, verify_release
from app.storage import REPO_ROOT, install_id
from app.maintenance import offline, runtime_lock
from app.storage import Store, encode, now
from app.usage import summarize, token_meters, validate_prices
from tests.support import AppCase


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def responder(reply):
    """Listen on a free loopback port and answer each connection with reply() bytes; None never answers."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        def serve():
            while True:
                try:
                    connection, _ = listener.accept()
                except OSError:
                    return
                with connection:
                    try:
                        connection.recv(65536)
                        connection.sendall(reply())
                    except OSError:
                        pass
        if reply:
            threading.Thread(target=serve, daemon=True).start()
        yield listener.getsockname()[1]


def http_json(body, status=200):
    data = json.dumps(body).encode()
    return (f"HTTP/1.1 {status} Status\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n"
            "Connection: close\r\n\r\n").encode() + data


class LauncherTests(unittest.TestCase):
    def test_release_excludes_unused_historical_assets_and_keeps_runtime_dependencies(self):
        spec = importlib.util.spec_from_file_location("build_release_test", REPO_ROOT / "scripts/build_release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        for name in release.RETIRED_FILES:
            self.assertFalse(release.product_file(name), name)
        for name in (*[path for path in REQUIRED if path.startswith("resources/")],
                     "backend/app/worker.py", "backend/app/analysis.py", "backend/app/gemini_v4.py",
                     "resources/catalogs/survey-v2.json", "resources/catalogs/survey-v1-to-v2.json",
                     "resources/catalogs/survey-v3.json", "resources/rules/scoring-v3.json"):
            self.assertTrue(release.product_file(name), name)
            self.assertTrue((REPO_ROOT / name).is_file(), name)
        self.assertFalse(release.product_file("resources/source/customer.xlsx"))
        self.assertFalse(release.product_file("backend/tests/test_scoring.py"))
        self.assertFalse(release.product_file("docs/요구사항_20261003/customer.docx"))
        self.assertFalse(release.product_file("docs/개발반영_20261003/customer.xlsx"))
        for name in (*release.OPERATING_DOCUMENTS,
                     "docs/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md"):
            self.assertTrue(release.product_file(name), name)

    @unittest.skipUnless(os.name == "nt", "Windows job object")
    def test_process_group_terminates_media_descendants(self):
        import ctypes as c
        from ctypes import wintypes as w
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel.WaitForSingleObject.restype = w.DWORD
        kernel.CloseHandle.argtypes = [w.HANDLE]
        with tempfile.TemporaryDirectory(prefix="kdog-m6-descendant-") as temporary:
            marker = Path(temporary) / "pid"
            code = "import sys,subprocess,time; from pathlib import Path; sys.stdin.buffer.read(1); " \
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); " \
                "Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
            handle = None
            try:
                with process_group() as attach:
                    child = subprocess.Popen([sys.executable, "-c", code, str(marker)], stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                    attach(child)
                    child.stdin.write(b"1")
                    child.stdin.flush()
                    deadline = time.monotonic() + 10
                    while not marker.is_file():
                        if time.monotonic() > deadline:
                            self.fail("descendant startup timed out")
                        time.sleep(0.05)
                    handle = kernel.OpenProcess(0x100000, False, int(marker.read_text()))  # SYNCHRONIZE
                    self.assertTrue(handle)
                self.assertEqual(kernel.WaitForSingleObject(handle, 10000), 0)
                child.wait(timeout=10)
            finally:
                if handle:
                    kernel.CloseHandle(handle)
                child.stdin.close()

    def test_required_files_include_s1_scoring_and_offline_report_assets(self):
        self.assertIn("resources/catalogs/behavior-v4.json", REQUIRED)
        self.assertIn("resources/rules/scoring-v4.json", REQUIRED)
        self.assertIn("resources/rules/preprocess-v4.json", REQUIRED)
        self.assertIn("resources/rules/survey-policy-v4.json", REQUIRED)
        self.assertIn("resources/report/templates/s1.html", REQUIRED)
        self.assertIn("resources/report/templates/s1.css", REQUIRED)
        self.assertFalse([name for name in REQUIRED if name.endswith(("behavior-v1.json", "survey-v1.json", "scoring-v1.json"))])
        self.assertEqual([name for name in REQUIRED if not (REPO_ROOT / name).is_file() and not name.startswith("frontend/")], [])

    def test_ffmpeg_build_manifest_matches_files(self):
        builds = sorted((REPO_ROOT / "releases/.cache").glob("ffmpeg-*-kdog/build.json"))
        if not builds:
            self.skipTest("D00 FFmpeg build output is absent (scripts/ffmpeg/build-ffmpeg.sh)")
        script = (REPO_ROOT / "scripts/ffmpeg/build-ffmpeg.sh").read_text(encoding="utf-8")
        pinned = re.findall(r"^(?:FFMPEG|X264|ZLIB)_SHA256=([0-9a-f]{64})$", script, re.M)
        self.assertEqual(len(pinned), 3)
        for path in builds:
            build, root = json.loads(path.read_text(encoding="utf-8")), path.parent
            actual = {file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
                      for file in root.rglob("*") if file.is_file() and file != path}
            self.assertEqual(build["files"], actual, root)
            for name in ("bin/ffmpeg.exe", "bin/ffprobe.exe", "licenses/COPYING.GPLv2",
                         "licenses/x264-COPYING", "licenses/zlib-LICENSE", "source/build-ffmpeg.sh"):
                self.assertIn(name, actual, root)
            for name, digest in build["sources"].items():
                self.assertEqual(actual["source/" + name], digest, name)
            # A stale cache must not survive a version or source bump in the committed script.
            self.assertEqual(sorted(build["sources"].values()), sorted(pinned), root)
            for name in ("mingw-w64-crt", "mingw-w64-winpthreads", "mingw-w64-libgcc"):
                self.assertTrue(any(file.startswith(f"licenses/{name}/") for file in actual), name)
            configure = build["configure"]["ffmpeg"]
            self.assertIn("--enable-w32threads", configure)
            self.assertIn("--disable-autodetect", configure)
            self.assertEqual(sorted(re.findall(r"--enable-(lib\w+|zlib)", configure)), ["libx264", "zlib"])

    def test_check_rejects_damaged_missing_or_escaping_release_files(self):
        with tempfile.TemporaryDirectory(prefix="kdog-release-check-") as temporary:
            root = Path(temporary) / "K-DOG"
            (root / "runtime/ffmpeg/bin").mkdir(parents=True)
            (root / "runtime/ffmpeg/bin/ffmpeg.exe").write_bytes(b"bundled")
            digest = hashlib.sha256(b"bundled").hexdigest()
            def manifest(files):
                (root / "release.json").write_text(json.dumps({"files": files}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "release.json"):
                verify_release(root)  # a packaged tree (runtime/) must keep its manifest
            verify_release(Path(temporary))  # a development checkout has neither
            manifest({"runtime/ffmpeg/bin/ffmpeg.exe": digest})
            verify_release(root)
            for files in ({"runtime/ffmpeg/bin/ffmpeg.exe": "0" * 64}, {"runtime/ffmpeg/bin/ffprobe.exe": digest},
                          {"../outside.txt": digest}):
                manifest(files)
                with self.assertRaisesRegex(ValueError, "손상"):
                    verify_release(root)
            (Path(temporary) / "outside.txt").write_bytes(b"bundled")
            with self.assertRaisesRegex(ValueError, "손상"):
                verify_release(root)

    def test_packaged_release_uses_only_bundled_ffmpeg(self):
        with tempfile.TemporaryDirectory(prefix="kdog-bundled-ffmpeg-") as temporary:
            runtime = Path(temporary) / "runtime"
            with patch.object(media, "RUNTIME", runtime):
                self.assertEqual(media.tool("ffmpeg"), "ffmpeg")  # development: PATH
                runtime.mkdir()
                bundled = str(runtime / "ffmpeg/bin/ffprobe.exe")
                self.assertEqual(media.tool("ffprobe"), bundled)  # even if quarantined, never PATH
                with patch("app.media.subprocess.run", side_effect=FileNotFoundError) as run:
                    with self.assertRaises(media.MediaError):
                        media.command(["ffprobe", "-version"])
                self.assertEqual(run.call_args.args[0], [bundled, "-version"])
                with patch("app.launcher.subprocess.run") as run, self.assertRaisesRegex(ValueError, "ffmpeg"):
                    preflight()
                run.assert_not_called()

    def test_release_build_accepts_only_the_exact_ffmpeg_build(self):
        spec = importlib.util.spec_from_file_location("build_release_ffmpeg", REPO_ROOT / "scripts/build_release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory(prefix="kdog-ffmpeg-gate-") as temporary:
            build = Path(temporary)
            (build / "bin").mkdir()
            (build / "bin/ffmpeg.exe").write_bytes(b"ffmpeg")
            def manifest(files):
                (build / "build.json").write_text(json.dumps({"files": files}), encoding="utf-8")
            with patch.object(release, "FFMPEG_BUILD", build):
                with self.assertRaisesRegex(ValueError, "없습니다"):
                    release.ffmpeg_runtime()
                manifest({"bin/ffmpeg.exe": hashlib.sha256(b"ffmpeg").hexdigest()})
                self.assertEqual(sorted(release.ffmpeg_runtime()), ["runtime/ffmpeg/bin/ffmpeg.exe", "runtime/ffmpeg/build.json"])
                (build / "bin/extra.dll").write_bytes(b"")
                with self.assertRaisesRegex(ValueError, "build.json"):
                    release.ffmpeg_runtime()
                (build / "bin/extra.dll").unlink()
                manifest({"bin/ffmpeg.exe": "0" * 64})
                with self.assertRaisesRegex(ValueError, "build.json"):
                    release.ffmpeg_runtime()

    def test_preflight_rejects_missing_media_tools(self):
        with patch("app.launcher.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "ffmpeg"):
                preflight()
        # A user-install folder has no runtime/, so the user must fix PATH rather than reinstall.
        with tempfile.TemporaryDirectory(prefix="kdog-path-ffmpeg-") as temporary, \
                patch.object(media, "RUNTIME", Path(temporary) / "runtime"), \
                patch("app.launcher.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "PATH에 등록"):
                preflight()
        with tempfile.TemporaryDirectory(prefix="kdog-bundled-missing-") as temporary, \
                patch.object(media, "RUNTIME", Path(temporary)), \
                patch("app.launcher.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "다시 설치"):
                preflight()

    def test_user_install_scripts_stay_ascii_and_hash_check_before_the_locked_venv(self):
        online = REPO_ROOT / "scripts/windows/online"
        for name in ("Install.cmd", "Start.cmd", "install.ps1"):
            content = (online / name).read_bytes()
            content.decode("ascii")  # cmd.exe and Windows PowerShell 5.1 read these without a BOM
            if name.endswith(".cmd"):
                self.assertEqual(content.count(b"\n"), content.count(b"\r\n"), name)
        script = (online / "install.ps1").read_text(encoding="ascii")
        self.assertLess(script.index("release.json"), script.index("uv sync --locked --no-dev"))
        self.assertIn("Remove-Item Env:PYTHONHOME, Env:PYTHONPATH", script)
        self.assertIn("UV_PROJECT_ENVIRONMENT", script)
        start = (online / "Start.cmd").read_text(encoding="ascii")
        self.assertIn(r'".venv\Scripts\python.exe" -X utf8 -m app.launcher %*', start)
        self.assertIn('exit /b %status%', start)
        self.assertIn('install.ps1" %*', (online / "Install.cmd").read_text(encoding="ascii"))

    @unittest.skipUnless((REPO_ROOT / "frontend/node_modules").is_dir(), "frontend dependencies are not installed")
    def test_open_source_notice_lists_python_packages_only_when_bundled(self):
        spec = importlib.util.spec_from_file_location("build_release_notice", REPO_ROOT / "scripts/build_release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory(prefix="kdog-notice-") as temporary:
            staging = Path(temporary)
            files = {}
            release.notice(staging, files, REPO_ROOT / "scripts/windows/online/오픈소스고지.txt", "licenses")
            text = files["오픈소스고지.txt"].read_text(encoding="utf-8-sig")
            self.assertIn("사용자 설치형", text)
            self.assertNotIn("동봉한 Python 패키지", text)
            self.assertIn("- react ", text)
            self.assertIn("라이선스 전문: licenses\\npm\\<이름>", text)
            # runtime/ would make the app look for a bundled FFmpeg that a user-install package does not have.
            self.assertTrue(any(name.startswith("licenses/npm/react/") for name in files))
            self.assertFalse(any(name.startswith("runtime/") for name in files))
            metadata = staging / "METADATA"
            metadata.write_text("Name: fastapi\nVersion: 0.141.1\nLicense-Expression: MIT\n", encoding="utf-8")
            files = {"runtime/python/Lib/site-packages/fastapi-0.141.1.dist-info/METADATA": metadata}
            release.notice(staging, files, REPO_ROOT / "scripts/windows/오픈소스고지.txt")
            text = files["오픈소스고지.txt"].read_text(encoding="utf-8-sig")
            self.assertIn("- fastapi 0.141.1: MIT", text)
            self.assertIn("라이선스 전문: runtime\\licenses\\npm\\<이름>", text)
            self.assertTrue(any(name.startswith("runtime/licenses/npm/react/") for name in files))

    def test_start_both_ready_duplicate_rejected_and_stop_releases_locks(self):
        with tempfile.TemporaryDirectory(prefix="kdog-m6-launch-") as temporary:
            root, port = Path(temporary), free_port()
            event = threading.Event()
            def ready(children):
                self.assertTrue(all(child.poll() is None for child in children))
                # Same data on another port: nothing answers there, so the lock error stands.
                with self.assertRaises(HTTPException):
                    launch(root, free_port(), open_browser=False, lock_wait=1)
                # Clicking again: only the browser opens for the running instance.
                again = io.StringIO()
                with (patch("app.launcher.webbrowser.open") as browser, patch("app.launcher.subprocess.Popen") as spawn,
                      contextlib.redirect_stdout(again)):
                    launch(root, port)
                browser.assert_called_once_with(f"http://127.0.0.1:{port}")
                spawn.assert_not_called()
                self.assertIn("이미 실행 중입니다. 브라우저를 엽니다.", again.getvalue())
                # Another data folder (or another installed version) on the same port is not silently reused.
                with tempfile.TemporaryDirectory(prefix="kdog-m6-other-") as other:
                    with self.assertRaisesRegex(ValueError, "다른 위치나 버전의 K-DOG"):
                        launch(Path(other), port, open_browser=False)
                event.set()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                launch(root, port, open_browser=False, stop_event=event, ready=ready)
            self.assertIn("이 창을 닫으면 K-DOG가 종료됩니다", output.getvalue())
            self.assertNotIn("Ctrl+C", output.getvalue())
            self.assertNotIn("브라우저", output.getvalue())  # --no-browser
            with offline(Store(root)):
                pass

    def test_second_click_while_first_is_starting_waits_and_opens_browser(self):
        started = threading.Event()
        with tempfile.TemporaryDirectory(prefix="kdog-starting-") as temporary:
            root = Path(temporary)
            health = lambda: http_json({"service": "K-DOG", "install": install_id(root)}, 200 if started.is_set() else 503)
            # The first launcher holds its lock and becomes healthy only after a delay.
            timer = threading.Timer(1.5, started.set)
            output = io.StringIO()
            with (responder(health) as port, runtime_lock(Store(root), "launcher"),
                  patch("app.launcher.webbrowser.open") as browser, patch("app.launcher.preflight"),
                  patch("app.launcher.subprocess.Popen") as spawn, contextlib.redirect_stdout(output)):
                timer.start()
                launch(root, port, lock_wait=10)
            timer.cancel()
            self.assertTrue(started.is_set())
            browser.assert_called_once_with(f"http://127.0.0.1:{port}")
            spawn.assert_not_called()
            self.assertIn("시작하는 중", output.getvalue())

    def test_first_launch_that_stops_while_waiting_lets_the_second_start(self):
        with tempfile.TemporaryDirectory(prefix="kdog-lock-retry-") as temporary:
            root, held = Path(temporary), threading.Event()
            def first():
                with runtime_lock(Store(root), "launcher"):
                    held.set()
                    time.sleep(1.5)
            thread = threading.Thread(target=first)
            thread.start()
            held.wait(5)
            with responder(None) as port, patch("app.launcher.preflight"):
                # Reaching the port check proves the lock was retried and acquired after the first stopped.
                with self.assertRaisesRegex(ValueError, "포트를 사용 중"):
                    launch(root, port, open_browser=False, lock_wait=10)
            thread.join()

    def test_other_programs_on_the_port_start_no_children(self):
        replies = {"silent": None, "not HTTP": lambda: b"SSH-2.0-OpenSSH\r\n",
                   "truncated": lambda: b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{",
                   "JSON list": lambda: http_json([1]), "other service": lambda: http_json({"service": "other"})}
        for name, reply in replies.items():
            with self.subTest(name), tempfile.TemporaryDirectory(prefix="kdog-m6-port-") as temporary:
                with (responder(reply) as port, patch("app.launcher.subprocess.Popen") as spawn,
                      patch("app.launcher.preflight")):  # preflight also uses Popen
                    with self.assertRaisesRegex(ValueError, "다른 프로그램이 .* 포트를 사용 중"):
                        launch(Path(temporary), port, open_browser=False)
                spawn.assert_not_called()

    def test_worker_failure_stops_api(self):
        with tempfile.TemporaryDirectory(prefix="kdog-m6-failure-") as temporary:
            def ready(children):
                children[1].kill()
                children[1].wait(timeout=10)
            with self.assertRaisesRegex(RuntimeError, "함께 중지"):
                launch(Path(temporary), free_port(), open_browser=False, ready=ready)
            with offline(Store(Path(temporary))):
                pass

    def test_killed_launcher_leaves_no_api_or_worker_lock(self):
        with tempfile.TemporaryDirectory(prefix="kdog-m6-kill-") as temporary:
            root, port = Path(temporary), free_port()
            process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "app.launcher", "--data-dir", str(root),
                "--port", str(port), "--no-browser"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                opener = build_opener(ProxyHandler({}))
                deadline = time.monotonic() + 30
                while True:
                    self.assertIsNone(process.poll())
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            self.fail("API startup timed out")
                        time.sleep(0.1)
                # Wait until worker has acquired its own process lock.
                store = Store(root)
                from app.maintenance import runtime_lock
                while True:
                    try:
                        with runtime_lock(store, "worker"):
                            pass
                    except HTTPException:
                        break
                    if time.monotonic() > deadline:
                        self.fail("worker startup timed out")
                    time.sleep(0.1)
                process.kill()
                process.wait(timeout=10)
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with offline(store):
                            break
                    except HTTPException:
                        if time.monotonic() > deadline:
                            self.fail("orphaned child still holds a runtime lock")
                        time.sleep(0.1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)


class UsageTests(AppCase):
    def completed(self):
        """A finished run with five reserved provider calls (two observations, two evaluations, one report), written directly."""
        item = self.make_case(event_id="M2")
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,status,created_at,updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", ("run-usage", item["case_id"], item["selected_session_id"], 1, "{}", "{}", "scored", now(), now()))
            for index, (stage, branch) in enumerate((("observe", "video-1"), ("observe", "video-2"), ("evaluate", "dog"), ("evaluate", "owner"), ("report", "source"))):
                db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,usage_json,created_at,updated_at,call_reserved) "
                           "VALUES (?,?,?,?,1,'succeeded','{}',?,?,1)", (f"step-{index}", "run-usage", stage, branch, now(), now()))

    def test_no_prices_is_unknown_and_metadata_is_not_exported(self):
        self.completed()
        result = summarize(self.store, event_id="M2")
        self.assertEqual(result["calls_reserved"], 5)
        self.assertEqual(result["unpriced_or_uncertain_calls"], 5)
        self.assertIsNone(result["complete_meter_cost_estimate"])
        self.assertNotIn("credential_reference", encode(result))
        self.assertEqual(summarize(self.store, event_id="absent")["runs"], [])

    def test_recorded_but_unpriced_token_meters_block_a_complete_estimate(self):
        self.completed()
        prices = {"currency": "TEST", "as_of": "2026-09-08", "source": "synthetic unit test; not real prices",
            "models": {"synthetic/model": {"total_input_tokens": "2", "total_output_tokens": "4"}}}
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET usage_json=? WHERE call_reserved=1",
                (encode({"provider": "synthetic", "model": "model", "total_input_tokens": 100,
                         "total_output_tokens": 50, "total_tokens": 150}),))
        result = summarize(self.store, prices=prices)
        # The provider roll-up is not a billable category, so it never counts as unpriced.
        self.assertEqual(result["unpriced_meters"], [])
        self.assertEqual(result["complete_meter_cost_estimate"], "0.0020")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET usage_json=? WHERE call_reserved=1",
                (encode({"provider": "synthetic", "model": "model", "total_input_tokens": 100,
                         "total_output_tokens": 50, "total_tokens": 400, "total_thought_tokens": 200,
                         "total_tool_use_tokens": 50}),))
        result = summarize(self.store, prices=prices)
        self.assertEqual(result["unpriced_meters"], ["total_thought_tokens", "total_tool_use_tokens"])
        self.assertIsNone(result["complete_meter_cost_estimate"])
        self.assertEqual(result["known_meter_cost_estimate"], "0.0020")
        # A call whose recorded categories are not all priced is itself an unpriced call.
        self.assertEqual(result["unpriced_or_uncertain_calls"], result["calls_reserved"])
        self.assertTrue(all(a["unpriced_meters"] == ["total_thought_tokens", "total_tool_use_tokens"]
                            for run in result["runs"] for a in run["attempts"]))
        priced = {**prices, "models": {"synthetic/model": {**prices["models"]["synthetic/model"],
                  "total_thought_tokens": "4", "total_tool_use_tokens": "1"}}}
        result = summarize(self.store, prices=priced)
        self.assertEqual(result["unpriced_meters"], [])
        self.assertEqual(result["unpriced_or_uncertain_calls"], 0)
        self.assertEqual(result["complete_meter_cost_estimate"], "0.00625")
        # Pricing the provider roll-up covers every category inside it.
        rolled = {**prices, "models": {"synthetic/model": {"total_tokens": "2"}}}
        result = summarize(self.store, prices=rolled)
        self.assertEqual(result["unpriced_meters"], [])
        self.assertEqual(result["complete_meter_cost_estimate"], "0.0040")

    def test_prices_retry_uncertainty_reuse_and_deletion(self):
        self.completed()
        prices = {"currency": "TEST", "as_of": "2026-09-06", "source": "synthetic unit test; not real prices",
            "models": {"synthetic/model": {"input_tokens": "2", "output_tokens": "4"}}}
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET usage_json=? WHERE call_reserved=1",
                (encode({"provider": "synthetic", "model": "model", "input_tokens": 100, "output_tokens": 50,
                         "credential_reference": "do-not-export", "provider_error_message": "do-not-export"}),))
        result = summarize(self.store, prices=prices)
        self.assertEqual(result["complete_meter_cost_estimate"], "0.0020")
        self.assertNotIn("do-not-export", encode(result))
        with self.store.connect(write=True) as db:
            step = db.execute("SELECT * FROM steps WHERE call_reserved=1 LIMIT 1").fetchone()
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,usage_json,created_at,updated_at,call_reserved) "
                "VALUES('extra-attempt',?,?,?,?,?,?,?,?,1)", (step["run_id"], step["stage"], step["branch_key"], 2,
                "abandoned", encode({"billing_uncertain": True}), step["created_at"], step["updated_at"]))
        result = summarize(self.store, prices=prices)
        self.assertEqual(result["calls_reserved"], 6)
        self.assertEqual(result["unpriced_or_uncertain_calls"], 1)
        self.assertIsNone(result["complete_meter_cost_estimate"])
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET call_reserved=0 WHERE step_id='extra-attempt'")
        self.assertEqual(summarize(self.store)["calls_reserved"], 5)
        self.assertIsNone(summarize(self.store, prices=prices)["complete_meter_cost_estimate"])
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET usage_json=? WHERE step_id='extra-attempt'", (encode({"reused": True}),))
        self.assertEqual(summarize(self.store, prices=prices)["complete_meter_cost_estimate"], "0.0020")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1")
        self.assertEqual(summarize(self.store)["runs"], [])

    def test_nested_meters_and_invalid_prices(self):
        self.assertEqual(token_meters({"input_tokens": 12, "input_tokens_details": {"cached_tokens": 4},
            "output_tokens": True, "bad_tokens": -1, "request_id": "secret"}),
            {"input_tokens": 12, "input_tokens_details.cached_tokens": 4})
        for rate in ("NaN", "Infinity", -1, "invalid"):
            with self.assertRaises(ValueError):
                validate_prices({"currency": "TEST", "as_of": "today", "source": "test",
                                 "models": {"test/model": {"input_tokens": rate}}})
