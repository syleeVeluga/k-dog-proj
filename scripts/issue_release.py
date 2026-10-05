"""Issue a per-customer encrypted K-DOG package and its one-time install key from a verified portable ZIP.

Only public software (runtime/ and the open-source notice) and the installer stay readable. Product files
and the account list (password hashes only) are sealed with the key. The key is printed once, never stored.
"""

import argparse
from datetime import datetime, timezone
from getpass import getpass
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.auth import password_hash  # noqa: E402  the app's own scrypt format

_spec = importlib.util.spec_from_file_location("kdog_install", ROOT / "scripts/windows/kdog_install.py")
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)

PUBLIC = ("runtime/", "오픈소스고지.txt")


def crlf(path):
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def issue(plain_zip: Path, customer: str, accounts: list[tuple[str, str, str]], out_dir: Path) -> dict:
    """accounts: (username, role, password) with exactly one admin and at most one developer."""
    if not re.fullmatch(r"[A-Za-z0-9-]{1,32}", customer):
        raise ValueError("고객 ID는 영문·숫자·하이픈 1~32자입니다.")
    if sorted(role for _, role, _ in accounts) not in (["admin"], ["admin", "developer"]) or \
            len({username for username, _, _ in accounts}) != len(accounts):
        raise ValueError("관리자 계정 1개와 선택 개발자 계정 1개를 서로 다른 아이디로 지정하세요.")
    for username, _role, password in accounts:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", username) or not 12 <= len(password) <= 256:
            raise ValueError(f"{username}: 아이디(영문·숫자·_-)와 비밀번호 길이(12~256자)를 확인하세요.")
    with ZipFile(plain_zip) as plain:
        manifest = json.loads(plain.read("release.json"))
        names = plain.namelist()
        if set(names) != set(manifest["files"]) | {"release.json"} or any(
                hashlib.sha256(plain.read(name)).hexdigest() != digest for name, digest in manifest["files"].items()):
            raise ValueError("평문 패키지가 release.json과 다릅니다. build_release.py로 다시 만드세요.")
        # The installer comes from this checkout; the product must already carry what it needs.
        crypto = r"runtime/python/Lib/site-packages/cryptography-[^/]+\.dist-info/METADATA"
        if not any(re.fullmatch(crypto, name) for name in names) or \
                b"provision-accounts" not in plain.read("backend/app/manage.py"):
            raise ValueError("평문 패키지가 발행 설치를 지원하지 않습니다 (cryptography·provision-accounts 없음). 현재 코드로 다시 만드세요.")
        version, commit = manifest["version"], manifest["commit"]
        provision = {"format": "kdog-provision-1", "customer": customer,
                     "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "accounts": [{"username": username, "role": role, "password_hash": password_hash(password)}
                                  for username, role, password in accounts]}
        product = BytesIO()
        with ZipFile(product, "w", ZIP_DEFLATED) as sealed:
            for name in names:
                if not name.startswith(PUBLIC):
                    sealed.writestr(name, plain.read(name))
            sealed.writestr("provision.json", json.dumps(provision, ensure_ascii=False))
        key = installer.new_key()
        payload = installer.seal(product.getvalue(), key, customer=customer, version=version, commit=commit)
        stem = f"K-DOG-{customer}-v{version}-{commit[:7]}"
        target = out_dir / f"{stem}.zip"
        if target.exists():
            raise ValueError(f"같은 이름의 발행 패키지가 이미 있습니다: {target}. 지우거나 --out으로 다른 폴더를 지정하세요.")
        out_dir.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        with ZipFile(partial, "w", ZIP_DEFLATED) as issued:
            issued.writestr("Install.cmd", crlf(ROOT / "scripts/windows/Install.cmd"))
            issued.writestr("설치안내.txt", b"\xef\xbb\xbf" + crlf(ROOT / "scripts/windows/설치안내.txt"))
            issued.write(ROOT / "scripts/windows/kdog_install.py", "installer/kdog_install.py")
            for name in names:
                if name.startswith(PUBLIC):
                    issued.writestr(name, plain.read(name))
            issued.writestr("payload.kdog", payload, compress_type=ZIP_STORED)
        partial.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + ".sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    record = {"customer": customer, "version": version, "commit": commit, "issued_at": provision["issued_at"],
              "package": target.name, "sha256": digest,
              "plain_package_sha256": hashlib.sha256(plain_zip.read_bytes()).hexdigest(),
              "installer_sha256": hashlib.sha256((ROOT / "scripts/windows/kdog_install.py").read_bytes()).hexdigest(),
              "accounts": [{"username": username, "role": role} for username, role, _ in accounts]}
    (out_dir / f"{stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**record, "path": target, "key": installer.display_key(key)}


def ask_password(username, role):
    password = getpass(f"{username} ({role}) 비밀번호 (12~256자): ")
    if password != getpass("비밀번호 확인: ") or not 12 <= len(password) <= 256:
        raise ValueError("비밀번호 확인과 길이(12~256자)를 확인하세요.")
    return password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plain_zip", type=Path, help="build_release.py로 만든 평문 포터블 ZIP")
    parser.add_argument("--customer", required=True, help="고객 ID (영문·숫자·하이픈 1~32자)")
    parser.add_argument("--admin", required=True, help="관리자 계정 아이디 (필수)")
    parser.add_argument("--developer", help="AI 키 등록용 개발자 계정 아이디 (선택)")
    parser.add_argument("--out", type=Path, help="결과 폴더 (기본: releases/issued/<고객 ID>)")
    args = parser.parse_args()
    try:
        accounts = [(args.admin, "admin", ask_password(args.admin, "admin"))]
        if args.developer:
            accounts.append((args.developer, "developer", ask_password(args.developer, "developer")))
        result = issue(args.plain_zip, args.customer, accounts, args.out or ROOT / "releases/issued" / args.customer)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"발행 실패: {exc}\n")
    print(f"발행 패키지: {result['path']}")
    print(f"SHA-256: {result['sha256']}")
    print(f"발행 키: {result['key']}")
    print("※ 발행 키는 여기서 한 번만 표시되며 어디에도 저장되지 않습니다.")
    print("※ 키와 SHA-256은 ZIP과 다른 경로(문자·전화 등)로 전달하세요. 같은 메일로 보내면 암호화 의미가 없습니다.")
    print("※ 이미 설치된 PC에 같은 아이디가 있으면 그 계정의 기존 비밀번호가 유지됩니다.")


if __name__ == "__main__":
    main()
