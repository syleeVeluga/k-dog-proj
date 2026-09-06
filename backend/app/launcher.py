"""Supervise the local API and worker without a shell or a second installation."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler
import uuid
import webbrowser

from app.storage import REPO_ROOT, Store
from app.maintenance import offline, runtime_lock


def watch_supervisor():
    # An inherited pipe closes even if the launcher is killed or its window closes.
    if os.environ.get("KDOG_SUPERVISED") == "1":
        if sys.stdin.buffer.read(1) != b"1":
            os._exit(0)
        def watch():
            sys.stdin.buffer.read(1)
            os._exit(0)
        threading.Thread(target=watch, daemon=True).start()


@contextmanager
def process_group():
    """Windows also terminates media subprocess descendants when the launcher dies."""
    if os.name != "nt":
        yield lambda child: None
        return
    import ctypes as c
    from ctypes import wintypes as w

    class BasicLimits(c.Structure):
        _fields_ = [("process_time", c.c_longlong), ("job_time", c.c_longlong), ("flags", w.DWORD),
            ("minimum_working_set", c.c_size_t), ("maximum_working_set", c.c_size_t),
            ("active_processes", w.DWORD), ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

    class ExtendedLimits(c.Structure):
        _fields_ = [("basic", BasicLimits), ("io_counters", c.c_ulonglong * 6),
            ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
            ("peak_process_memory", c.c_size_t), ("peak_job_memory", c.c_size_t)]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    kernel.SetInformationJobObject.restype = w.BOOL
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.AssignProcessToJobObject.restype = w.BOOL
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise c.WinError(c.get_last_error())
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)):
            raise c.WinError(c.get_last_error())

        def attach(child):
            handle = kernel.OpenProcess(0x0101, False, child.pid)  # SET_QUOTA | TERMINATE
            if not handle:
                raise c.WinError(c.get_last_error())
            try:
                if not kernel.AssignProcessToJobObject(job, handle):
                    raise c.WinError(c.get_last_error())
            finally:
                kernel.CloseHandle(handle)
        yield attach
    finally:
        kernel.CloseHandle(job)


def preflight():
    if sys.version_info[:2] != (3, 14):
        raise ValueError("Python 3.14 환경이 필요합니다. Install.cmd를 실행하세요.")
    required = ["frontend/dist/index.html", "resources/catalogs/behavior-v1.json",
                "resources/catalogs/survey-v1.json", "resources/rules/scoring-v1.json",
                "resources/fonts/NanumGothic-Regular.ttf", "resources/fonts/NotoSansSymbols.ttf"]
    for name in required:
        if not (REPO_ROOT / name).is_file():
            raise ValueError(f"설치 파일이 없습니다: {name}")
    for name in ("ffmpeg", "ffprobe"):
        if not shutil.which(name):
            raise ValueError(f"{name}을 설치하고 PATH에 등록하세요.")
        subprocess.run([name, "-version"], check=True, capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def stop(children):
    for child in children:
        if child.stdin:
            child.stdin.close()
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)


def launch(data_dir, port=8000, *, open_browser=True, stop_event=None, ready=None):
    if not 1 <= port <= 65535:
        raise ValueError("포트는 1~65535여야 합니다.")
    preflight()
    store = Store(data_dir)
    stop_event = stop_event or threading.Event()
    with runtime_lock(store, "launcher"):
        with offline(store):
            pass
        with socket.socket() as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
        with tempfile.TemporaryDirectory(prefix="kdog-launch-") as temporary, process_group() as attach:
            marker = Path(temporary) / "worker-ready"
            instance = uuid.uuid4().hex
            env = {**os.environ, "KDOG_SUPERVISED": "1", "KDOG_INSTANCE": instance,
                   "KDOG_WORKER_READY": str(marker), "PYTHONUTF8": "1"}
            command = [sys.executable, "-X", "utf8", "-m", "app.manage", "--data-dir", str(store.root)]
            children = []
            try:
                for arguments in (["serve", "--port", str(port)], ["worker"]):
                    children.append(subprocess.Popen(command + arguments, cwd=REPO_ROOT / "backend",
                        env=env, stdin=subprocess.PIPE,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
                    attach(children[-1])
                    children[-1].stdin.write(b"1")
                    children[-1].stdin.flush()
                url = f"http://127.0.0.1:{port}"
                opener = build_opener(ProxyHandler({}))
                deadline = time.monotonic() + 30
                while True:
                    if any(child.poll() is not None for child in children):
                        raise RuntimeError("API 또는 worker 시작에 실패했습니다.")
                    if stop_event.is_set():
                        return
                    try:
                        with opener.open(url + "/api/health", timeout=1) as response:
                            healthy = json.load(response).get("instance") == instance
                        if healthy and marker.is_file():
                            break
                    except (OSError, URLError, ValueError):
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError("실행 준비 제한 시간(30초)을 초과했습니다.")
                    stop_event.wait(0.2)
                print(f"K-DOG 실행 중: {url}\n종료하려면 이 창에서 Ctrl+C를 누르세요.", flush=True)
                if ready:
                    ready(children)
                if open_browser:
                    webbrowser.open(url)
                while not stop_event.wait(0.5):
                    if any(child.poll() is not None for child in children):
                        raise RuntimeError("API 또는 worker가 종료되어 함께 중지했습니다. 다시 실행하면 미완료 작업을 복구합니다.")
            finally:
                stop(children)


def main():
    from app.api import DEFAULT_DATA
    from fastapi import HTTPException
    parser = argparse.ArgumentParser(description="K-DOG API·worker 원클릭 실행")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("KDOG_DATA_DIR", DEFAULT_DATA)))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="설치 파일·Python·FFmpeg 확인만 수행")
    args = parser.parse_args()
    try:
        if args.check:
            preflight()
            print("K-DOG 설치 파일·Python·FFmpeg 확인 완료")
        else:
            launch(args.data_dir, args.port, open_browser=not args.no_browser)
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, HTTPException) as exc:
        parser.exit(1, f"실행 실패: {getattr(exc, 'detail', str(exc))}\n")


if __name__ == "__main__":
    main()
