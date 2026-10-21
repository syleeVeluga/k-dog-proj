"""Native smoke check: backend/.venv/bin/python Verify.py (no provider calls)."""

import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler
import uuid
from unittest.mock import patch


def verify(root):
    if sys.platform != "darwin":
        raise ValueError("Native verification requires macOS.")
    root = root.resolve()
    manifest = json.loads((root / "release.json").read_text(encoding="utf-8"))
    if manifest.get("variant") != "macos-online":
        raise ValueError("Not a macOS user-install package.")
    for name, digest in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Missing/damaged release file: {name}")
    sys.path.insert(0, str(root / "backend"))
    from app import macos_keychain, media, secrets
    from app.launcher import preflight
    preflight()
    service = "K-DOG verification " + uuid.uuid4().hex
    try:
        key = macos_keychain.keychain_key(service=service, create=True)
        if key != macos_keychain.keychain_key(service=service):
            raise ValueError("Keychain read mismatch.")
        with patch.object(macos_keychain, "keychain_key", return_value=key):
            ciphertext = secrets.protect(b"synthetic-key-only")
            if secrets.protect(ciphertext, decrypt=True) != b"synthetic-key-only":
                raise ValueError("Vault roundtrip failed.")
    finally:
        subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", service, "-a", "aes256-v1"],
                       check=False, capture_output=True)
    with tempfile.TemporaryDirectory(prefix="kdog-mac-verify-") as temporary:
        temporary = Path(temporary)
        video = temporary / "synthetic.mp4"
        subprocess.run([media.tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=s=160x120:r=10",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libx264", "-c:a", "aac",
                        str(video)], check=True, timeout=30)
        if media.probe(video)["audio_status"] != "present":
            raise ValueError("Synthetic audio missing.")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = [str(root / "Start.command"), "--no-browser", "--port", str(port),
                   "--data-dir", str(temporary / "data")]
        with (temporary / "launcher.log").open("w+") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while True:
                    try:
                        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                            if json.load(response)["service"] != "K-DOG":
                                raise ValueError("Unexpected health response.")
                        break
                    except OSError:
                        if process.poll() is not None or time.monotonic() > deadline:
                            log.seek(0)
                            raise ValueError(log.read()) from None
                        time.sleep(0.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=15)
        deadline = time.monotonic() + 10
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    pass
            except OSError:
                break
            if time.monotonic() > deadline:
                raise ValueError("API survived launcher termination.")
            time.sleep(0.2)
    print("PASS: hashes, native Keychain, FFmpeg/audio, launcher startup/termination. No provider calls.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, nargs="?", default=Path(__file__).resolve().parent)
    verify(parser.parse_args().package)
