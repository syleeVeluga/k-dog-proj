"""Verify a portable release and an issued package built from it, without uv/Python/FFmpeg on PATH.

Plain ZIP: new Korean/space path, damaged-file rejection, bundled runtime, HTTP login/intake/restart, locks.
Issued ZIP (synthetic customer VERIFY): no readable product files, wrong key and tampering change nothing,
key install with accounts and shortcut, admin/developer login, and reinstall keeping data and accounts.
User-install ZIP (--variant online, uv/FFmpeg on PATH, internet): Start.cmd asks for Install.cmd first, damage
is rejected before a venv exists, Install.cmd builds backend/.venv, then the same HTTP, restart and lock checks.
"""

import argparse
from contextlib import contextmanager
from http.cookiejar import CookieJar
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
# A product source line that must never be readable in an issued package.
SOURCE_MARKER = b"Supervise the local API and worker"


def windows_only_path():
    system = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    path = os.pathsep.join(str(item) for item in (system / "System32", system, system / "System32/Wbem",
                                                   system / "System32/WindowsPowerShell/v1.0"))
    for tool in ("uv", "python", "ffmpeg", "ffprobe"):
        if shutil.which(tool, path=path):
            raise RuntimeError(f"{tool} is on the Windows system PATH; cannot prove the package is self-contained")
    return path


def isolated_env(root, data):
    return {**os.environ, "PATH": windows_only_path(), "KDOG_DATA_DIR": str(data), "GEMINI_API_KEY": "",
            "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "PYTHONUTF8": "1",
            "PYTHONPATH": str(root / "wrong-path"), "PYTHONHOME": str(root / "wrong-home")}


def run_python(python, app, env, *arguments):
    return subprocess.run([str(python), "-X", "utf8", *arguments], cwd=app, env=env,
                          check=True, capture_output=True, timeout=30)


@contextmanager
def served(command, app, env, *, kill_tree=False, python=None):
    """Run the launcher on a free port until ready; yield a factory of logged-out HTTP clients."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([*command, "--port", str(port), "--no-browser"], cwd=app, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        probe = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 30
        while True:
            if process.poll() is not None:
                raise RuntimeError("packaged launcher exited")
            try:
                with probe.open(url + "/api/health", timeout=1) as response:
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
        with probe.open(url + "/") as response:
            if b'<div id="root">' not in response.read():
                raise RuntimeError("packaged UI missing")

        def client():
            opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
            def request(path, body=None):
                data = json.dumps(body).encode() if body is not None else None
                headers = {"Content-Type": "application/json", "X-KDOG-Request": "1"}
                with opener.open(Request(url + path, data=data, headers=headers), timeout=10) as response:
                    return json.load(response)
            return request
        yield client
    finally:
        if kill_tree:  # Start.cmd: end cmd.exe and the launcher under it
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        else:
            process.kill()
        process.wait(timeout=10)
        process.stdout.close()
        # The supervisor must release locks even after an abrupt termination.
        if python:  # a venv interpreter cannot start under the deliberately wrong PYTHONHOME; launchers clear it
            env = {key: value for key, value in env.items() if key not in ("PYTHONHOME", "PYTHONPATH")}
        python = python or Path(app) / "runtime/python/python.exe"
        deadline = time.monotonic() + 10
        while True:
            try:
                run_python(python, app, env, "-c", "from pathlib import Path; import os; from app.storage import Store\n"
                           "from app.maintenance import offline\n"
                           "with offline(Store(Path(os.environ['KDOG_DATA_DIR']))):\n    pass\n")
                break
            except subprocess.CalledProcessError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)


def unpack(package, app):
    with ZipFile(package) as archive:
        for name in archive.namelist():
            if not (app / name).resolve().is_relative_to(app.resolve()):
                raise ValueError("unsafe package path")
            if any(part in {"tests", ".venv", ".git", "node_modules", "__pycache__", ".env"} for part in Path(name).parts):
                raise ValueError("development/runtime file leaked into package")
        manifest = json.loads(archive.read("release.json"))
        if set(archive.namelist()) != set(manifest["files"]) | {"release.json"}:
            raise ValueError("package entries differ from release.json")
        archive.extractall(app)
    return manifest


def verify_plain(package, root):
    app = root / "새 설치 경로"
    unpack(package, app)
    for name in ("Start.cmd", "release.json", "오픈소스고지.txt", "runtime/python/python.exe",
                 "runtime/python/python314._pth", "runtime/python/LICENSE.txt", "runtime/ffmpeg/bin/ffmpeg.exe",
                 "runtime/ffmpeg/bin/ffprobe.exe", "runtime/ffmpeg/build.json", "runtime/ffmpeg/licenses/COPYING.GPLv2",
                 "runtime/ffmpeg/source/build-ffmpeg.sh", "runtime/ffmpeg/source/configure-commands.txt"):
        if not (app / name).is_file():
            raise RuntimeError(f"package is missing {name}")
    if not any((app / "runtime/ffmpeg/source").glob("ffmpeg-*.tar.xz")) or not any(
            (app / "runtime/python/Lib/site-packages").glob("*.dist-info/licenses/*")):
        raise RuntimeError("package is missing FFmpeg corresponding source or Python package licenses")
    env = isolated_env(root, root / "data")
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
    bundled = run_python(python, app, env, "-c", "import sys; from app import media; print(media.tool('ffmpeg')); print(sys.prefix)")
    ffmpeg, prefix = (Path(line).resolve() for line in bundled.stdout.decode().splitlines())
    if ffmpeg != (app / "runtime/ffmpeg/bin/ffmpeg.exe").resolve() or prefix != (app / "runtime/python").resolve():
        raise RuntimeError("packaged app does not use its bundled Python and FFmpeg")
    run_python(python, app, env, "-c", "from pathlib import Path; import os; from app.storage import Store\n"
               "from app.auth import create_user\nfrom app.input_models import UserCreate\n"
               "with Store(Path(os.environ['KDOG_DATA_DIR'])).connect(write=True) as db:\n"
               "    create_user(db,UserCreate(username='pilot',role='admin',password='Synthetic-install-only-42'))\n")
    case_id = None
    for run in range(2):
        with served([str(python), "-X", "utf8", "-m", "app.launcher"], app, env) as client:
            request = client()
            request("/api/auth/login", {"username": "pilot", "password": "Synthetic-install-only-42"})
            if run == 0:
                case = request("/api/cases", {"event_id": "S1-INSTALL", "participant_id": "0001", "dog_name": "설치 시험견"})
                if case["manifest"]["schema_version"] != "intake-4.0":
                    raise RuntimeError("new package created an old input edition")
                case_id = case["case_id"]
            elif request("/api/cases/" + case_id)["participant_id"] != "0001":
                raise RuntimeError("packaged restart lost data")
    return {"bundled_runtime_only": True, "unicode_space_path": True, "corruption_rejected_by_check": True,
            "environment_override_isolated": True, "http_login_create_restart": "passed",
            "supervisor_shutdown": "passed"}


def verify_online(package, root):
    """User-install ZIP: uv and FFmpeg come from PATH; Install.cmd downloads Python 3.14 and locked dependencies."""
    for tool in ("uv", "ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} must be on PATH to verify a user-install package")
    app = root / "새 설치 경로"
    manifest = unpack(package, app)
    if manifest.get("variant") != "online" or "python" in manifest or any(name.startswith("runtime/") for name in manifest["files"]):
        raise RuntimeError("user-install package must not bundle a runtime")
    for name in ("Install.cmd", "install.ps1", "Start.cmd", "오픈소스고지.txt", "backend/pyproject.toml", "backend/uv.lock"):
        if not (app / name).is_file():
            raise RuntimeError(f"package is missing {name}")
    env = {**os.environ, "KDOG_DATA_DIR": str(root / "data"), "GEMINI_API_KEY": "", "OPENAI_API_KEY": "",
           "ANTHROPIC_API_KEY": "", "PYTHONUTF8": "1", "UV_PROJECT_ENVIRONMENT": str(root / "wrong-env"),
           "PYTHONPATH": str(root / "wrong-path"), "PYTHONHOME": str(root / "wrong-home")}
    clean = {key: value for key, value in env.items() if key not in ("PYTHONHOME", "PYTHONPATH")}
    def run(*command, timeout=120):
        return subprocess.run([str(app / command[0]), *command[1:]], cwd=app, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout)
    early = run("Start.cmd", "--check")
    if early.returncode == 0 or b"Install.cmd" not in early.stdout + early.stderr:
        raise RuntimeError("Start.cmd before installation did not ask for Install.cmd")
    asset = app / "frontend/dist/index.html"
    original = asset.read_bytes()
    asset.write_bytes(b"corrupted release")
    try:
        damaged = run("Install.cmd", "-SkipAccounts", timeout=600)
        if damaged.returncode == 0 or b"hash mismatch" not in damaged.stdout + damaged.stderr or \
                (app / "backend/.venv").exists():
            raise RuntimeError("damaged release was not rejected before installation")
    finally:
        asset.write_bytes(original)
    installed = run("Install.cmd", "-SkipAccounts", timeout=600)
    if installed.returncode or "Installation complete" not in installed.stdout.decode("utf-8", errors="replace"):
        raise RuntimeError("Install.cmd failed: " + (installed.stdout + installed.stderr).decode("utf-8", errors="replace"))
    if (root / "wrong-env").exists():
        raise RuntimeError("installer used an unrelated UV_PROJECT_ENVIRONMENT")
    asset.write_bytes(b"corrupted release")
    try:
        damaged = run("Start.cmd", "--check")
        if damaged.returncode == 0 or "손상".encode() not in damaged.stdout + damaged.stderr:
            raise RuntimeError("damage after installation was not rejected by Start.cmd --check")
    finally:
        asset.write_bytes(original)
    checked = run("Start.cmd", "--check")
    if checked.returncode:
        raise RuntimeError("Start.cmd --check failed: " + (checked.stdout + checked.stderr).decode("utf-8", errors="replace"))
    backend, python = app / "backend", app / "backend/.venv/Scripts/python.exe"
    found = run_python(python, backend, clean, "-c", "import sys; from app import media; print(media.tool('ffmpeg')); "
                       "print(sys.prefix); print(sys.version_info[:2] == (3, 14))")
    tool, prefix, version = found.stdout.decode().splitlines()
    if tool != "ffmpeg" or Path(prefix).resolve() != (backend / ".venv").resolve() or version != "True":
        raise RuntimeError("installed app does not use its venv Python 3.14 and the PATH FFmpeg")
    run_python(python, backend, clean, "-c", "from pathlib import Path; import os; from app.storage import Store\n"
               "from app.auth import create_user\nfrom app.input_models import UserCreate\n"
               "with Store(Path(os.environ['KDOG_DATA_DIR'])).connect(write=True) as db:\n"
               "    create_user(db,UserCreate(username='pilot',role='admin',password='Synthetic-install-only-42'))\n")
    case_id = None
    for command, launch_env, kill_tree in (([str(python), "-X", "utf8", "-m", "app.launcher"], clean, False),
                                           ([str(app / "Start.cmd")], env, True)):
        with served(command, backend, launch_env, kill_tree=kill_tree, python=python) as client:
            request = client()
            request("/api/auth/login", {"username": "pilot", "password": "Synthetic-install-only-42"})
            if case_id is None:
                case = request("/api/cases", {"event_id": "S1-INSTALL", "participant_id": "0001", "dog_name": "설치 시험견"})
                if case["manifest"]["schema_version"] != "intake-4.0":
                    raise RuntimeError("new package created an old input edition")
                case_id = case["case_id"]
            elif request("/api/cases/" + case_id)["participant_id"] != "0001":
                raise RuntimeError("restart through Start.cmd lost data")
    return {"fresh_venv": True, "unicode_space_path": True, "start_before_install_rejected": True,
            "corruption_rejected_before_install": True, "corruption_rejected_by_check": True, "environment_override_isolated": True,
            "path_ffmpeg_and_venv_python": True, "http_login_create_restart": "passed", "supervisor_shutdown": "passed"}


def verify_issued(package, root):
    spec = importlib.util.spec_from_file_location("issue_release", ROOT / "scripts/issue_release.py")
    issuer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(issuer)
    passwords = {"verify-admin": secrets.token_urlsafe(18), "verify-dev": secrets.token_urlsafe(18)}
    issued = issuer.issue(package, "VERIFY", [("verify-admin", "admin", passwords["verify-admin"]),
                                              ("verify-dev", "developer", passwords["verify-dev"])], root / "issued")
    unpacked = root / "새 발행 패키지"
    with ZipFile(issued["path"]) as archive:
        names = archive.namelist()
        if any(name.startswith(("backend/", "resources/", "frontend/", "docs/")) or
               name in ("provision.json", "release.json", "Start.cmd") for name in names):
            raise RuntimeError("issued package exposes product file names")
        for name in names:
            content = archive.read(name)
            if SOURCE_MARKER in content or b"password_hash" in content or b"scrypt$" in content:
                raise RuntimeError(f"issued package exposes product content in {name}")
        archive.extractall(unpacked)
    install_root, desktop, data = root / "설치 위치", root / "바탕 화면", root / "발행 자료"
    env = isolated_env(root, data)
    def install(*answers):
        result = subprocess.run([str(unpacked / "Install.cmd"), "--install-root", str(install_root),
                                 "--shortcut-dir", str(desktop)], cwd=unpacked, env=env, timeout=600,
                                input="".join(answer + "\n" for answer in answers).encode(), capture_output=True)
        return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")
    def untouched():
        return not install_root.exists() and not desktop.exists() and not data.exists()
    code, output = install("KDOG-" + "-".join(["11111"] * 5), "")
    if code == 0 or "키가 맞지 않습니다" not in output or not untouched():
        raise RuntimeError("a wrong key created files: " + output)
    payload = unpacked / "payload.kdog"
    original = payload.read_bytes()
    try:
        for altered in (original.replace(b'"VERIFY"', b'"VERIFZ"', 1), original[:-1] + bytes([original[-1] ^ 1])):
            payload.write_bytes(altered)
            code, output = install(issued["key"], "")
            if code == 0 or not untouched():
                raise RuntimeError("a tampered payload was installed: " + output)
    finally:
        payload.write_bytes(original)
    code, output = install(issued["key"])
    if code or "바탕화면의 K-DOG 아이콘" not in output:
        raise RuntimeError("issued install failed or made no shortcut: " + output)
    target = install_root / f"{issued['version']}-{issued['commit'][:7]}"
    if not (target / "Start.cmd").is_file() or list(target.rglob("provision.json")) or list(install_root.glob(".tmp-*")):
        raise RuntimeError("installed folder is incomplete or kept provisioning data")
    shell = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    link = subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-Command",
                           "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                           "(New-Object -ComObject WScript.Shell).CreateShortcut($env:KDOG_LINK).TargetPath"],
                          env={**env, "KDOG_LINK": str(desktop / "K-DOG.lnk")}, capture_output=True, timeout=60)
    shown = link.stdout.decode("utf-8").strip()
    if not shown or Path(shown).resolve() != (target / "Start.cmd").resolve():
        raise RuntimeError(f"desktop shortcut does not start the installed version: {shown!r} {link.stderr!r}")
    with served([str(target / "Start.cmd")], target, env, kill_tree=True) as client:
        admin, developer = client(), client()
        admin("/api/auth/login", {"username": "verify-admin", "password": passwords["verify-admin"]})
        case_id = admin("/api/cases", {"event_id": "S1-ISSUED", "participant_id": "0002", "dog_name": "발행 시험견"})["case_id"]
        developer("/api/auth/login", {"username": "verify-dev", "password": passwords["verify-dev"]})
        developer("/api/developer/settings")
    code, output = install(issued["key"])
    if code or "기존 비밀번호가 유지" not in output:
        raise RuntimeError("reinstalling the same package did not keep accounts: " + output)
    with served([str(target / "Start.cmd")], target, env, kill_tree=True) as client:
        admin = client()
        admin("/api/auth/login", {"username": "verify-admin", "password": passwords["verify-admin"]})
        if admin("/api/cases/" + case_id)["participant_id"] != "0002":
            raise RuntimeError("reinstall lost data")
    return {"issued_package_sealed": True, "wrong_key_and_tampering_change_nothing": True,
            "key_install_accounts_shortcut": "passed", "developer_settings_access": "passed",
            "reinstall_keeps_data_and_accounts": "passed"}


def verify(package):
    with ZipFile(package) as archive:
        variant = json.loads(archive.read("release.json")).get("variant", "portable")
    if variant == "online":
        with tempfile.TemporaryDirectory(prefix="kdog-s1-online-") as temporary:
            result = {"package": str(package.resolve()), "variant": variant, **verify_online(package, Path(temporary))}
        print(json.dumps({**result, "external_ai_calls": 0, "spec": "20261002", "s1_catalog_report_assets": "passed",
                          "scope": "new folder and venv on current Windows host with uv/FFmpeg on PATH and internet; "
                                   "not a clean OS/second PC"}, ensure_ascii=False))
        return
    with tempfile.TemporaryDirectory(prefix="kdog-s1-clean-") as temporary:
        result = {"package": str(package.resolve()), **verify_plain(package, Path(temporary) / "plain")}
    with tempfile.TemporaryDirectory(prefix="kdog-s1-issued-") as temporary:
        result.update(verify_issued(package, Path(temporary)))
    print(json.dumps({**result, "external_ai_calls": 0, "spec": "20261002", "s1_catalog_report_assets": "passed",
                      "scope": "new folders on current Windows host, PATH without uv/Python/FFmpeg; not a clean OS/second PC"},
                     ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="build_release.py로 만든 평문 ZIP (포터블 또는 사용자 설치형)")
    verify(parser.parse_args().package)
