"""S1 run admission, immutable input pins, explicit reuse and execution fences."""

import hashlib
import json
import time
from fastapi import HTTPException

from .analysis import digest, file_stamp, step_payload
from .domain.preprocess_v4 import FileV4
from .domain.runs_v4 import ActionV4, ReuseV4, RunConfigV4, RunInputV4, StartV4
from .domain.sheets_v4 import BatchPointerV4, InputPointerV4
from .input_models_v4 import ManifestV4
from .intake import selected_session
from . import preprocess_v4
from .sheets_v4 import manager
from .storage import encode, now, uid
from .usage import token_meters

TERMINAL = ("succeeded", "partial_failed", "failed", "stopped", "settings_required")


def verify_files(store, snapshot):
    """Hash every adopted input/parent/derivative outside writer transactions."""
    files = [(snapshot.input.manifest_ref, snapshot.input.manifest_hash), (snapshot.preprocess.ref, snapshot.preprocess.hash)]
    files.extend((video.storage_ref, video.sha256) for video in snapshot.session.videos)
    files.extend((source.ref, source.hash) for source in snapshot.batch.source_files)
    files.extend((source.ref, source.hash) for source in preprocess_v4._artifacts(snapshot.batch))
    if snapshot.batch.reuse_manifest:
        files.append((snapshot.batch.reuse_manifest.ref, snapshot.batch.reuse_manifest.hash))
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
    except (OSError, ValueError):
        raise HTTPException(409, "S1 실행 입력·원본·변환 부모·클립 파일이 변경되었거나 누락되었습니다.") from None
    return stamps


def check_stamps(store, identities):
    try:
        if any(file_stamp(store.path(ref)) != stamp for ref, stamp in identities.items()):
            raise ValueError("file changed")
    except (OSError, ValueError):
        raise HTTPException(409, "S1 결과 채택 직전 고정 입력 파일이 변경되었습니다.") from None


def assets(snapshot):
    current = preprocess_v4._assets()
    if snapshot.batch.asset_hashes != current or snapshot.calculation_hash != current["rules/scoring-v4.json"]:
        raise HTTPException(409, "S1 전처리·카탈로그·계산 규칙 판본이 일치하지 않습니다.")


def snapshot_for(row):
    if row["kind"] != "s1":
        raise HTTPException(409, "S1 실행 입력만 읽을 수 있습니다.")
    snapshot = RunInputV4.model_validate_json(row["input_snapshot_json"])
    if digest(snapshot.model_dump(mode="json")) != row["input_hash"] or (snapshot.case_id, snapshot.session_id, snapshot.input_revision) != (
            row["case_id"], row["session_id"], row["input_revision"]):
        raise HTTPException(409, "S1 실행 입력의 고정 식별자가 일치하지 않습니다.")
    return snapshot


def check_access(store, db, row):
    snapshot = snapshot_for(row)
    case = store.case(db, snapshot.case_id, expected=snapshot.input_revision)
    manifest = store.manifest(case)
    account = db.execute("SELECT active,role FROM users WHERE username=?", (snapshot.requested_by,)).fetchone()
    if not account or not account["active"] or account["role"] not in ("operator", "admin"):
        raise HTTPException(403, "S1 실행 요청자의 권한이 변경되었습니다.")
    if not isinstance(manifest, ManifestV4) or manifest.consents.analysis_feedback != "confirmed":
        raise HTTPException(403, "분석·피드백 동의가 확인된 S1 입력만 실행할 수 있습니다.")
    session = selected_session(manifest, snapshot.session_id)
    if (case["manifest_ref"], case["manifest_hash"], session) != (snapshot.input.manifest_ref, snapshot.input.manifest_hash, snapshot.session):
        raise HTTPException(409, "S1 실행 중 선택 회차·입력·동기화가 변경되었습니다.")
    files, metadata = preprocess_v4._source_snapshot(store, db, snapshot.case_id, session, snapshot.requested_by)
    if files != snapshot.batch.source_files or metadata != snapshot.batch.source_metadata:
        raise HTTPException(409, "S1 원본 또는 변환 연결 원장이 변경되었습니다.")
    return snapshot


def compatibility(snapshot, config):
    return digest({"source": snapshot.model_dump(mode="json", exclude={"requested_by"}), "config": config.model_dump(mode="json")})


def validate_reuse(store, db, snapshot, config, entries):
    expected = compatibility(snapshot, config)
    groups = {(stage.stage, stage.key) for stage in config.stages if stage.stage == "score_v4"}
    seen = set()
    identities = {}
    for entry in entries:
        pair = entry.stage, entry.key
        if pair not in groups or pair in seen or entry.compatibility_hash != expected:
            raise HTTPException(409, "S1 재사용 항목군·창·판본·요청 설정이 일치하지 않습니다.")
        seen.add(pair)
        source = db.execute("SELECT * FROM runs WHERE run_id=?", (entry.source_run_id,)).fetchone()
        step = db.execute("SELECT * FROM steps WHERE step_id=? AND run_id=? AND status='succeeded'", (entry.step_id, entry.source_run_id)).fetchone()
        if not source or source["kind"] != "s1" or not step or (source["case_id"], source["session_id"], step["stage"], step["branch_key"], step["output_ref"], step["output_hash"]) != (
                snapshot.case_id, snapshot.session_id, entry.stage, entry.key, entry.ref, entry.hash):
            raise HTTPException(409, "성공한 S1 재사용 원자료의 연결이 일치하지 않습니다.")
        original = snapshot_for(source)
        original_config = RunConfigV4.model_validate_json(source["config_snapshot_json"])
        if compatibility(original, original_config) != expected:
            raise HTTPException(409, "재사용 원본 입력 또는 설정이 다릅니다.")
        before = file_stamp(store.path(entry.ref))
        step_payload(store, source, step)
        if file_stamp(store.path(entry.ref)) != before:
            raise HTTPException(409, "검증 중 재사용 원자료가 변경되었습니다.")
        identities[entry.ref] = before
    return identities


def _consented(store, db, case_id, session_id, expected=None):
    case = store.case(db, case_id, expected=expected)
    manifest = store.manifest(case)
    if not isinstance(manifest, ManifestV4) or manifest.consents.analysis_feedback != "confirmed":
        raise HTTPException(403, "분석·피드백 동의가 확인된 S1 입력이 필요합니다.")
    return case, selected_session(manifest, session_id)


def enqueue(store, case_id, session_id, value, user, config, *, reuse=(), enabled=False):
    manager(user)
    value = StartV4.model_validate_json(value.model_dump_json())
    config = RunConfigV4.model_validate(config)
    reuse = tuple(ReuseV4.model_validate(entry) for entry in reuse)
    if not enabled or not config.raw_observation_scope_confirmed:
        raise HTTPException(503, "S1 관찰 원자료 적용 범위를 확인한 활성 설정이 필요합니다.")
    request_hash = digest({"request": value.model_dump(mode="json"), "config": config.model_dump(mode="json"),
                           "reuse": [entry.model_dump(mode="json") for entry in reuse], "actor": user.username})
    with store.connect() as db:
        manager(user, db)
        case, session = _consented(store, db, case_id, session_id)
        previous = db.execute("SELECT * FROM runs WHERE case_id=? AND session_id=? AND kind='s1' AND request_id=?", (case_id, session_id, value.request_id)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise HTTPException(409, "같은 요청 ID에 다른 S1 실행 입력을 사용할 수 없습니다.")
            check_access(store, db, previous)
            return view(store, previous["run_id"], user)
        store.case(db, case_id, expected=value.expected_revision)
    pointer = FileV4(ref=value.preprocess_ref, hash=value.preprocess_hash)
    batch = preprocess_v4.verified_batch(store, case_id, session_id, pointer, user.username)
    snapshot = RunInputV4(case_id=case_id, session_id=session_id, input_revision=case["input_revision"],
        input=InputPointerV4(manifest_ref=case["manifest_ref"], manifest_hash=case["manifest_hash"]), session=session,
        preprocess=BatchPointerV4(ref=pointer.ref, hash=pointer.hash, batch_id=batch.batch_id), batch=batch,
        calculation_hash=batch.asset_hashes["rules/scoring-v4.json"], requested_by=user.username)
    assets(snapshot)
    stamps = verify_files(store, snapshot)
    with store.connect() as db:
        reuse_stamps = validate_reuse(store, db, snapshot, config, reuse)
    with store.connect(write=True) as db:
        manager(user, db)
        current, current_session = _consented(store, db, case_id, session_id, value.expected_revision)
        if (current["manifest_ref"], current["manifest_hash"], current_session) != (case["manifest_ref"], case["manifest_hash"], session):
            raise HTTPException(409, "실행 접수 중 S1 입력이 바뀌었습니다.")
        if config.active_settings_version is not None:
            from . import settings_v4, scoring_ai_v4
            if settings_v4.active(db) != config.active_settings_version or scoring_ai_v4.configuration(config.active_settings_version,
                    settings_v4.load(store, db, config.active_settings_version)) != config:
                raise HTTPException(409, "실행 접수 중 활성 S1 설정이 변경되었습니다.")
        check_stamps(store, {**stamps, **reuse_stamps})
        previous = db.execute("SELECT * FROM runs WHERE case_id=? AND session_id=? AND kind='s1' AND request_id=?", (case_id, session_id, value.request_id)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise HTTPException(409, "같은 요청 ID의 S1 실행 설정이 다릅니다.")
            run_id = previous["run_id"]
        else:
            run_id = uid()
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,reuse_manifest_json,"
                       "status,created_at,updated_at,kind,request_id,request_hash,input_hash) VALUES(?,?,?,?,?,?,?,'queued',?,?,'s1',?,?,?)",
                       (run_id, case_id, session_id, case["input_revision"], snapshot.model_dump_json(), config.model_dump_json(),
                        encode([entry.model_dump(mode="json") for entry in reuse]), now(), now(), value.request_id, request_hash,
                        digest(snapshot.model_dump(mode="json"))))
            check_access(store, db, db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())
            store.audit(db, user.username, run_id, "run_v4.create", {"kind": "s1", "request_id": value.request_id})
    return view(store, run_id, user)


def row_for(store, db, run_id):
    row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row or row["kind"] != "s1":
        raise HTTPException(404, "S1 실행을 찾을 수 없습니다.")
    store.case(db, row["case_id"])
    return row


def view(store, run_id, user):
    """Operational status excludes observations, output refs, prompts and provider text."""
    with store.connect() as db:
        account = db.execute("SELECT active,role FROM users WHERE username=?", (user.username,)).fetchone()
        if not account or not account["active"] or account["role"] not in ("operator", "reviewer", "admin"):
            raise HTTPException(403, "S1 실행 상태 조회 권한이 없습니다.")
        row = row_for(store, db, run_id)
        case = store.case(db, row["case_id"])
        steps = []
        for step in db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY created_at,attempt", (run_id,)):
            usage = json.loads(step["usage_json"])
            timing = {key: value for key, value in usage.get("timing", {}).items() if type(value) in (int, float)}
            provider_usage = usage.get("provider_usage")
            meters = token_meters(provider_usage if isinstance(provider_usage, dict) else usage)
            tokens = {key: next((meters[name] for name in names if name in meters), None) for key, names in (
                ("input_tokens", ("total_input_tokens", "input_tokens")),
                ("output_tokens", ("total_output_tokens", "output_tokens")),
                ("total_tokens", ("total_tokens",)),
            )}
            steps.append({"stage": step["stage"], "key": step["branch_key"], "attempt": step["attempt"], "status": step["status"],
                "code": usage.get("code"), "billing_uncertain": bool(usage.get("billing_uncertain") or step["call_reserved"] and step["status"] == "running"),
                "remote_cleanup_pending": bool(usage.get("remote_cleanup_pending")),
                "call_reserved": bool(step["call_reserved"]), "reused": bool(usage.get("reused")), "timing": timing,
                "token_meters": meters, **tokens,
                "cost_usd": usage["cost_usd"] if type(usage.get("cost_usd")) in (int, float) else None})
        config = RunConfigV4.model_validate_json(row["config_snapshot_json"])
        return {"run_id": run_id, "case_id": row["case_id"], "session_id": row["session_id"], "kind": "s1", "input_revision": row["input_revision"],
            "status": row["status"], "updated_at": row["updated_at"], "outdated": row["input_revision"] != case["input_revision"] or row["session_id"] != case["selected_session_id"],
            "failure_code": row["failure_code"], "result_available": bool(row["result_ref"]), "steps": steps,
            "planned_provider_calls": sum(stage.provider_call for stage in config.stages), "reserved_calls": sum(step["call_reserved"] for step in steps),
            "max_ai_calls": config.max_ai_calls, "judgement_status": "policy_pending_D04"}


def action(store, run_id, value, user, *, retry=False):
    value = ActionV4.model_validate_json(value.model_dump_json())
    with store.connect(write=True) as db:
        manager(user, db)
        row = row_for(store, db, run_id)
        if row["updated_at"] != value.expected_updated_at:
            raise HTTPException(409, "실행 상태가 변경되었습니다. 다시 조회하세요.")
        if retry:
            check_access(store, db, row)
            if row["status"] not in ("failed", "stopped", "settings_required"):
                raise HTTPException(409, "실패·중지 실행만 재시도할 수 있습니다. 부분 완료 재생성은 명시 재사용한 새 실행입니다.")
        elif row["status"] in TERMINAL:
            raise HTTPException(409, "종료된 실행입니다.")
        db.execute("UPDATE runs SET status=?,failure_code=NULL,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?", ("queued" if retry else "stopped", now(), run_id))
        if not retry:
            for step in db.execute("SELECT * FROM steps WHERE run_id=? AND status='running'", (run_id,)).fetchall():
                usage = {**json.loads(step["usage_json"]), "code": "worker_interrupted", "billing_uncertain": bool(step["call_reserved"])}
                db.execute("UPDATE steps SET usage_json=?,updated_at=? WHERE step_id=?", (encode(usage), now(), step["step_id"]))
        store.audit(db, user.username, run_id, "run_v4.retry" if retry else "run_v4.stop", {"reason": value.reason})
    return view(store, run_id, user)


class DependenciesPending(Exception):
    pass


def process(worker, row):
    snapshot = snapshot_for(row)
    config = RunConfigV4.model_validate_json(row["config_snapshot_json"])
    worker.check(row)
    assets(snapshot)
    verify_files(worker.store, snapshot)
    handler = getattr(worker, "v4_work", None)
    if handler is None:
        from .scoring_ai_v4 import handler as provider_handler
        handler = lambda snapshot, group, row: provider_handler(worker, snapshot, group, row)
    entries = tuple(ReuseV4.model_validate_json(encode(entry)) for entry in json.loads(row["reuse_manifest_json"]))
    with worker.store.connect() as db:
        validate_reuse(worker.store, db, snapshot, config, entries)
    complete = True
    for group in config.stages:
        worker.check(row)
        entry = next((entry for entry in entries if (entry.stage, entry.key) == (group.stage, group.key)), None)
        try:
            validate, work = handler(snapshot, group, row)
        except DependenciesPending:
            complete = False
            continue
        if entry:
            with worker.store.connect() as db:
                source = db.execute("SELECT * FROM runs WHERE run_id=?", (entry.source_run_id,)).fetchone()
                step = db.execute("SELECT * FROM steps WHERE step_id=?", (entry.step_id,)).fetchone()
                payload = step_payload(worker.store, source, step)
            perform = lambda step, payload=payload, entry=entry: {**payload, "usage": {"reused": True, "source_run_id": entry.source_run_id}}
        else:
            perform = work
        def timed(step, operation=perform, stage=group.stage):
            started = time.monotonic()
            result = operation(step)
            usage = result.setdefault("usage", {})
            usage.setdefault("timing", {})[{"calculate_v4": "calculation_seconds", "publish_v4": "publish_seconds"}.get(stage, "stage_seconds")] = time.monotonic() - started
            return result
        result = worker.stage(row, group.stage, group.key, validate, timed)
        complete = complete and result is not None
    worker.check(row)
    assets(snapshot)
    stamps = verify_files(worker.store, snapshot)
    with worker.store.connect() as db:
        retry_wait = db.execute("SELECT 1 FROM steps WHERE run_id=? AND status='retry_wait' LIMIT 1", (row["run_id"],)).fetchone()
        published = db.execute("SELECT 1 FROM steps WHERE run_id=? AND stage='publish_v4' AND status='succeeded'", (row["run_id"],)).fetchone()
    finish(worker, row, "succeeded" if complete else "retry_wait" if retry_wait else "partial_failed" if published else "failed", None, stamps=stamps)


def finish(worker, row, status, code, *, stamps=None):
    worker.check(row)
    with worker.store.connect(write=True) as db:
        current = row_for(worker.store, db, row["run_id"])
        if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
            raise HTTPException(409, "오래된 S1 실행을 완료할 수 없습니다.")
        check_access(worker.store, db, current)
        if stamps is not None:
            check_stamps(worker.store, stamps)
        published = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='publish_v4' AND status='succeeded' ORDER BY rowid DESC LIMIT 1", (row["run_id"],)).fetchone()
        db.execute("UPDATE runs SET status=?,failure_code=?,result_ref=?,result_hash=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?",
            (status, code, published["output_ref"] if published and status in ("succeeded", "partial_failed") else None,
             published["output_hash"] if published and status in ("succeeded", "partial_failed") else None, now(), row["run_id"]))
