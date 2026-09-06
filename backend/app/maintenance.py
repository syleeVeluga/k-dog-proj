"""Verified data-only snapshots and offline recovery into a fresh directory."""

from contextlib import closing, contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from fastapi import HTTPException

from app.storage import REPO_ROOT, Store, encode, now, uid


MANAGED = {"inputs", "videos", "runs", "reviews", "exports", "settings"}
REF_HASH = {"manifest_ref": "manifest_hash", "output_ref": "output_hash", "result_ref": "result_hash",
            "storage_ref": "sha256", "ref": "hash"}


@contextmanager
def runtime_lock(store, name):
    path = store.root / ("." + name + ".lock")
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise HTTPException(409, "API·worker 또는 유지보수 작업이 실행 중입니다. 종료 후 다시 시도하세요.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def offline(store):
    with ExitStack() as stack:
        for name in ("maintenance", "api", "worker"):
            stack.enter_context(runtime_lock(store, name))
        yield


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def managed_path(store, ref):
    path = store.path(ref)
    if not isinstance(ref, str) or "\\" in ref or Path(ref).is_absolute() or ref.split("/")[0] not in MANAGED or path.relative_to(store.root).as_posix() != ref:
        raise HTTPException(409, "백업에 허용되지 않은 파일 참조입니다.")
    return path


def references(store, db):
    found = {}

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, candidate in value.items():
                if key in REF_HASH and candidate:
                    path = managed_path(store, candidate)
                    expected = value.get(REF_HASH[key])
                    if candidate in found:
                        if expected and expected != found[candidate]:
                            raise HTTPException(409, "파일 참조 해시가 충돌합니다.")
                        continue
                    actual = file_hash(path)
                    if expected and expected != actual:
                        raise HTTPException(409, "백업 대상 파일 해시가 일치하지 않습니다.")
                    found[candidate] = actual
                    if path.suffix == ".json":
                        visit(json.loads(path.read_bytes()))
                elif key.endswith("_json") and isinstance(candidate, str):
                    visit(json.loads(candidate))
                else:
                    visit(candidate)

    for table in ("cases", "runs", "steps", "changes"):
        for row in db.execute(f"SELECT * FROM {table}"):
            visit(dict(row))
    # Keep a completed, unadopted latest attempt for normal worker envelope validation.
    for row in db.execute("SELECT * FROM steps s WHERE status='running' AND attempt=(SELECT MAX(attempt) FROM steps WHERE run_id=s.run_id AND stage=s.stage AND branch_key=s.branch_key)"):
        ref = f"runs/{row['run_id']}/{row['step_id']}/output.json"
        if store.path(ref).is_file():
            visit({"ref": ref})
    return found


def status(store):
    with store.connect() as db:
        counts = {row[0]: row[1] for row in db.execute("SELECT status,COUNT(*) FROM runs GROUP BY status")}
        deleted = db.execute("SELECT COUNT(*) FROM cases WHERE deletion_requested=1").fetchone()[0]
        last = db.execute("SELECT detail_json FROM changes WHERE action='backup.create' ORDER BY rowid DESC LIMIT 1").fetchone()
    return {"runs": counts, "deletion_requests": deleted, "free_bytes": shutil.disk_usage(store.root).free,
            "last_backup": json.loads(last[0]) if last else None,
            "message": "중단된 worker는 점유 만료 후 재개합니다. 복원·파일 정리는 API와 worker 종료 후 관리 명령을 사용하세요."}


def destination_path(store, destination):
    destination = destination.expanduser().resolve()
    if destination.is_relative_to(REPO_ROOT) or destination.is_relative_to(store.root) or store.root.is_relative_to(destination):
        raise HTTPException(409, "백업·복원 폴더는 소스 및 원본 데이터 폴더와 분리하세요.")
    if destination.exists():
        raise HTTPException(409, "새 폴더를 지정하세요. 기존 폴더를 덮어쓰지 않습니다.")
    return destination


def backup(store, destination, actor):
    destination = destination_path(store, Path(destination))
    with runtime_lock(store, "maintenance"), store.connect(write=True) as db:
        refs = references(store, db)
        destination.mkdir(parents=True)
        # A second connection reads the committed snapshot while BEGIN IMMEDIATE fences writes.
        with store.connect() as source, closing(sqlite3.connect(destination / "kdog.sqlite3")) as target:
            with target:
                source.backup(target)
                target.execute("UPDATE users SET session_hash=NULL,session_expires=NULL")
        for ref, expected in refs.items():
            target = destination / ref
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(managed_path(store, ref), target)
            if file_hash(target) != expected:
                raise HTTPException(409, "복사한 파일 해시가 일치하지 않습니다.")
        refs["kdog.sqlite3"] = file_hash(destination / "kdog.sqlite3")
        manifest = {"schema": "kdog-backup-1", "created_at": now(), "files": refs, "secrets_included": False}
        (destination / "backup.json").write_text(encode(manifest), encoding="utf-8")
        result = {"path": str(destination), "created_at": manifest["created_at"], "file_count": len(refs)}
        store.audit(db, actor, destination.name, "backup.create", result)
        return result


def deletion_records(store):
    with store.connect() as db:
        records = {(r["event_id"], r["participant_id"]) for r in db.execute("SELECT * FROM cases WHERE deletion_requested=1")}
        records.update((d["event_id"], d["participant_id"]) for r in db.execute("SELECT detail_json FROM changes WHERE action='deletion.record'") for d in [json.loads(r[0])])
    return records


def clean(store, *, purge_deleted=False):
    with offline(store), store.connect(write=True) as db:
        if purge_deleted:
            db.execute("PRAGMA secure_delete=ON")
            for case in db.execute("SELECT * FROM cases WHERE deletion_requested=1").fetchall():
                actor = db.execute("SELECT username FROM users ORDER BY username LIMIT 1").fetchone()[0]
                store.audit(db, actor, case["case_id"], "deletion.record", {"event_id": case["event_id"], "participant_id": case["participant_id"]})
                runs = [r[0] for r in db.execute("SELECT run_id FROM runs WHERE case_id=?", (case["case_id"],))]
                targets = {case["case_id"], *runs}
                for change in db.execute("SELECT * FROM changes WHERE action='export.snapshot'").fetchall():
                    link = json.loads(change["detail_json"])
                    data = json.loads(store.path(link["ref"]).read_bytes())
                    if any(m["case_id"] == case["case_id"] for m in data["members"]):
                        targets.add(change["target"])
                for target in targets:
                    db.execute("DELETE FROM changes WHERE target=? AND action!='deletion.record'", (target,))
                db.execute("UPDATE cases SET display_run_id=NULL WHERE case_id=?", (case["case_id"],))
                for run_id in runs:
                    db.execute("DELETE FROM steps WHERE run_id=?", (run_id,))
                db.execute("DELETE FROM runs WHERE case_id=?", (case["case_id"],))
                db.execute("DELETE FROM cases WHERE case_id=?", (case["case_id"],))
        refs = references(store, db)
        candidates = []
        for name in MANAGED:
            for path in store.path(name).rglob("*"):
                if path.is_file() and path.relative_to(store.root).as_posix() not in refs:
                    # Resolve once more before unlink; never follow a junction outside the store.
                    resolved = store.path(path.relative_to(store.root).as_posix())
                    candidates.append(resolved)
        # Commit tombstones before deleting any bytes; interrupted cleanup is safe to rerun.
        db.commit()
        for path in candidates:
            path.unlink(missing_ok=True)
        if purge_deleted:
            db.execute("VACUUM")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"removed_files": len(candidates), "retained_files": len(refs)}


def restore(store, source, destination):
    source = Path(source).expanduser().resolve()
    destination = destination_path(store, Path(destination))
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise HTTPException(409, "백업과 복원 폴더를 분리하세요.")
    with offline(store):
        manifest = json.loads((source / "backup.json").read_bytes())
        if manifest.get("schema") != "kdog-backup-1" or manifest.get("secrets_included") is not False or "kdog.sqlite3" not in manifest.get("files", {}):
            raise HTTPException(409, "지원하지 않는 백업입니다.")
        for ref, expected in manifest["files"].items():
            path = (source / ref).resolve()
            if not path.is_relative_to(source) or path.relative_to(source).as_posix() != ref or (ref != "kdog.sqlite3" and ref.split("/")[0] not in MANAGED):
                raise HTTPException(409, "잘못된 백업 경로입니다.")
            if file_hash(path) != expected:
                raise HTTPException(409, "백업 파일 해시가 일치하지 않습니다.")
        # Reapply the current deletion ledger, even when restoring a backup from before withdrawal.
        deleted = deletion_records(store)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="kdog-restore-", dir=destination.parent) as staging:
            staged = Path(staging) / "data"
            staged.mkdir()
            for ref, expected in manifest["files"].items():
                target = staged / ref
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / ref, target)
                if file_hash(target) != expected:
                    raise HTTPException(409, "복원 중 백업 내용이 변경되었습니다.")
            restored = Store(staged)
            with restored.connect(write=True) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
                    raise HTTPException(409, "복원 DB 무결성 검사에 실패했습니다.")
                db.execute("UPDATE users SET session_hash=NULL,session_expires=NULL")
                actor = db.execute("SELECT username FROM users ORDER BY username LIMIT 1").fetchone()
                if deleted and not actor:
                    raise HTTPException(409, "삭제 이력 기록용 계정이 없는 백업입니다.")
                for event, participant in deleted:
                    db.execute("UPDATE cases SET deletion_requested=1 WHERE event_id=? AND participant_id=?", (event, participant))
                    # Preserve tombstones absent from this backup for any subsequent restore.
                    restored.audit(db, actor[0], uid(), "deletion.record", {"event_id": event, "participant_id": participant})
                db.execute("UPDATE runs SET lease_expires_at=? WHERE status='running'", ("1970-01-01T00:00:00+00:00",))
                references(restored, db)
            clean(restored, purge_deleted=True)
            staged.rename(destination)
        return {"path": str(destination), "message": "복원·삭제 목록 재적용 완료. 개발자가 새 PC의 키를 다시 등록하세요."}
