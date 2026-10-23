"""Read-only projections of individual preprocessing attempts from the audit ledger."""

import json

from fastapi import HTTPException

from . import preprocess_v4 as preprocess
from .domain.preprocess_v4 import (FileV4, PreprocessExecutionDetailV4,
                                    PreprocessExecutionPageV4, PreprocessExecutionV4)
from .maintenance import runtime_lock

IDENTITY = ("session_id", "batch_id", "claim_token", "request_id", "request_hash", "input_revision")


def _active_claim(store, db):
    try:
        with runtime_lock(store, "preprocess"):
            return None
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
    latest = db.execute("SELECT target,detail_json FROM changes WHERE action='preprocess_v4.started' "
                        "ORDER BY rowid DESC LIMIT 1").fetchone()
    return (latest["target"], json.loads(latest["detail_json"]).get("claim_token")) if latest else None


def _project(store, db, start, actor, active):
    detail = json.loads(start["detail_json"])
    case_id, session_id = start["target"], detail["session_id"]
    case, _ = preprocess._case(store, db, case_id, session_id, actor, selected=False)
    events = []
    for row in db.execute("SELECT rowid,action,actor,happened_at,detail_json FROM changes WHERE target=? "
                          "AND rowid>? AND action IN ('preprocess_v4.progress','preprocess_v4.completed',"
                          "'preprocess_v4.failed','preprocess_v4.superseded') ORDER BY rowid DESC",
                          (case_id, start["rowid"])):
        value = json.loads(row["detail_json"])
        if row["actor"] == start["actor"] and all(value.get(key) == detail.get(key) for key in IDENTITY):
            events.append((row, value))
    terminal = next(((row, value) for row, value in events if row["action"] != "preprocess_v4.progress"), None)
    stage = next(((row, value) for row, value in events if row["action"] == "preprocess_v4.progress"), None)
    state = "running" if active == (case_id, detail["claim_token"]) else "interrupted"
    message = "전처리 실행 중" if state == "running" else "중단된 전처리입니다. 새 요청으로 다시 시작하세요."
    pointer, batch, finished = None, None, None
    outdated = detail["input_revision"] != case["input_revision"] or session_id != case["selected_session_id"]
    if terminal:
        row, value = terminal
        finished = row["happened_at"]
        if row["action"] == "preprocess_v4.completed":
            try:
                candidate = FileV4(ref=value["ref"], hash=value["hash"])
                batch = preprocess._load_batch(store, db, case_id, session_id, candidate)
                if (batch.batch_id, batch.claim_token, batch.request.request_id, batch.input_revision) != (
                        detail["batch_id"], detail["claim_token"], detail["request_id"], detail["input_revision"]):
                    raise HTTPException(409, "전처리 실행과 결과 식별자가 다릅니다.")
                if preprocess._digest(batch.request.model_dump(mode="json")) != detail["request_hash"]:
                    raise HTTPException(409, "전처리 요청 내용이 다릅니다.")
                preprocess._verify_files(store, (batch.input, *batch.source_files, *preprocess._artifacts(batch)))
                state, pointer = batch.status, candidate
                outdated = outdated or batch.asset_hashes != preprocess._assets()
                message = "전처리 완료" if state == "complete" else "일부 전처리 결과를 확인하세요."
            except (HTTPException, OSError, ValueError, KeyError):
                state, batch = "failed", None
                message = "전처리 결과 파일·연결을 확인할 수 없습니다. 새 요청으로 다시 시작하세요."
        else:
            state, message = "failed", value.get("message", "전처리 점유가 대체되었습니다.")
    return PreprocessExecutionDetailV4(execution_id=detail["batch_id"], case_id=case_id, session_id=session_id,
        participant_id=case["participant_id"], dog_name=case["dog_name"], event_id=case["event_id"],
        sequence_no=case["sequence_no"], guardian_name=case["guardian_name"],
        input_revision=detail["input_revision"], request_id=detail["request_id"], requested_by=start["actor"],
        started_at=start["happened_at"], finished_at=finished, status=state, message=message, outdated=outdated,
        current_stage=stage[1].get("stage") if stage else None,
        stage_updated_at=stage[0]["happened_at"] if stage else None, result_pointer=pointer, result=batch)


def executions(store, actor, *, cursor=None, search="", event_id="", status="all", request_id=None, case_id=None):
    with store.connect() as db:
        account = db.execute("SELECT active FROM users WHERE username=?", (actor,)).fetchone()
        if not account or not account["active"]:
            raise HTTPException(403, "전처리 자료 접근 권한이 없습니다.")
        starts = db.execute("SELECT rowid,* FROM changes WHERE action='preprocess_v4.started' AND actor=? "
                            "AND (? IS NULL OR rowid<?) ORDER BY rowid DESC", (actor, cursor, cursor)).fetchall()
        active = _active_claim(store, db)
        found = []
        for start in starts:
            if case_id is not None and start["target"] != case_id:
                continue
            detail = json.loads(start["detail_json"])
            if request_id is not None and detail.get("request_id") != request_id:
                continue
            try:
                item = _project(store, db, start, actor, active)
            except HTTPException as exc:
                if exc.status_code not in (404, 409):
                    raise
                continue
            if event_id and item.event_id != event_id:
                continue
            if search.casefold() not in f"{item.participant_id} {item.sequence_no or ''} {item.dog_name} {item.guardian_name}".casefold():
                continue
            if (status == "running" and item.status != "running" or
                    status == "complete" and item.status != "complete" or
                    status == "attention" and item.status not in ("partial", "failed", "interrupted") and not item.outdated):
                continue
            found.append((start["rowid"], item))
            if len(found) == 51:
                break
    items = [PreprocessExecutionV4.model_validate(item.model_dump(exclude={"result"})) for _, item in found[:50]]
    return PreprocessExecutionPageV4(items=items, next_cursor=found[49][0] if len(found) > 50 else None)


def execution(store, case_id, session_id, execution_id, actor):
    with store.connect() as db:
        preprocess._case(store, db, case_id, session_id, actor, selected=False)
        starts = db.execute("SELECT rowid,* FROM changes WHERE target=? AND action='preprocess_v4.started' "
                            "ORDER BY rowid DESC", (case_id,)).fetchall()
        start = next((row for row in starts if json.loads(row["detail_json"]).get("batch_id") == execution_id
                      and json.loads(row["detail_json"]).get("session_id") == session_id), None)
        if start is None:
            raise HTTPException(404, "이 회차의 전처리 실행을 찾을 수 없습니다.")
        return _project(store, db, start, actor, _active_claim(store, db))
