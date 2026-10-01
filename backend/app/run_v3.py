"""Versioned run admission, explicit reuse and operational status without AI disclosure."""

import hashlib
import json

from fastapi import HTTPException

from app.analysis import digest, file_stamp, step_payload
from app.domain.preprocess_v3 import BatchV3
from app.domain.runs_v3 import ReuseV3, RunConfigV3, RunInputV3
from app.domain.sheets_v3 import BatchPointerV3
from app.input_models_v3 import ManifestV3
from app.intake import selected_session
from app.preprocess_v3 import ASSET_HASHES, verify_assets
from app.scoring_v3 import RULE_HASH, RULE_VERSION, verify_rules
from app.sheets import manager
from app.storage import encode, now, uid

KINDS = ("scoring_v3", "report_v3")
TERMINAL = ("succeeded", "failed", "stopped", "settings_required")


def verify_files(store, snapshot):
    """Hash large files outside a writer transaction, then retain change stamps for admission."""
    files = [(snapshot.input.manifest_ref, snapshot.input.manifest_hash),
             (snapshot.preprocess.ref, snapshot.preprocess.hash)]
    files.extend((video.storage_ref, video.sha256) for video in snapshot.session.videos)
    files.extend((clip.ref, clip.hash) for clip in snapshot.batch.clips)
    stamps = {}
    try:
        for ref, expected in files:
            path = store.path(ref)
            before = file_stamp(path)
            with path.open("rb") as handle:
                actual = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual != expected or file_stamp(path) != before:
                raise ValueError("hash or file changed")
            stamps[ref] = before
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "실행 입력·원본·클립 파일이 변경되었거나 누락되었습니다.") from exc
    return stamps


def assets(snapshot):
    verify_assets()
    verify_rules()
    batch = snapshot.batch
    if (batch.catalog_hash, batch.protocol_hash, batch.rules_hash, snapshot.calculation_hash, snapshot.calculation_version) != (
            ASSET_HASHES["catalog_hash"], ASSET_HASHES["protocol_hash"], ASSET_HASHES["rules_hash"], RULE_HASH, RULE_VERSION):
        raise HTTPException(409, "전처리와 실행 판본이 일치하지 않습니다.")


def snapshot_for(row):
    if row["kind"] != "scoring_v3":
        raise HTTPException(409, "이 종류의 채점 입력 조회는 지원하지 않습니다.")
    snapshot = RunInputV3.model_validate_json(row["input_snapshot_json"])
    if digest(snapshot.model_dump(mode="json")) != row["input_hash"] or (
            snapshot.case_id, snapshot.session_id, snapshot.input_revision) != (
            row["case_id"], row["session_id"], row["input_revision"]):
        raise ValueError("execution input identity mismatch")
    return snapshot


def compatibility(snapshot, config):
    # Requestor metadata does not change the footage or provider contract.
    source = snapshot.model_dump(mode="json", exclude={"requested_by"})
    return digest({"source": source, "config": config.model_dump(mode="json")})


def validate_reuse(store, db, snapshot, config, entries):
    expected = compatibility(snapshot, config)
    groups = {(stage.stage, stage.key) for stage in config.stages}
    seen = set()
    for entry in entries:
        pair = entry.stage, entry.key
        if pair not in groups or pair in seen or entry.compatibility_hash != expected:
            raise HTTPException(409, "재사용 항목군·창·판본·요청 설정이 일치하지 않습니다.")
        seen.add(pair)
        source = db.execute("SELECT * FROM runs WHERE run_id=?", (entry.source_run_id,)).fetchone()
        step = db.execute("SELECT * FROM steps WHERE step_id=? AND run_id=? AND status='succeeded'",
                          (entry.step_id, entry.source_run_id)).fetchone()
        if not source or source["kind"] != "scoring_v3" or not step or (
                source["case_id"], source["session_id"], step["stage"], step["branch_key"], step["output_ref"], step["output_hash"]) != (
                snapshot.case_id, snapshot.session_id, entry.stage, entry.key, entry.ref, entry.hash):
            raise HTTPException(409, "성공한 재사용 산출물의 연결이 일치하지 않습니다.")
        original = snapshot_for(source)
        original_config = RunConfigV3.model_validate_json(source["config_snapshot_json"])
        if compatibility(original, original_config) != expected:
            raise HTTPException(409, "재사용 원본 입력 또는 설정이 다릅니다.")
        step_payload(store, source, step)


def enqueue(store, case_id, session_id, value, user, config, *, reuse=(), enabled=False):
    manager(user)
    if not enabled:
        raise HTTPException(503, "신판 AI 채점은 C07B 공급자 연결 전으로 아직 활성화되지 않았습니다.")
    config = RunConfigV3.model_validate(config)
    reuse = tuple(ReuseV3.model_validate(entry) for entry in reuse)
    request_hash = digest({"request": value.model_dump(mode="json"), "config": config.model_dump(mode="json"),
                           "reuse": [entry.model_dump(mode="json") for entry in reuse], "actor": user.username})
    with store.connect() as db:
        manager(user, db)
        row = store.case(db, case_id)
        previous = db.execute("SELECT * FROM runs WHERE case_id=? AND session_id=? AND kind='scoring_v3' AND request_id=?",
                              (case_id, session_id, value.request_id)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise HTTPException(409, "같은 요청 식별에 다른 입력을 사용할 수 없습니다.")
            return view(store, previous["run_id"], user)
        store.case(db, case_id, expected=value.expected_revision)
        manifest = store.manifest(row)
        if not isinstance(manifest, ManifestV3):
            raise HTTPException(409, "신판 접수 입력이 필요합니다.")
        session = selected_session(manifest, session_id)
        recorded = any(json.loads(entry[0]).get("ref") == value.preprocess_ref and json.loads(entry[0]).get("hash") == value.preprocess_hash
                       for entry in db.execute("SELECT detail_json FROM changes WHERE target=? AND action='preprocess.complete'", (case_id,)))
    if not recorded:
        raise HTTPException(409, "이 사례에 채택된 전처리 참조가 아닙니다.")
    try:
        batch = BatchV3.model_validate_json(store.path(value.preprocess_ref).read_bytes())
        snapshot = RunInputV3(case_id=case_id, session_id=session_id, input_revision=row["input_revision"],
            input={"manifest_ref": row["manifest_ref"], "manifest_hash": row["manifest_hash"]}, session=session,
            preprocess=BatchPointerV3(ref=value.preprocess_ref, hash=value.preprocess_hash), batch=batch,
            calculation_version=RULE_VERSION, calculation_hash=RULE_HASH, requested_by=user.username)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "전처리 입력·세션·판본 연결을 확인하세요.") from exc
    assets(snapshot)
    verify_files(store, snapshot)
    with store.connect() as db:
        validate_reuse(store, db, snapshot, config, reuse)
    stamps = verify_files(store, snapshot)
    assets(snapshot)
    with store.connect(write=True) as db:
        manager(user, db)
        current = store.case(db, case_id, expected=value.expected_revision)
        if (current["manifest_ref"], current["manifest_hash"]) != (row["manifest_ref"], row["manifest_hash"]):
            raise HTTPException(409, "실행 접수 중 입력이 바뀌었습니다.")
        try:
            if any(file_stamp(store.path(ref)) != stamp for ref, stamp in stamps.items()):
                raise ValueError("file changed")
        except (OSError, ValueError) as exc:
            raise HTTPException(409, "실행 접수 직전 파일이 변경되었습니다.") from exc
        previous = db.execute("SELECT * FROM runs WHERE case_id=? AND session_id=? AND kind='scoring_v3' AND request_id=?",
                              (case_id, session_id, value.request_id)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise HTTPException(409, "같은 요청 식별에 다른 입력을 사용할 수 없습니다.")
            run_id = previous["run_id"]
        else:
            run_id = uid()
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,"
                       "reuse_manifest_json,status,created_at,updated_at,kind,request_id,request_hash,input_hash) "
                       "VALUES(?,?,?,?,?,?,?,'queued',?,?,'scoring_v3',?,?,?)",
                       (run_id, case_id, session_id, row["input_revision"], snapshot.model_dump_json(), config.model_dump_json(),
                        encode([entry.model_dump(mode="json") for entry in reuse]), now(), now(), value.request_id, request_hash,
                        digest(snapshot.model_dump(mode="json"))))
            store.audit(db, user.username, run_id, "run_v3.create", {"kind": "scoring_v3", "request_id": value.request_id})
    return view(store, run_id, user)


def row_for(store, db, run_id):
    row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row or row["kind"] not in KINDS:
        raise HTTPException(404, "신판 실행을 찾을 수 없습니다.")
    store.case(db, row["case_id"])
    return row


def view(store, run_id, user):
    # Operational status intentionally carries neither payload, usage text nor file references.
    with store.connect() as db:
        account = db.execute("SELECT role,active FROM users WHERE username=?", (user.username,)).fetchone()
        if not account or not account["active"] or account["role"] not in ("operator", "reviewer", "admin"):
            raise HTTPException(403, "실행 상태 조회 권한이 없습니다.")
        row = row_for(store, db, run_id)
        case = store.case(db, row["case_id"])
        steps = []
        for step in db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY created_at,attempt", (run_id,)):
            usage = json.loads(step["usage_json"])
            steps.append({"stage": step["stage"], "key": step["branch_key"], "attempt": step["attempt"], "status": step["status"],
                          "code": usage.get("code"), "billing_uncertain": bool(usage.get("billing_uncertain") or
                              (step["call_reserved"] and step["status"] == "running")),
                          "call_reserved": bool(step["call_reserved"])})
        return {"run_id": run_id, "case_id": row["case_id"], "session_id": row["session_id"], "kind": row["kind"],
                "input_revision": row["input_revision"], "status": row["status"], "updated_at": row["updated_at"],
                "outdated": row["input_revision"] != case["input_revision"], "failure_code": row["failure_code"],
                "result_available": bool(row["result_ref"]), "steps": steps}


def action(store, run_id, value, user, *, retry=False):
    with store.connect(write=True) as db:
        manager(user, db)
        row = row_for(store, db, run_id)
        if row["updated_at"] != value.expected_updated_at:
            raise HTTPException(409, "실행 상태가 변경되었습니다. 다시 조회하세요.")
        if retry and row["status"] not in ("failed", "stopped", "settings_required"):
            raise HTTPException(409, "실패·중지한 실행만 명시적으로 재시도할 수 있습니다.")
        if not retry and row["status"] in TERMINAL:
            raise HTTPException(409, "종료된 실행입니다.")
        db.execute("UPDATE runs SET status=?,failure_code=NULL,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?",
                   ("queued" if retry else "stopped", now(), run_id))
        if not retry:
            for step in db.execute("SELECT * FROM steps WHERE run_id=? AND status='running'", (run_id,)).fetchall():
                usage = {**json.loads(step["usage_json"]), "code": "worker_interrupted", "billing_uncertain": bool(step["call_reserved"])}
                db.execute("UPDATE steps SET usage_json=?,updated_at=? WHERE step_id=?", (encode(usage), now(), step["step_id"]))
        store.audit(db, user.username, run_id, "run_v3.retry" if retry else "run_v3.stop", {"reason": value.reason})
    return view(store, run_id, user)


def process(worker, row):
    """C07B supplies validated Python handlers; no generic work execution API exists."""
    snapshot = snapshot_for(row)
    config = RunConfigV3.model_validate_json(row["config_snapshot_json"])
    assets(snapshot)
    verify_files(worker.store, snapshot)
    if worker.v3_work is None:
        finish(worker, row, "settings_required", "v3_provider_inactive")
        return
    entries = tuple(ReuseV3.model_validate_json(encode(entry)) for entry in json.loads(row["reuse_manifest_json"]))
    with worker.store.connect() as db:
        validate_reuse(worker.store, db, snapshot, config, entries)
    last = None
    complete = True
    for group in config.stages:
        entry = next((entry for entry in entries if (entry.stage, entry.key) == (group.stage, group.key)), None)
        validate, work = worker.v3_work(snapshot, group, row)
        if entry:
            with worker.store.connect() as db:
                source = db.execute("SELECT * FROM runs WHERE run_id=?", (entry.source_run_id,)).fetchone()
                step = db.execute("SELECT * FROM steps WHERE step_id=?", (entry.step_id,)).fetchone()
                payload = step_payload(worker.store, source, step)
            perform = lambda step, payload=payload: {**payload, "usage": {"reused": True, "source_run_id": entry.source_run_id}}
        else:
            perform = work
        last = worker.stage(row, group.stage, group.key, validate, perform)
        complete = complete and last is not None
    worker.check(row)
    assets(snapshot)
    verify_files(worker.store, snapshot)
    with worker.store.connect() as db:
        retry_wait = db.execute("SELECT 1 FROM steps WHERE run_id=? AND status='retry_wait' LIMIT 1", (row["run_id"],)).fetchone()
    finish(worker, row, "succeeded" if complete else "retry_wait" if retry_wait else "failed", None)


def finish(worker, row, status, code):
    worker.check(row)
    with worker.store.connect(write=True) as db:
        current = row_for(worker.store, db, row["run_id"])
        if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
            raise HTTPException(409, "오래된 실행을 완료할 수 없습니다.")
        step = db.execute("SELECT * FROM steps WHERE run_id=? AND status='succeeded' ORDER BY rowid DESC LIMIT 1", (row["run_id"],)).fetchone()
        db.execute("UPDATE runs SET status=?,failure_code=?,result_ref=?,result_hash=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?",
                   (status, code, step["output_ref"] if step and status == "succeeded" else None,
                    step["output_hash"] if step and status == "succeeded" else None, now(), row["run_id"]))
