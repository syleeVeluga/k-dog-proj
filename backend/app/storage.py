"""SQLite references plus immutable managed input and attempt files."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import HTTPException

from app.input_models import CaseView, Manifest


REPO_ROOT = Path(__file__).resolve().parents[2]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid4().hex


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('operator','reviewer','admin','developer')),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    session_hash TEXT UNIQUE, session_expires REAL,
    failed_logins INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, participant_id TEXT NOT NULL,
    dog_name TEXT NOT NULL, reservation_at TEXT NOT NULL,
    input_revision INTEGER NOT NULL CHECK(input_revision > 0),
    selected_session_id TEXT NOT NULL, display_run_id TEXT,
    manifest_ref TEXT NOT NULL UNIQUE, manifest_hash TEXT NOT NULL,
    consent_json TEXT, deletion_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(event_id, participant_id),
    FOREIGN KEY(display_run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id),
    session_id TEXT NOT NULL, input_revision INTEGER NOT NULL,
    input_snapshot_json TEXT NOT NULL, config_snapshot_json TEXT NOT NULL,
    reuse_manifest_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL, result_ref TEXT, result_hash TEXT,
    claim_token TEXT, lease_expires_at TEXT, heartbeat_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
    stage TEXT NOT NULL, branch_key TEXT NOT NULL, attempt INTEGER NOT NULL,
    status TEXT NOT NULL, claim_token TEXT, lease_expires_at TEXT,
    heartbeat_at TEXT, retry_at TEXT, output_ref TEXT UNIQUE, output_hash TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, UNIQUE(run_id, stage, branch_key, attempt)
);
CREATE TABLE IF NOT EXISTS changes (
    change_id TEXT PRIMARY KEY, actor TEXT NOT NULL REFERENCES users(username),
    happened_at TEXT NOT NULL, target TEXT NOT NULL,
    action TEXT NOT NULL, detail_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS immutable_run_input
BEFORE UPDATE OF input_snapshot_json, config_snapshot_json, case_id,
session_id, input_revision, reuse_manifest_json ON runs
BEGIN SELECT RAISE(ABORT, 'run snapshots are immutable'); END;
"""


class Store:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        if self.root == REPO_ROOT or self.root.is_relative_to(REPO_ROOT):
            raise ValueError("K-DOG 데이터 폴더는 소스 저장소 밖에 지정하세요.")
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("inputs", "videos"):
            (self.root / name).mkdir(exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            if "call_reserved" not in {r[1] for r in db.execute("PRAGMA table_info(steps)")}:
                db.execute("ALTER TABLE steps ADD COLUMN call_reserved INTEGER NOT NULL DEFAULT 0")
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.root / "kdog.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise HTTPException(409, "잘못된 관리 파일 경로입니다.")
        return path

    def manifest(self, row) -> Manifest:
        try:
            data = self.path(row["manifest_ref"]).read_bytes()
        except OSError as exc:
            raise HTTPException(409, "입력 파일을 읽을 수 없습니다. 저장소를 확인하세요.") from exc
        if hashlib.sha256(data).hexdigest() != row["manifest_hash"]:
            raise HTTPException(409, "입력 파일 해시가 일치하지 않습니다.")
        value = Manifest.model_validate_json(data)
        if (value.case_id, value.input_revision, value.selected_session_id) != (
            row["case_id"], row["input_revision"], row["selected_session_id"]
        ):
            raise HTTPException(409, "입력 참조가 일치하지 않습니다.")
        return value

    def write_manifest(self, manifest: Manifest) -> tuple[str, str]:
        data = manifest.model_dump_json().encode("utf-8")
        key = f"inputs/{manifest.case_id}-r{manifest.input_revision}-{uid()}.json"
        with self.path(key).open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return key, hashlib.sha256(data).hexdigest()

    def case(self, db, case_id: str, *, expected=None, accessible=True):
        row = db.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "참가자를 찾을 수 없습니다.")
        if accessible and row["deletion_requested"]:
            raise HTTPException(403, "삭제 요청된 자료입니다.")
        if expected is not None and row["input_revision"] != expected:
            raise HTTPException(409, "다른 변경이 저장되었습니다. 새로 조회 후 다시 시도하세요.")
        return row

    def view(self, row) -> CaseView:
        with self.connect() as db:
            run = db.execute("SELECT status FROM runs WHERE run_id=?", (row["display_run_id"],)).fetchone()
        return CaseView(
            analysis_status=run["status"] if run else "not_started",
            **{name: row[name] for name in (
                "case_id", "event_id", "participant_id", "dog_name", "reservation_at",
                "input_revision", "selected_session_id",
            )},
            consent=json.loads(row["consent_json"]) if row["consent_json"] else None,
            deletion_requested=bool(row["deletion_requested"]), manifest=self.manifest(row),
        )

    def save(self, db, row, manifest: Manifest, actor: str, action: str):
        manifest.input_revision = row["input_revision"] + 1
        manifest.display_run_id = None
        key, digest = self.write_manifest(manifest)
        db.execute(
            "UPDATE cases SET input_revision=?, selected_session_id=?, display_run_id=NULL, "
            "manifest_ref=?, manifest_hash=?, updated_at=? WHERE case_id=?",
            (manifest.input_revision, manifest.selected_session_id, key, digest, now(), row["case_id"]),
        )
        self.audit(db, actor, row["case_id"], action, {"revision": manifest.input_revision})

    def audit(self, db, actor, target, action, detail):
        db.execute("INSERT INTO changes VALUES (?,?,?,?,?,?)",
                   (uid(), actor, now(), target, action, encode(detail)))


def require_consent(row, permission: str):
    consent = json.loads(row["consent_json"]) if row["consent_json"] else {}
    if row["deletion_requested"] or not consent.get(permission):
        raise HTTPException(403, "현재 동의 상태에서 이 작업을 수행할 수 없습니다.")
