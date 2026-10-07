"""S1 run claims, immutable attempt artifacts and fenced adoption."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os

from fastapi import HTTPException

from app.storage import encode, now, uid


LEASE_SECONDS = 180
ACTIVE = ("queued", "running", "retry_wait")


def later(seconds) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def file_stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def step_output(store, row, step, *, recover=False):
    ref = step["output_ref"] or f"runs/{row['run_id']}/{step['step_id']}/output.json"
    path = store.path(ref)
    try:
        stamp = file_stamp(path)
        raw = path.read_bytes()
        output_hash = hashlib.sha256(raw).hexdigest()
        if file_stamp(path) != stamp or (not recover and step["output_hash"] and step["output_hash"] != output_hash):
            raise ValueError("changed artifact")
        result = json.loads(raw)
    except (OSError, ValueError):
        raise HTTPException(409, "산출물 파일 또는 해시가 올바르지 않습니다.") from None
    if (result["run_id"], result["step_id"], result["claim_token"], result["input_hash"], result["config_hash"]) != (
        row["run_id"], step["step_id"], step["claim_token"],
        digest(json.loads(row["input_snapshot_json"])), digest(json.loads(row["config_snapshot_json"]))
    ):
        raise HTTPException(409, "산출물 실행 연결이 일치하지 않습니다.")
    if (result.get("kind"), result.get("attempt"), result.get("stage"), result.get("key")) != (
            row["kind"], step["attempt"], step["stage"], step["branch_key"]):
        raise ValueError("versioned attempt envelope mismatch")
    return result["payload"], ref, output_hash, stamp


def step_payload(store, row, step, *, recover=False):
    return step_output(store, row, step, recover=recover)[0]


def check_access(store, db, row):
    if row["kind"] == "attachment_v4":
        from app import attachment_runs_v4
        return attachment_runs_v4.check_access(store, db, row)
    if row["kind"] == "report_v4":
        from app import report_runs_v4
        return report_runs_v4.check_access(store, db, row)
    if row["kind"] == "s1":
        from app import run_v4
        return run_v4.check_access(store, db, row)
    raise HTTPException(409, "이전 판본 실행은 종료되었습니다. S1 실행만 사용할 수 있습니다.")


def guard(store, run_id, token, *, renew=True):
    with store.connect(write=renew) as db:
        row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row or row["status"] != "running" or row["claim_token"] != token or row["lease_expires_at"] <= now():
            raise HTTPException(409, "실행 점유가 만료되었거나 중지되었습니다.")
        check_access(store, db, row)
        if renew:
            db.execute("UPDATE runs SET lease_expires_at=?,heartbeat_at=? WHERE run_id=? AND claim_token=?",
                       (later(LEASE_SECONDS), now(), run_id, token))
        return row


def claim(store):
    with store.connect(write=True) as db:
        rows = db.execute("SELECT * FROM runs WHERE status IN ('queued','retry_wait') "
                          "OR (status='running' AND lease_expires_at<=?) ORDER BY created_at", (now(),)).fetchall()
        for row in rows:
            try:
                check_access(store, db, row)
            except HTTPException:
                db.execute("UPDATE runs SET status='stopped',claim_token=NULL,updated_at=? WHERE run_id=?", (now(), row["run_id"]))
                continue
            pending = db.execute("SELECT MAX(retry_at) FROM steps WHERE run_id=? AND status='retry_wait'", (row["run_id"],)).fetchone()[0]
            if pending and pending > now():
                continue
            token = uid()
            db.execute("UPDATE runs SET status='running',claim_token=?,lease_expires_at=?,heartbeat_at=?,updated_at=? WHERE run_id=?",
                       (token, later(LEASE_SECONDS), now(), now(), row["run_id"]))
            claimed = dict(db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone())
            claimed["retry_failed"] = row["status"] == "queued"
            return claimed
    return None


def write_output(store, row, step, payload):
    guard(store, row["run_id"], row["claim_token"], renew=False)
    ref = f"runs/{row['run_id']}/{step['step_id']}/output.json"
    path = store.path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {"run_id": row["run_id"], "step_id": step["step_id"], "claim_token": step["claim_token"],
             "input_hash": digest(json.loads(row["input_snapshot_json"])),
             "config_hash": digest(json.loads(row["config_snapshot_json"])), "payload": payload}
    value.update(kind=row["kind"], attempt=step["attempt"], stage=step["stage"], key=step["branch_key"])
    raw = encode(value).encode("utf-8")
    temp = path.with_name(uid() + ".tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic publication, no existing attempt artifact can be overwritten.
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return ref, hashlib.sha256(raw).hexdigest()


def adopt(store, row, step, ref, output_hash, usage):
    if ref != f"runs/{row['run_id']}/{step['step_id']}/output.json":
        raise HTTPException(409, "attempt 경로가 일치하지 않습니다.")
    candidate = {**dict(step), "output_ref": ref, "output_hash": output_hash}
    payload, _, _, stamp = step_output(store, row, candidate)
    if row["kind"] == "s1":
        from app import run_v4
        source_stamps = run_v4.verify_files(store, run_v4.snapshot_for(row))
    if row["kind"] == "report_v4":
        from app import report_runs_v4
        source_stamps = report_runs_v4.verify_files(store, report_runs_v4.snapshot_for(row))
        source_stamps.update(report_runs_v4.output_stamps(store, step["stage"], payload))
    with store.connect(write=True) as db:
        current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
        if not current or current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
            raise HTTPException(409, "오래된 실행 결과를 채택할 수 없습니다.")
        check_access(store, db, current)
        if row["kind"] == "s1":
            run_v4.check_stamps(store, source_stamps)
        if row["kind"] == "report_v4":
            report_runs_v4.check_stamps(store, source_stamps)
        try:
            if file_stamp(store.path(ref)) != stamp:
                raise ValueError("changed artifact")
        except (OSError, ValueError):
            raise HTTPException(409, "채택 직전 산출물이 변경되었습니다.") from None
        latest = db.execute("SELECT step_id FROM steps WHERE run_id=? AND stage=(SELECT stage FROM steps WHERE step_id=?) "
                            "AND branch_key=(SELECT branch_key FROM steps WHERE step_id=?) ORDER BY attempt DESC LIMIT 1",
                            (row["run_id"], step["step_id"], step["step_id"])).fetchone()
        if not latest or latest[0] != step["step_id"]:
            raise HTTPException(409, "최신 attempt만 채택할 수 있습니다.")
        changed = db.execute("UPDATE steps SET status='succeeded',output_ref=?,output_hash=?,usage_json=?,updated_at=? "
                             "WHERE step_id=? AND status='running' AND claim_token=?",
                             (ref, output_hash, encode(usage), now(), step["step_id"], step["claim_token"])).rowcount
        if not changed:
            raise HTTPException(409, "오래된 단계 결과를 채택할 수 없습니다.")
