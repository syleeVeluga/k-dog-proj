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
    from app.launcher import watch_supervisor
    watch_supervisor()
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
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true", help="대기 실행 하나를 처리한 뒤 종료")
    backup = sub.add_parser("backup", help="자료와 DB를 새 폴더에 검증하여 백업 (키 제외)")
    backup.add_argument("destination", type=Path)
    backup.add_argument("--actor", required=True, help="기록에 사용할 운영 관리자 계정")
    restore = sub.add_parser("restore", help="현재 --data-dir 삭제 목록을 재적용하여 새 폴더에 복원")
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path)
    clean = sub.add_parser("clean", help="API·worker 종료 후 미참조 파일 정리")
    clean.add_argument("--purge-deleted", action="store_true", help="삭제 요청된 참가자 DB·파일도 영구 삭제")
    sub.add_parser("recovery-status")
    usage = sub.add_parser("usage-report", help="행사·참가자·시도별 사용량과 명시한 단가 추정 JSON")
    usage.add_argument("--event-id")
    usage.add_argument("--prices", type=Path, help="통화·출처·모델별 계량 단가 JSON")
    args = parser.parse_args()
    if args.command == "usage-report":
        import json
        from app.usage import summarize
        if not (args.data_dir / "kdog.sqlite3").is_file():
            parser.error("현재 데이터 DB가 필요합니다.")
        try:
            prices = json.loads(args.prices.read_text(encoding="utf-8-sig")) if args.prices else None
            print(json.dumps(summarize(Store(args.data_dir), event_id=args.event_id, prices=prices), ensure_ascii=False, indent=2))
        except (OSError, ValueError):
            parser.error("사용량 조회 실패: 데이터 경로와 단가 형식을 확인하세요.")
        return
    if args.command in ("backup", "restore", "clean", "recovery-status"):
        from app import maintenance
        from fastapi import HTTPException
        import json
        if not (args.data_dir / "kdog.sqlite3").is_file():
            parser.error("현재 데이터 DB가 필요합니다. 삭제 목록을 새 빈 폴더로 대체하지 마세요.")
        store = Store(args.data_dir)
        try:
            if args.command == "backup":
                with store.connect() as db:
                    actor = db.execute("SELECT * FROM users WHERE username=? AND role='admin' AND active=1", (args.actor,)).fetchone()
                    if not actor:
                        parser.error("활성 운영 관리자 계정이 필요합니다.")
                result = maintenance.backup(store, args.destination, args.actor)
            elif args.command == "restore":
                result = maintenance.restore(store, args.source, args.destination)
            elif args.command == "clean":
                result = maintenance.clean(store, purge_deleted=args.purge_deleted)
            else:
                result = maintenance.status(store)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except (HTTPException, OSError, ValueError):
            parser.error("유지보수 실패: 실행 중 프로세스, 새 대상 폴더, 파일 해시 및 권한을 확인하세요.")
        return
    if args.command == "worker":
        from app.worker import Worker
        from app.maintenance import runtime_lock
        worker = Worker(Store(args.data_dir))
        try:
            with runtime_lock(worker.store, "worker"):
                if os.environ.get("KDOG_SUPERVISED") == "1":
                    Path(os.environ["KDOG_WORKER_READY"]).write_text("ready", encoding="utf-8")
                worker.once() if args.once else worker.run()
        except KeyboardInterrupt:
            pass
        return
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
