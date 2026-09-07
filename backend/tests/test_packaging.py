"""M6 real process supervision and attempt accounting regressions."""

import json
import os
from pathlib import Path
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

from app.launcher import launch, preflight, process_group
from app.maintenance import offline
from app.storage import Store, encode
from app.usage import summarize, token_meters, validate_prices
from tests import test_observation as observation


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LauncherTests(unittest.TestCase):
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

    def test_preflight_rejects_missing_media_tools(self):
        with patch("app.launcher.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "ffmpeg"):
                preflight()

    def test_start_both_ready_duplicate_rejected_and_stop_releases_locks(self):
        with tempfile.TemporaryDirectory(prefix="kdog-m6-launch-") as temporary:
            root, port = Path(temporary), free_port()
            event = threading.Event()
            def ready(children):
                self.assertTrue(all(child.poll() is None for child in children))
                with self.assertRaises(HTTPException):
                    launch(root, free_port(), open_browser=False)
                event.set()
            launch(root, port, open_browser=False, stop_event=event, ready=ready)
            with offline(Store(root)):
                pass

    def test_occupied_port_starts_no_children(self):
        with tempfile.TemporaryDirectory(prefix="kdog-m6-port-") as temporary, socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            with patch("app.launcher.subprocess.Popen") as spawn:
                # preflight also uses Popen; isolate it for this focused bind regression.
                with patch("app.launcher.preflight"):
                    with self.assertRaises(OSError):
                        launch(Path(temporary), sock.getsockname()[1], open_browser=False)
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


class UsageTests(unittest.TestCase):
    setUp = observation.ObservationTests.setUp
    login = observation.ObservationTests.login
    start = observation.ObservationTests.start

    def completed(self):
        self.start()
        self.worker.once()

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
