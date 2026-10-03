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
    reset_s1 = sub.add_parser("reset-s1", help="원입력을 보존하고 구판 평가 결과를 S1으로 초기화 (API·worker 종료 필요)")
    reset_s1.add_argument("--actor", required=True, help="활성 운영 관리자 계정")
    reset_s1.add_argument("--apply", action="store_true", help="생략하면 제거 범위만 점검")
    reset_s1.add_argument("--retry-remote", action="store_true", help="남아 있는 공급자 파일 삭제를 재시도")
    preprocess = sub.add_parser("preprocess", help="확정한 8구간으로 기준 영상을 잘라 불변 클립을 만든다 (FFmpeg)")
    preprocess.add_argument("case_id")
    preprocess.add_argument("--session-id", help="비우면 현재 선택 세션")
    preprocess.add_argument("--actor", required=True, help="기록에 사용할 활성 운영자·관리자 계정")
    preprocess.add_argument("--request-id", required=True, help="명시 S1 전처리 요청 ID; 같은 요청 재시도 시 유지")
    preprocess.add_argument("--expected-revision", type=int, required=True, help="확인한 현재 입력 판본")
    usage = sub.add_parser("usage-report", help="행사·참가자·시도별 사용량과 명시한 단가 추정 JSON")
    usage.add_argument("--event-id")
    usage.add_argument("--prices", type=Path, help="통화·출처·모델별 계량 단가 JSON")
    args = parser.parse_args()
    if args.command == "reset-s1":
        import json
        from fastapi import HTTPException
        from app import reset_s1
        if not (args.data_dir / "kdog.sqlite3").is_file():
            parser.error("현재 데이터 DB가 필요합니다. 초기화할 데이터 루트를 명시하세요.")
        store = Store(args.data_dir)
        try:
            if args.retry_remote:
                result = reset_s1.retry_remote_cleanup(store, args.actor)
            else:
                result = reset_s1.execute(store, args.actor) if args.apply else reset_s1.preview(store)
                result["remote_cleanup_pending"] = len(reset_s1.pending_remote_cleanup(store))
        except (HTTPException, OSError, ValueError) as exc:
            parser.error(f"S1 초기화 실패: {getattr(exc, 'detail', type(exc).__name__)}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "preprocess":
        import json
        from fastapi import HTTPException
        from app import preprocess_v4 as clips
        from app.domain.preprocess_v4 import PreprocessRequestV4
        from app.media import MediaError
        if not (args.data_dir / "kdog.sqlite3").is_file():
            parser.error("현재 데이터 DB가 필요합니다.")
        store = Store(args.data_dir)
        with store.connect() as db:
            actor = db.execute("SELECT username FROM users WHERE username=? AND role IN ('operator','admin') AND active=1", (args.actor,)).fetchone()
            if not actor:
                parser.error("활성 운영자 또는 운영 관리자 계정이 필요합니다.")
            case = db.execute("SELECT selected_session_id FROM cases WHERE case_id=?", (args.case_id,)).fetchone()
            if not case:
                parser.error("참가자를 찾을 수 없습니다.")
        try:
            result = clips.execute(store, args.case_id, args.session_id or case["selected_session_id"], args.actor,
                PreprocessRequestV4(request_id=args.request_id, expected_revision=args.expected_revision))
        except (HTTPException, MediaError) as exc:
            parser.error(f"전처리 실패: {getattr(exc, 'detail', exc)}")
        print(json.dumps(result.model_dump(mode="json", exclude={"clips"}) | {"clips": len(result.clips)}, ensure_ascii=False, indent=2))
        return
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
        store = Store(args.data_dir)
        with store.connect() as db:
            old_inputs = db.execute("SELECT 1 FROM cases WHERE manifest_schema_version!='intake-4.0' LIMIT 1").fetchone()
            old_runs = db.execute("SELECT 1 FROM runs WHERE kind NOT IN ('s1','report_v4') LIMIT 1").fetchone()
            if old_inputs or old_runs:
                parser.error("S1 worker 실행 전 reset-s1 --actor <관리자> --apply로 기존 결과를 초기화하세요.")
        worker = Worker(store)
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
