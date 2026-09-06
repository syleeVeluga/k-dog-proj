"""Build an allowlisted Windows online-install ZIP; never package local runtime data."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[1]


def build(destination):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("패키지 대상 파일이 이미 존재합니다.")
    subprocess.run([shutil.which("npm.cmd") or shutil.which("npm"), "run", "build"],
                   cwd=ROOT / "frontend", check=True)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    files = {name: ROOT / name for name in tracked if (
        name.startswith("backend/app/") and name.endswith(".py") or
        name.startswith("resources/") and Path(name).suffix in (".json", ".ttf", ".txt", ".md")
    )}
    # New application files are included before the release commit, without globbing secrets.
    for name in ("launcher.py", "usage.py"):
        files[f"backend/app/{name}"] = ROOT / "backend/app" / name
    for name in ("backend/pyproject.toml", "backend/uv.lock", "docs/PILOT_OPERATIONS.md"):
        files[name] = ROOT / name
    for name in ("Install.cmd", "Start.cmd", "install.ps1"):
        files[name] = ROOT / "scripts/windows" / name
    files.update({path.relative_to(ROOT).as_posix(): path for path in (ROOT / "frontend/dist").rglob("*") if path.is_file()})
    manifest = {"format": "kdog-release-1", "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "files": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "x", ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr("release.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(digest + "  " + destination.name + "\n", encoding="utf-8")
    print(json.dumps({"package": str(destination), "files": len(files), "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)
