"""Build an allowlisted Windows ZIP; never package local runtime data.

portable (default): bundled Python and FFmpeg, nothing to install. online: the user installs uv and FFmpeg, and
Install.cmd downloads Python 3.14 and the locked dependencies into backend/.venv (the S15 installation).
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "releases/.cache"

# Official signed CPython embeddable; checked against python.org's published SHA-256 (2026-10-05).
PYTHON_VERSION = "3.14.8"
PYTHON_ARCHIVE = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ARCHIVE}"
PYTHON_SHA256 = "a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310"
# With a ._pth file the interpreter ignores PYTHONPATH, PYTHONHOME and user site-packages.
PYTHON_PATHS = ("python314.zip", ".", r"Lib\site-packages", r"..\..\backend")
# D00 output (scripts/ffmpeg/build-ffmpeg.sh), verified against its build.json before use.
FFMPEG_BUILD = CACHE / "ffmpeg-9.0.2-kdog"

# Historical fixtures stay in the repository, outside the S1 product package.
# Retain only historical assets still needed by raw-input reset or source extraction.
RETIRED_FILES = frozenset({
    "resources/catalogs/behavior-v1.json", "resources/catalogs/behavior-v2.json",
    "resources/catalogs/survey-v1.json", "resources/rules/pending-v1.json",
    "resources/rules/preprocess-v1.json", "resources/rules/preprocess-v2.json",
    "resources/rules/preprocess-v3.json", "resources/rules/scoring-v1.json",
    "resources/rules/scoring-v2.json", "resources/report-presentation-v1.json",
    "resources/mappings/results-v3.json",
    "resources/mappings/survey-behavior-v3.json",
})
OPERATING_DOCUMENTS = frozenset({
    "README.md", "docs/DEVELOPMENT.md", "docs/PILOT_OPERATIONS.md",
    "docs/K-DOG_개발기준변경검토_v1.0_20261003.md",
    "docs/개발반영_20261003/검증이미지/S17_외부비교_모바일_합성.png",
    "docs/개발반영_20261003/검증이미지/S17_PDF_외부비교_합성.png",
})


def product_file(name):
    return name not in RETIRED_FILES and (
        name.startswith("backend/app/") and name.endswith(".py") or
        name.startswith("resources/") and Path(name).suffix in (".json", ".ttf", ".txt", ".md", ".html", ".css") or
        name in OPERATING_DOCUMENTS or
        name.startswith("docs/개발반영_20261003/") and name.endswith(".md")
    )


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def python_archive():
    path = CACHE / PYTHON_ARCHIVE
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        with urlopen(PYTHON_URL, timeout=120) as response:
            partial.write_bytes(response.read())
        partial.replace(path)
    if sha256(path) != PYTHON_SHA256:
        raise ValueError(f"{path} SHA-256이 고정값과 다릅니다. 파일을 지우고 다시 실행하세요.")
    return path


def python_runtime(staging):
    """Embeddable CPython plus the locked, hash-pinned binary wheels; nothing is downloaded at install time."""
    python = staging / "runtime/python"
    with ZipFile(python_archive()) as archive:
        archive.extractall(python)
    (python / "python314._pth").write_text("\n".join(PYTHON_PATHS) + "\n", encoding="utf-8")
    requirements = staging / "requirements.txt"
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("릴리즈 빌드에는 uv가 필요합니다 (docs/DEVELOPMENT.md).")
    subprocess.run([uv, "export", "--locked", "--no-dev", "--format", "requirements-txt", "--output-file",
                    str(requirements)], cwd=ROOT / "backend", check=True, stdout=subprocess.DEVNULL)
    subprocess.run([uv, "pip", "install", "--python", str(python / "python.exe"), "--target",
                    str(python / "Lib/site-packages"), "--require-hashes", "--no-deps", "--only-binary", ":all:",
                    "--no-config", "--requirements", str(requirements)], cwd=staging, check=True)
    # Console-script launchers embed the staging interpreter path; the app runs modules with -m instead.
    shutil.rmtree(python / "Lib/site-packages/bin", ignore_errors=True)
    (python / "Lib/site-packages/.lock").unlink(missing_ok=True)
    files = {"runtime/python/" + path.relative_to(python).as_posix(): path
             for path in python.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    # The embeddable LICENSE.txt omits bundled OpenSSL, expat, libmpdec, zstd and others; ship CPython's full list.
    files["runtime/licenses/python/license.rst"] = ROOT / f"scripts/windows/licenses/python-{PYTHON_VERSION}-license.rst"
    return files


def ffmpeg_runtime():
    manifest_path = FFMPEG_BUILD / "build.json"
    if not manifest_path.is_file():
        raise ValueError(f"FFmpeg 빌드 결과가 없습니다: {FFMPEG_BUILD} (scripts/ffmpeg/README.md)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = {path.relative_to(FFMPEG_BUILD).as_posix(): path for path in FFMPEG_BUILD.rglob("*")
              if path.is_file() and path != manifest_path}
    if actual.keys() != manifest["files"].keys() or any(
            sha256(actual[name]) != digest for name, digest in manifest["files"].items()):
        raise ValueError("FFmpeg 빌드 결과가 build.json과 다릅니다. scripts/ffmpeg/build-ffmpeg.sh로 다시 빌드하세요.")
    return {"runtime/ffmpeg/" + name: path for name, path in {**actual, "build.json": manifest_path}.items()}


def notice(staging, files, fixed, license_dir="runtime/licenses"):
    """Korean open-source notice: fixed text plus the exact bundled Python and npm package lists.

    A user-install package keeps npm licenses outside runtime/, which marks a bundled runtime to the app.
    """
    lines, python = [fixed.read_text(encoding="utf-8").rstrip("\n")], []
    for name in sorted(files):
        if re.fullmatch(r"runtime/python/Lib/site-packages/[^/]+\.dist-info/METADATA", name):
            metadata = files[name].read_text(encoding="utf-8").split("\n\n", 1)[0].splitlines()
            field = lambda key: next((line.split(": ", 1)[1] for line in metadata if line.startswith(key + ": ")), "")
            python.append(f"- {field('Name')} {field('Version')}: "
                          f"{field('License-Expression') or field('License') or 'dist-info 라이선스 파일 참조'}")
    if python:
        lines += ["", "■ 동봉한 Python 패키지 (라이선스 파일: runtime\\python\\Lib\\site-packages\\<이름>-<버전>.dist-info)",
                  *python]
    lines += ["", f"■ 화면(frontend\\dist)에 번들된 npm 패키지 (라이선스 전문: {license_dir.replace('/', '\\')}\\npm\\<이름>)"]
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    for key, package in sorted(lock["packages"].items()):
        if not key or package.get("dev") or package.get("optional"):
            continue
        name = key.rsplit("node_modules/", 1)[1]
        lines.append(f"- {name} {package['version']}: {package.get('license', '라이선스 파일 참조')}")
        licenses = [path for path in (ROOT / "frontend" / key).iterdir() if path.is_file() and
                    path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))]
        if not licenses:
            raise ValueError(f"npm 패키지 라이선스 파일이 없습니다: {name}")
        for path in licenses:
            files[f"{license_dir}/npm/{name}/{path.name}"] = path
    target = staging / "오픈소스고지.txt"
    target.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig", newline="")
    files["오픈소스고지.txt"] = target


def build(destination, variant="portable"):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("패키지 대상 파일이 이미 존재합니다.")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        raise ValueError("릴리즈 패키지는 커밋된 깨끗한 작업 트리에서 생성해야 합니다.")
    subprocess.run([shutil.which("npm.cmd") or shutil.which("npm"), "run", "build"],
                   cwd=ROOT / "frontend", check=True)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    files = {name: ROOT / name for name in tracked if product_file(name)}
    for name in ("README.md", "docs/PILOT_OPERATIONS.md"):
        files[name] = ROOT / name
    if variant == "online":
        # The user's Install.cmd runs uv sync --locked; a stale lock must fail here, not on their PC.
        uv = shutil.which("uv")
        if not uv:
            raise ValueError("사용자 설치형 빌드에는 uv가 필요합니다 (docs/DEVELOPMENT.md).")
        subprocess.run([uv, "lock", "--check"], cwd=ROOT / "backend", check=True)
        for name in ("backend/pyproject.toml", "backend/uv.lock"):
            files[name] = ROOT / name
        for name in ("Install.cmd", "install.ps1", "Start.cmd"):
            files[name] = ROOT / "scripts/windows/online" / name
    else:
        files["Start.cmd"] = ROOT / "scripts/windows/Start.cmd"
    files.update({path.relative_to(ROOT).as_posix(): path for path in (ROOT / "frontend/dist").rglob("*") if path.is_file()})
    with (ROOT / "backend/pyproject.toml").open("rb") as project_file:
        version = tomllib.load(project_file)["project"]["version"]
    with tempfile.TemporaryDirectory(prefix="kdog-release-") as temporary:
        staging = Path(temporary)
        if variant == "online":
            notice(staging, files, ROOT / "scripts/windows/online/오픈소스고지.txt", "licenses")
        else:
            files.update(python_runtime(staging))
            files.update(ffmpeg_runtime())
            notice(staging, files, ROOT / "scripts/windows/오픈소스고지.txt")
        manifest = {"format": "kdog-release-1", "variant": variant, "version": version,
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
            "working_tree_dirty": False, **({"python": PYTHON_VERSION} if variant == "portable" else {}),
            "files": {name: sha256(path) for name, path in sorted(files.items())}}
        destination.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(destination, "x", ZIP_DEFLATED) as archive:
            for name, path in sorted(files.items()):
                archive.write(path, name)
            archive.writestr("release.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    digest = sha256(destination)
    destination.with_suffix(destination.suffix + ".sha256").write_text(digest + "  " + destination.name + "\n", encoding="utf-8")
    print(json.dumps({"package": str(destination), "files": len(files), "bytes": destination.stat().st_size,
                      "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--variant", choices=("portable", "online"), default="portable",
                        help="portable: Python·FFmpeg 내장 (기본). online: 사용자가 uv·FFmpeg를 설치하고 설치 때 인터넷 사용")
    args = parser.parse_args()
    build(args.destination, args.variant)
