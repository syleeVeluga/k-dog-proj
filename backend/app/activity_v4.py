"""Explicit opens and bounded target history, using the existing changes ledger."""

import json

from fastapi import HTTPException
from .input_models import Model


class ActivityV4(Model):
    change_id: str
    actor: str
    happened_at: str
    target: str
    action: str
    revision: int | None = None
    session_id: str | None = None
    sheet_id: str | None = None
    format: str | None = None
    clip_id: str | None = None


class ActivityPageV4(Model):
    items: list[ActivityV4]
    next_offset: int | None
    before: int


def opened(store, user, target, action, value, purpose, **detail):
    if purpose == "open":
        with store.connect(write=True) as db:
            account = db.execute("SELECT active FROM users WHERE username=?", (user.username,)).fetchone()
            if not account or not account[0]:
                raise HTTPException(401, "활성 계정으로 다시 로그인하세요.")
            if detail.get("case_id"):
                store.case(db, detail["case_id"])
            store.audit(db, user.username, target, action, detail)
    return value


def recent(store, target, offset=0, *, before=None, case=False, registered_action=None):
    with store.connect() as db:
        if before is None:
            before = db.execute("SELECT COALESCE(MAX(rowid),0) FROM changes").fetchone()[0]
        if registered_action and not db.execute("SELECT 1 FROM changes WHERE target=? AND action=? LIMIT 1", (target, registered_action)).fetchone():
            raise HTTPException(404, "등록된 자료의 기록이 없습니다.")
        targets = {target}
        if case:
            store.case(db, target)
            targets.update(row[0] for row in db.execute("SELECT run_id FROM runs WHERE case_id=?", (target,)))
            targets.update(row[0] for row in db.execute("SELECT sheet_id FROM score_sheets WHERE case_id=?", (target,)))
            for row in db.execute("SELECT target,detail_json FROM changes WHERE rowid<=? AND (target=? OR json_extract(detail_json,'$.case_id')=? OR EXISTS (SELECT 1 FROM json_each(json_extract(detail_json,'$.case_ids')) WHERE value=?))", (before, target, target, target)):
                targets.add(row[0])
                detail = json.loads(row[1])
                targets.update(detail[key] for key in ("result_id", "opinion_id", "final_id", "sheet_id", "video_id") if isinstance(detail.get(key), str))
        marks = ",".join("?" for _ in targets)
        rows = db.execute(f"SELECT change_id,actor,happened_at,target,action,detail_json FROM changes WHERE target IN ({marks}) AND rowid<=? ORDER BY happened_at DESC,rowid DESC LIMIT 21 OFFSET ?", (*sorted(targets), before, offset)).fetchall()
    items = []
    for row in rows[:20]:
        detail = json.loads(row["detail_json"])
        items.append({key: row[key] for key in ("change_id", "actor", "happened_at", "target", "action")} | {
            key: detail[key] for key in ("revision", "session_id", "sheet_id", "format", "clip_id") if key in detail})
    return {"items": items, "next_offset": offset + 20 if len(rows) > 20 else None, "before": before}
