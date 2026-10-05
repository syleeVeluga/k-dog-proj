"""Install an issued K-DOG package: one install key decrypts the product, then accounts and a desktop shortcut.

The package format lives only here; scripts/issue_release.py imports these functions to seal packages.
Nothing is written to disk until the key has decrypted and authenticated the payload.
"""

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from uuid import uuid4
from zipfile import ZipFile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


MAGIC = b"KDOGPKG1"
FORMAT = "kdog-issued-1"
# Crockford Base32 without I, L, O, U: 25 characters carry a 125-bit random key.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
KEY_LENGTH = 25
# Fixed here, never read from the header: the key is already uniformly random, so HKDF suffices.
HKDF_INFO = b"K-DOG issued package v1"


class PackageError(Exception):
    """The payload file is not an issued K-DOG package or its header is damaged."""


class WrongKey(Exception):
    """The key does not decrypt the payload (or the payload was altered)."""


def new_key() -> str:
    value = secrets.randbits(5 * KEY_LENGTH)
    return "".join(ALPHABET[(value >> 5 * index) & 31] for index in reversed(range(KEY_LENGTH)))


def display_key(key: str) -> str:
    return "KDOG-" + "-".join(key[index:index + 5] for index in range(0, KEY_LENGTH, 5))


def normalize_key(text: str) -> str | None:
    """Accept the key as typed: optional KDOG prefix, any case, hyphens and spaces, O for 0 and I/L for 1."""
    value = text.strip().upper()
    if value.startswith("KDOG"):
        value = value[4:]
    value = re.sub(r"[\s-]", "", value).translate(str.maketrans("OIL", "011"))
    return value if len(value) == KEY_LENGTH and all(char in ALPHABET for char in value) else None


def _cipher(key: str, salt: bytes) -> AESGCM:
    return AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=HKDF_INFO).derive(key.encode("ascii")))


def seal(product: bytes, key: str, *, customer: str, version: str, commit: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    header = json.dumps({"format": FORMAT, "customer": customer, "version": version, "commit": commit,
                         "salt": salt.hex(), "nonce": nonce.hex()}, sort_keys=True).encode("utf-8")
    # The stored header bytes themselves are the associated data, so any header change fails authentication.
    return MAGIC + len(header).to_bytes(4, "big") + header + _cipher(key, salt).encrypt(nonce, product, header)


def read_header(data: bytes) -> tuple[dict, bytes, bytes]:
    size = int.from_bytes(data[8:12], "big") if len(data) >= 12 else 0
    if data[:8] != MAGIC or not 0 < size <= 4096 or len(data) < 12 + size + 16:
        raise PackageError
    raw = data[12:12 + size]
    try:
        header = json.loads(raw)
    except ValueError:
        raise PackageError from None
    if not (isinstance(header, dict) and header.get("format") == FORMAT
            and all(isinstance(header.get(name), str) for name in ("customer", "version", "commit"))
            and re.fullmatch(r"[0-9a-f]{32}", str(header.get("salt"))) and re.fullmatch(r"[0-9a-f]{24}", str(header.get("nonce")))):
        raise PackageError
    return header, raw, data[12 + size:]


def unseal(data: bytes, key: str) -> tuple[dict, bytes]:
    header, raw, ciphertext = read_header(data)
    try:
        return header, _cipher(key, bytes.fromhex(header["salt"])).decrypt(bytes.fromhex(header["nonce"]), ciphertext, raw)
    except InvalidTag:
        raise WrongKey from None


def clean_env() -> dict:
    env = {name: value for name, value in os.environ.items() if name not in ("PYTHONPATH", "PYTHONHOME")}
    return {**env, "PYTHONUTF8": "1"}


def run_python(folder: Path, *arguments, stdin: bytes | None = None):
    return subprocess.run([str(folder / "runtime/python/python.exe"), "-X", "utf8", *arguments], cwd=folder,
                          env=clean_env(), input=stdin, capture_output=True, timeout=300)


def check(folder: Path) -> bool:
    result = run_python(folder, "-m", "app.launcher", "--check")
    if result.returncode:
        print((result.stdout + result.stderr).decode("utf-8", errors="replace").strip())
    return result.returncode == 0


def ask_key(data: bytes) -> bytes | None:
    while True:
        try:
            text = input("발행 키를 입력하세요 (취소하려면 Enter만 누르세요): ")
        except EOFError:
            text = ""
        if not text.strip():
            return None
        key = normalize_key(text)
        if key is None:
            print("키 형식이 맞지 않습니다. KDOG-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX 형태의 25자를 확인하세요.")
            continue
        try:
            return unseal(data, key)[1]
        except WrongKey:
            print("키가 맞지 않습니다. 다시 입력하세요. (키가 맞는데도 계속 실패하면 받은 ZIP의 SHA-256을 다시 확인하세요.)")


def install_files(archive: ZipFile, package: Path, root: Path, target: Path) -> bool:
    for leftover in root.glob(".tmp-*"):
        shutil.rmtree(leftover, ignore_errors=True)
    if target.exists():
        print("같은 버전이 이미 설치되어 있어 설치 파일 확인만 다시 합니다.")
        if check(target):
            return True
        print(f"설치 폴더 확인에 실패했습니다: {target}\n이 폴더를 지운 뒤 다시 설치하세요.")
        return False
    temporary = root / f".tmp-{uuid4().hex[:12]}"
    for info in archive.infolist():
        # Account information stays in memory; it never lands in the program folder.
        if info.filename == "provision.json":
            continue
        if not (temporary / info.filename).resolve().is_relative_to(temporary.resolve()):
            raise PackageError
        archive.extract(info, temporary)
    shutil.copytree(package / "runtime", temporary / "runtime")
    shutil.copy2(package / "오픈소스고지.txt", temporary / "오픈소스고지.txt")
    if not check(temporary):
        shutil.rmtree(temporary, ignore_errors=True)
        print("설치 파일 확인에 실패했습니다. ZIP을 다시 받아 SHA-256을 확인한 뒤 설치하세요.")
        return False
    # Antivirus or the search indexer may hold a new file for a moment; retry the final rename.
    for _ in range(20):
        try:
            temporary.rename(target)
            return True
        except OSError:
            time.sleep(0.5)
    print(f"설치 폴더 이름을 바꾸지 못했습니다: {temporary}\n잠시 뒤 Install.cmd를 다시 실행하세요.")
    return False


def shortcut(target: Path, directory: Path | None) -> Path | None:
    script = ("$d = if ($env:KDOG_SHORTCUT_DIR) { $env:KDOG_SHORTCUT_DIR } else { [Environment]::GetFolderPath('Desktop') }; "
              "$p = Join-Path $d 'K-DOG.lnk'; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($p); "
              "$s.TargetPath = $env:KDOG_START; $s.WorkingDirectory = $env:KDOG_HOME; $s.Description = 'K-DOG'; "
              "$s.Save(); [Console]::OutputEncoding = [Text.Encoding]::UTF8; Write-Output $p")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    env = {**os.environ, "KDOG_START": str(target / "Start.cmd"), "KDOG_HOME": str(target),
           "KDOG_SHORTCUT_DIR": str(directory) if directory else ""}
    try:
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-Command", script], env=env, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    path = result.stdout.decode("utf-8", errors="replace").strip()
    return Path(path) if result.returncode == 0 and path and Path(path).is_file() else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="K-DOG 발행 패키지 설치")
    parser.add_argument("--install-root", type=Path,
                        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs/K-DOG")
    parser.add_argument("--shortcut-dir", type=Path, help="바로가기 폴더 (기본: 바탕화면)")
    args = parser.parse_args(argv)
    package = Path(__file__).resolve().parents[1]
    try:
        data = (package / "payload.kdog").read_bytes()
        header = read_header(data)[0]
    except (OSError, PackageError):
        print("설치 패키지가 손상되었거나 완전하지 않습니다. ZIP 전체를 다시 풀거나 다시 받아 SHA-256을 확인하세요.")
        return 1
    print(f"K-DOG {header['version']} ({header['commit'][:7]}) 설치를 시작합니다.")
    product = ask_key(data)
    if product is None:
        print("설치를 취소했습니다. 아무것도 바뀌지 않았습니다.")
        return 1
    target = args.install_root / f"{header['version']}-{header['commit'][:7]}"
    try:
        with ZipFile(BytesIO(product)) as archive:
            provision = archive.read("provision.json")
            args.install_root.mkdir(parents=True, exist_ok=True)
            if not install_files(archive, package, args.install_root, target):
                return 1
    except (OSError, ValueError, KeyError, PackageError) as exc:
        print(f"설치에 실패했습니다: {exc}")
        return 1
    accounts = run_python(target, "-m", "app.manage", "provision-accounts", stdin=provision)
    print((accounts.stdout + accounts.stderr).decode("utf-8", errors="replace").strip())
    if accounts.returncode:
        print("계정을 만들지 못했습니다. 프로그램 파일은 설치되었습니다. 문의처: 벨루가 veluga.app@veluga.io")
        return 1
    link = shortcut(target, args.shortcut_dir)
    print()
    if link:
        print(f"설치를 마쳤습니다. 바탕화면의 K-DOG 아이콘으로 실행하세요. ({link})")
    else:
        print(f"설치를 마쳤습니다. 바로가기를 만들지 못했으니 다음 파일을 실행하세요:\n{target / 'Start.cmd'}")
    print("새 계정의 비밀번호는 별도로 전달받은 것을 사용하세요.")
    print("K-DOG가 이미 실행 중이면 그 창을 닫고 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
