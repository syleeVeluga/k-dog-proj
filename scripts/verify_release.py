"""Extract a portable release to a new path without uv/Python/FFmpeg on PATH; smoke-test HTTP, restart and locks."""

import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from zipfile import ZipFile


def windows_only_path():
    system = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    path = os.pathsep.join(str(item) for item in (system / "System32", system, system / "System32/Wbem",
                                                   system / "System32/WindowsPowerShell/v1.0"))
    for tool in ("uv", "python", "ffmpeg", "ffprobe"):
        if shutil.which(tool, path=path):
            raise RuntimeError(f"{tool} is on the Windows system PATH; cannot prove the package is self-contained")
    return path


def verify(package):
    with tempfile.TemporaryDirectory(prefix="kdog-s1-clean-") as temporary:
        root = Path(temporary)
        app = root / "새 설치 경로"
        with ZipFile(package) as archive:
            for name in archive.namelist():
                if not (app / name).resolve().is_relative_to(app.resolve()):
                    raise ValueError("unsafe package path")
                if any(part in {"tests", ".venv", ".git", "node_modules", "__pycache__", ".env"} for part in Path(name).parts):
                    raise ValueError("development/runtime file leaked into package")
            archive.extractall(app)
        for name in ("Start.cmd", "release.json", "오픈소스고지.txt", "runtime/python/python.exe",
                     "runtime/python/python314._pth", "runtime/python/LICENSE.txt", "runtime/ffmpeg/bin/ffmpeg.exe",
                     "runtime/ffmpeg/bin/ffprobe.exe", "runtime/ffmpeg/build.json", "runtime/ffmpeg/licenses/COPYING.GPLv2",
                     "runtime/ffmpeg/source/build-ffmpeg.sh", "runtime/ffmpeg/source/configure-commands.txt"):
            if not (app / name).is_file():
                raise RuntimeError(f"package is missing {name}")
        if not any((app / "runtime/ffmpeg/source").glob("ffmpeg-*.tar.xz")) or not any(
                (app / "runtime/python/Lib/site-packages").glob("*.dist-info/licenses/*")):
            raise RuntimeError("package is missing FFmpeg corresponding source or Python package licenses")
        env = {**os.environ, "PATH": windows_only_path(), "KDOG_DATA_DIR": str(root / "data"), "GEMINI_API_KEY": "",
               "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "PYTHONUTF8": "1",
               "PYTHONPATH": str(root / "wrong-path"), "PYTHONHOME": str(root / "wrong-home")}
        def check_package():
            return subprocess.run([str(app / "Start.cmd"), "--check"], cwd=app, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=120)
        asset = app / "frontend/dist/index.html"
        original = asset.read_bytes()
        asset.write_bytes(b"corrupted release")
        try:
            damaged = check_package()
            if damaged.returncode == 0 or "손상".encode() not in damaged.stdout + damaged.stderr:
                raise RuntimeError("damaged release was not rejected by Start.cmd --check")
        finally:
            asset.write_bytes(original)
        checked = check_package()
        if checked.returncode:
            raise RuntimeError("Start.cmd --check failed: " + (checked.stdout + checked.stderr).decode("utf-8", errors="replace"))
        python = app / "runtime/python/python.exe"
        def command(*arguments):
            return subprocess.run([str(python), "-X", "utf8", *arguments], cwd=app, env=env,
                                  check=True, capture_output=True, timeout=30)
        bundled = command("-c", "import sys; from app import media; print(media.tool('ffmpeg')); print(sys.prefix)")
        ffmpeg, prefix = (Path(line).resolve() for line in bundled.stdout.decode().splitlines())
        if ffmpeg != (app / "runtime/ffmpeg/bin/ffmpeg.exe").resolve() or prefix != (app / "runtime/python").resolve():
            raise RuntimeError("packaged app does not use its bundled Python and FFmpeg")
        command("-c", "from pathlib import Path; import os; from app.storage import Store; from app.auth import create_user\n"
            "from app.input_models import UserCreate\n"
            "with Store(Path(os.environ['KDOG_DATA_DIR'])).connect(write=True) as db:\n"
            "    create_user(db,UserCreate(username='pilot',role='admin',password='Synthetic-install-only-42'))\n")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        case_id = None
        for run in range(2):
            process = subprocess.Popen([str(python), "-X", "utf8", "-m", "app.launcher", "--port", str(port), "--no-browser"],
                cwd=app, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("packaged launcher exited")
                    try:
                        with opener.open(url + "/api/health", timeout=1) as response:
                            if json.load(response).get("spec") != "20261002":
                                raise RuntimeError("packaged server does not use the S1 specification")
                            break
                    except URLError:
                        if time.monotonic() > deadline:
                            raise RuntimeError("packaged startup timed out") from None
                        time.sleep(0.1)
                # The launcher prints this only after BOTH children pass readiness.
                if "K-DOG 실행 중" not in process.stdout.readline().decode("utf-8"):
                    raise RuntimeError("packaged worker did not become ready")
                with opener.open(url + "/") as response:
                    if b'<div id="root">' not in response.read():
                        raise RuntimeError("packaged UI missing")
                def request(path, body=None):
                    data = json.dumps(body).encode() if body is not None else None
                    with opener.open(Request(url + path, data=data, headers={"Content-Type": "application/json", "X-KDOG-Request": "1"}), timeout=10) as response:
                        return json.load(response)
                request("/api/auth/login", {"username": "pilot", "password": "Synthetic-install-only-42"})
                if run == 0:
                    case = request("/api/cases", {"event_id": "S1-INSTALL", "participant_id": "0001", "dog_name": "설치 시험견"})
                    if case["manifest"]["schema_version"] != "intake-4.0":
                        raise RuntimeError("new package created an old input edition")
                    case_id = case["case_id"]
                else:
                    if request("/api/cases/" + case_id)["participant_id"] != "0001":
                        raise RuntimeError("packaged restart lost data")
            finally:
                process.kill()
                process.wait(timeout=10)
                process.stdout.close()
                # The supervisor must release locks even after an abrupt termination.
                deadline = time.monotonic() + 10
                while True:
                    try:
                        command("-c", "from pathlib import Path; import os; from app.storage import Store\n"
                            "from app.maintenance import offline\n"
                            "with offline(Store(Path(os.environ['KDOG_DATA_DIR']))):\n    pass\n")
                        break
                    except subprocess.CalledProcessError:
                        if time.monotonic() > deadline:
                            raise
                        time.sleep(0.1)
        print(json.dumps({"package": str(package.resolve()), "bundled_runtime_only": True, "unicode_space_path": True,
            "corruption_rejected_by_check": True, "environment_override_isolated": True,
            "http_login_create_restart": "passed", "supervisor_shutdown": "passed", "external_ai_calls": 0,
            "spec": "20261002", "s1_catalog_report_assets": "passed",
            "scope": "new folder on current Windows host, PATH without uv/Python/FFmpeg; not a clean OS/second PC"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    verify(parser.parse_args().package)
