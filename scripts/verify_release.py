"""Install a release in a new path/venv and smoke-test real HTTP, restart and locks."""

import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from zipfile import ZipFile


def verify(package):
    with tempfile.TemporaryDirectory(prefix="kdog-m6-clean-") as temporary:
        root = Path(temporary)
        app = root / "새 설치 경로"
        with ZipFile(package) as archive:
            for name in archive.namelist():
                if not (app / name).resolve().is_relative_to(app.resolve()):
                    raise ValueError("unsafe package path")
                if any(part in {"tests", ".venv", ".git", "node_modules", "__pycache__", ".env"} for part in Path(name).parts):
                    raise ValueError("development/runtime file leaked into package")
            archive.extractall(app)
        env = {**os.environ, "KDOG_DATA_DIR": str(root / "data"), "GEMINI_API_KEY": "",
               "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "PYTHONUTF8": "1",
               "UV_PROJECT_ENVIRONMENT": str(root / "wrong-env")}
        install_command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(app / "install.ps1"), "-SkipAccounts"]
        def install_package():
            return subprocess.run(install_command, env=env, capture_output=True, timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        asset = app / "frontend/dist/index.html"
        original = asset.read_bytes()
        asset.write_bytes(b"corrupted release")
        try:
            damaged = install_package()
            if damaged.returncode == 0 or (app / "backend/.venv").exists():
                raise RuntimeError("damaged release was not rejected before installation")
        finally:
            asset.write_bytes(original)
        install = install_package()
        if install.returncode:
            raise RuntimeError(install.stdout.decode("utf-8", errors="replace") + install.stderr.decode("utf-8", errors="replace"))
        if (root / "wrong-env").exists():
            raise RuntimeError("installer used an unrelated UV_PROJECT_ENVIRONMENT")
        wrapper = subprocess.run([str(app / "Start.cmd"), "--check"], cwd=app, env=env,
                                 capture_output=True, timeout=30)
        if wrapper.returncode:
            raise RuntimeError("Start.cmd installation check failed")
        python = app / "backend/.venv/Scripts/python.exe"
        def command(*arguments):
            return subprocess.run([str(python), "-X", "utf8", *arguments], cwd=app / "backend", env=env,
                                  check=True, capture_output=True, timeout=30)
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
                cwd=app / "backend", env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("packaged launcher exited")
                    try:
                        with opener.open(url + "/api/health", timeout=1):
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
                    case_id = request("/api/cases", {"event_id": "M6-INSTALL", "participant_id": "0001", "dog_name": "설치 시험견"})["case_id"]
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
        print(json.dumps({"package": str(package.resolve()), "fresh_venv": True, "unicode_space_path": True,
            "corruption_rejected_before_install": True, "environment_override_isolated": True,
            "http_login_create_restart": "passed", "supervisor_shutdown": "passed", "external_ai_calls": 0,
            "scope": "new folder and venv on current Windows host; not a clean OS/second PC"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    verify(parser.parse_args().package)
