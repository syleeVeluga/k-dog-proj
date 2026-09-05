"""Trusted local provisioning and loopback-first application launcher."""

import argparse
from getpass import getpass
import os
from pathlib import Path
import sqlite3

import uvicorn

from app.api import DEFAULT_DATA, create_app
from app.auth import create_user, password_hash
from app.input_models import UserCreate
from app.storage import Store


def main():
    parser = argparse.ArgumentParser(description="K-DOG 로컬 실행·계정 관리")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("KDOG_DATA_DIR", DEFAULT_DATA)))
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("create-user")
    add.add_argument("username")
    add.add_argument("--role", choices=["operator", "reviewer", "admin", "developer"], required=True)
    reset = sub.add_parser("reset-password")
    reset.add_argument("username")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--public-origin")
    args = parser.parse_args()
    if args.command == "serve":
        if args.host not in ("127.0.0.1", "localhost", "::1") and not args.public_origin:
            parser.error("내부망 접속에는 HTTPS --public-origin을 명시하세요.")
        origin = args.public_origin or f"http://{'[::1]' if args.host == '::1' else args.host}:{args.port}"
        app = create_app(args.data_dir, public_origin=origin)
        uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False, access_log=False)
        return
    password = getpass("새 비밀번호 (12자 이상): ")
    if password != getpass("비밀번호 확인: ") or not 12 <= len(password) <= 256:
        parser.error("비밀번호 확인과 길이(12~256자)를 확인하세요.")
    store = Store(args.data_dir)
    try:
        with store.connect(write=True) as db:
            if args.command == "create-user":
                create_user(db, UserCreate(username=args.username, password=password, role=args.role))
                store.audit(db, args.username, args.username, "user.local_create", {"role": args.role})
            else:
                row = db.execute("SELECT username FROM users WHERE username=?", (args.username,)).fetchone()
                if row is None:
                    parser.error("존재하지 않는 계정입니다.")
                db.execute("UPDATE users SET password_hash=?,session_hash=NULL,session_expires=NULL,"
                           "failed_logins=0,locked_until=0 WHERE username=?", (password_hash(password), args.username))
                store.audit(db, args.username, args.username, "user.local_password_reset", {})
    except sqlite3.IntegrityError:
        parser.error("이미 등록된 계정입니다.")
    print("계정을 저장했습니다.")


if __name__ == "__main__":
    main()
