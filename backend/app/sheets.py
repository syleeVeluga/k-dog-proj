"""Assigned evaluator sheets with immutable revisions and explicit, recorded disclosure."""

import hashlib
import json
import os
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from app.domain.contracts_v3 import ObservationV3, ScoreSheetV3
from app.domain.sheets_v3 import SheetDocumentV3, SheetInputV3, SheetReferenceV3
from app.domain.validation_v3 import validate_sheet_v3
from app.input_models import Key, Model, Revision
from app.intake import selected_session
from app.preprocess import latest
from app.preprocess_v3 import ASSET_HASHES, CATALOG, PROTOCOL, verify_assets, window_plan
from app.recording_v3 import validate_recording_media
from app.storage import encode, now, uid

Reason = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class SheetAssignmentV3(Revision):
    assigned_username: Key
    rater_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
    rater_name: Reason
    purpose: Literal["independent", "review", "consensus"] = "independent"
    source_sheet_id: Key | None = None


class SheetEditV3(Revision):
    observations: Annotated[list[ObservationV3], Field(max_length=109)]

    @field_validator("observations", mode="before")
    @classmethod
    def contracts(cls, value):
        return [ObservationV3.model_validate_json(json.dumps(item)) if isinstance(item, dict) else item for item in value]


class SheetReasonV3(Revision):
    reason: Reason


class SheetActiveV3(SheetReasonV3):
    active: bool


class SheetGrantV3(SheetReasonV3):
    target_sheet_id: Key
    target_revision: Annotated[int, Field(ge=1)]


class SheetRevealV3(Revision):
    ref: str


class SheetSummaryV3(Model):
    sheet_id: str
    case_id: str
    session_id: str
    rater_id: str
    rater_name: str
    assigned_username: str
    purpose: str
    state: str
    active: bool
    revision: int
    manifest_ref: str
    manifest_hash: str
    source_hash: str
    own: bool


class SheetViewV3(Model):
    summary: SheetSummaryV3
    document: SheetDocumentV3
    outdated: bool
    grants: list[SheetReferenceV3]

    @field_validator("document", mode="before")
    @classmethod
    def document_contract(cls, value):
        return SheetDocumentV3.model_validate_json(json.dumps(value)) if isinstance(value, dict) else value

    @field_validator("grants", mode="before")
    @classmethod
    def grant_contract(cls, values):
        return [SheetReferenceV3.model_validate_json(json.dumps(value)) if isinstance(value, dict) else value for value in values]


class SheetRevealResultV3(Model):
    viewer: SheetSummaryV3
    target: SheetDocumentV3

    @field_validator("target", mode="before")
    @classmethod
    def target_contract(cls, value):
        return SheetDocumentV3.model_validate_json(json.dumps(value)) if isinstance(value, dict) else value


def row_for(store, db, sheet_id, *, expected=None):
    row = db.execute("SELECT * FROM score_sheets WHERE sheet_id=?", (sheet_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "채점 시트를 찾을 수 없습니다.")
    store.case(db, row["case_id"])
    if expected is not None and row["revision"] != expected:
        raise HTTPException(409, "다른 채점 변경이 저장되었습니다. 다시 조회하세요.")
    return row


def manager(user, db=None):
    if user.role not in ("operator", "admin"):
        raise HTTPException(403, "배정·공개·재개방은 운영자 권한입니다.")
    if db is not None:
        account = db.execute("SELECT role,active FROM users WHERE username=?", (user.username,)).fetchone()
        if not account or not account["active"] or account["role"] not in ("operator", "admin"):
            raise HTTPException(403, "운영 계정 권한이 변경되었습니다.")


def owner(db, row, user):
    account = db.execute("SELECT role,active FROM users WHERE username=?", (user.username,)).fetchone()
    if not account or not account["active"] or account["role"] not in ("operator", "reviewer", "admin") or row["assigned_username"] != user.username or not row["active"]:
        raise HTTPException(403, "활성 상태로 본인에게 배정된 시트만 조회·입력할 수 있습니다.")


def read_document(store, ref, digest):
    if not ref.startswith("sheets/"):
        raise HTTPException(409, "채점 파일 참조가 올바르지 않습니다.")
    try:
        data = store.path(ref).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("hash")
        doc = SheetDocumentV3.model_validate_json(data)
        if hashlib.sha256(encode(doc.source.model_dump(mode="json")).encode()).hexdigest() != doc.source_hash:
            raise ValueError("source hash")
        parent = store.path(doc.source.input.manifest_ref).read_bytes()
        if hashlib.sha256(parent).hexdigest() != doc.source.input.manifest_hash:
            raise ValueError("input hash")
        return doc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "채점 또는 부모 입력 파일이 손상되었습니다. 저장소를 확인하세요.") from exc


def document_for(store, row):
    doc = read_document(store, row["manifest_ref"], row["manifest_hash"])
    identity = (doc.sheet.sheet_id, doc.sheet.case_id, doc.sheet.session_id, doc.assigned_username, doc.sheet.rater_id,
                doc.rater_name, doc.source_hash, doc.purpose, doc.state, doc.active, doc.revision)
    if identity != tuple(row[key] for key in ("sheet_id", "case_id", "session_id", "assigned_username", "rater_id", "rater_name", "source_hash", "purpose", "state", "active", "revision")):
        raise HTTPException(409, "채점 파일과 배정 참조가 일치하지 않습니다.")
    return doc


def reference(row):
    return {"sheet_id": row["sheet_id"], "revision": row["revision"], "ref": row["manifest_ref"], "hash": row["manifest_hash"]}


def summary(row, user):
    return {**{key: row[key] for key in SheetSummaryV3.model_fields if key not in ("own", "active")},
            "active": bool(row["active"]), "own": row["assigned_username"] == user.username}


def list_sheets(store, case_id, session_id, user):
    with store.connect() as db:
        case = store.case(db, case_id)
        selected_session(store.manifest(case), session_id)
        rows = db.execute("SELECT * FROM score_sheets WHERE case_id=? AND session_id=? ORDER BY rowid", (case_id, session_id)).fetchall()
        return [summary(row, user) for row in rows if row["assigned_username"] == user.username or user.role in ("operator", "admin")]


def view(store, sheet_id, user):
    with store.connect() as db:
        row = row_for(store, db, sheet_id)
        owner(db, row, user)
        doc = document_for(store, row)
        grants = [{"sheet_id": item["target_sheet_id"], "revision": item["revision"], "ref": item["ref"], "hash": item["hash"]}
                  for item in db.execute("SELECT * FROM score_grants WHERE viewer_sheet_id=?", (sheet_id,))]
        case = store.case(db, row["case_id"])
        return {"summary": summary(row, user), "document": doc.model_dump(mode="json"),
                "outdated": doc.source.input_revision != case["input_revision"], "grants": grants}


def revision(store, sheet_id, number, user):
    with store.connect() as db:
        row = row_for(store, db, sheet_id)
        owner(db, row, user)
        doc = document_for(store, row)
        if number == doc.revision:
            return doc
        ref = next((item for item in doc.previous if item.revision == number), None)
        if ref is None:
            raise HTTPException(404, "보존한 채점 revision이 아닙니다.")
        return read_document(store, ref.ref, ref.hash)


def write_document(store, data):
    doc = SheetDocumentV3.model_validate_json(encode(data))
    payload = doc.model_dump_json().encode("utf-8")
    ref = f"sheets/{doc.sheet.case_id}/{doc.sheet.sheet_id}/r{doc.revision}-{uid()}.json"
    path = store.path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return ref, hashlib.sha256(payload).hexdigest()


def assign(store, case_id, session_id, value, user):
    manager(user)
    verify_assets()
    with store.connect() as db:
        case = store.case(db, case_id, expected=value.expected_revision)
        session = selected_session(store.manifest(case), session_id)
        account = db.execute("SELECT * FROM users WHERE username=? AND active=1", (value.assigned_username,)).fetchone()
        if not account or account["role"] not in ("operator", "reviewer", "admin"):
            raise HTTPException(422, "활성 평가 계정을 선택하세요. 임의 대리 입력은 허용되지 않습니다.")
        if value.source_sheet_id:
            old = row_for(store, db, value.source_sheet_id)
            if (old["case_id"], old["session_id"]) != (case_id, session_id):
                raise HTTPException(422, "같은 참가자·회차의 입력 snapshot을 선택하세요.")
            source = document_for(store, old).source.model_dump(mode="json")
        else:
            planned = window_plan(session)
            batch = latest(store, db, case_id, session_id)
            pointer = None
            if batch and batch.get("schema_version") == "3.0" and batch["input_revision"] == case["input_revision"] and all(batch[key] == ASSET_HASHES[key] for key in ASSET_HASHES):
                planned["windows"] = batch["windows"]
                entry = next(json.loads(item[0]) for item in db.execute("SELECT detail_json FROM changes WHERE target=? AND action='preprocess.complete' ORDER BY rowid DESC", (case_id,)) if json.loads(item[0]).get("session_id") == session_id)
                pointer = {"ref": entry["ref"], "hash": entry["hash"]}
            source = {"input_revision": case["input_revision"], "input": {"manifest_ref": case["manifest_ref"], "manifest_hash": case["manifest_hash"]},
                      "catalog_hash": ASSET_HASHES["catalog_hash"], "protocol_hash": ASSET_HASHES["protocol_hash"], "window_rules_hash": ASSET_HASHES["rules_hash"],
                      "session": session.model_dump(mode="json"), "windows": planned["windows"], "preprocess": pointer}
    source_model = SheetInputV3.model_validate_json(encode(source))
    source = source_model.model_dump(mode="json")
    validate_recording_media(store, source_model.session, source_model.session.recording)
    digest = hashlib.sha256(encode(source).encode()).hexdigest()
    sheet_id = uid()
    data = {"revision": 1, "state": "draft", "assigned_username": value.assigned_username, "rater_name": value.rater_name,
            "purpose": value.purpose, "active": True, "actor": user.username, "recorded_at": now(), "change_reason": "명시 배정",
            "source": source, "source_hash": digest, "sheet": {"sheet_id": sheet_id, "case_id": case_id, "session_id": session_id,
            "rater_id": value.rater_id, "rater_kind": "human", "observations": []}}
    ref, file_digest = write_document(store, data)
    with store.connect(write=True) as db:
        manager(user, db)
        store.case(db, case_id, expected=value.expected_revision)
        account = db.execute("SELECT role,active FROM users WHERE username=?", (value.assigned_username,)).fetchone()
        if not account or not account["active"] or account["role"] not in ("operator", "reviewer", "admin"):
            raise HTTPException(409, "배정 계정 상태가 변경되었습니다.")
        existing = db.execute("SELECT * FROM score_sheets WHERE case_id=? AND session_id=?", (case_id, session_id)).fetchall()
        for other in existing:
            if other["source_hash"] == digest and other["rater_id"] == value.rater_id and other["purpose"] == value.purpose:
                raise HTTPException(409, "같은 평가자·입력·목적의 시트가 이미 배정되어 있습니다.")
            if value.purpose == "independent" and (other["assigned_username"] == value.assigned_username or other["rater_id"] == value.rater_id):
                old_source = document_for(store, other).source
                if same_filming(old_source, source_model):
                    raise HTTPException(409, "같은 촬영 입력의 독립 시트가 이 계정 또는 평가자에 이미 배정되어 있습니다. 전처리 재실행은 독립성을 초기화하지 않습니다.")
        db.execute("INSERT INTO score_sheets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (sheet_id, case_id, session_id, value.assigned_username, value.rater_id, value.rater_name, digest, value.purpose, "draft", 1, 1, ref, file_digest))
        store.audit(db, user.username, case_id, "sheet.assign", {"sheet_id": sheet_id, "ref": ref, "hash": file_digest, "rater_id": value.rater_id, "assigned_username": value.assigned_username})
        return summary(row_for(store, db, sheet_id), user)


def validate_observations(doc, observations, *, complete=False):
    sheet = ScoreSheetV3.model_validate_json(encode({**doc.sheet.model_dump(mode="json"), "observations": observations}))
    validate_sheet_v3(sheet, CATALOG, PROTOCOL)
    if complete and {item.code for item in sheet.observations} != {item.code for item in CATALOG.rated_items()}:
        raise HTTPException(422, "직접 입력109행 각각에 원값 또는 빈칸 상태/사유를 기록하세요.")
    videos = {video.video_id: video for video in doc.source.session.videos}
    windows = {window.window_id: window for window in doc.source.windows}
    offsets = {offset.video_id: offset.offset_seconds for offset in doc.source.session.recording.video_offsets if offset.confirmed}
    for item in sheet.observations:
        if item.vocalization:
            vocal_video = item.vocalization.video_id
            if vocal_video not in videos or vocal_video != doc.source.session.recording.video_id and vocal_video not in offsets:
                raise HTTPException(422, "청취 원본은 입력 snapshot의 기준 영상 또는 동기화 확정 영상이어야 합니다.")
        if complete and item.status == "observed" and not item.evidence:
            raise HTTPException(422, f"{item.code}: 관찰한 값의 실제 영상·창 근거를 기록하세요.")
        for evidence in item.evidence:
            video, window = videos.get(evidence.video_id), windows.get(evidence.window_id)
            shift = offsets.get(evidence.video_id, 0)
            if not video or video.sha256 != evidence.video_sha256 or evidence.video_id != doc.source.session.recording.video_id and evidence.video_id not in offsets:
                raise HTTPException(422, "근거 영상/hash/수동 동기화가 입력 snapshot과 다릅니다.")
            if not window or window.status not in ("available", "partial"):
                raise HTTPException(422, "미실시·미관찰 창을 관찰 근거로 사용하지 마세요.")
            pieces = [window]
            if window.window_id in ("entry_leash", "exit_leash"):
                pieces = [part for part in doc.source.windows if part.window_id in (window.window_id + "_before", window.window_id + "_after")
                          and part.status in ("available", "partial") and set(part.clip_names) & set(window.clip_names)]
            ranges = [(part.start_sec if part.start_sec is not None else part.source_point_sec,
                       part.end_sec if part.end_sec is not None else part.source_point_sec) for part in pieces]
            if not any(start is not None and end is not None and start <= evidence.start_seconds - shift <= evidence.end_seconds - shift <= end for start, end in ranges):
                raise HTTPException(422, "근거 시각이 고정한 실제 관찰창 밖입니다.")
    return sheet.model_dump(mode="json")


def same_filming(one, two):
    # Metadata, timing corrections and batch retries cannot make previously seen footage blind again.
    return (one.catalog_hash == two.catalog_hash and one.protocol_hash == two.protocol_hash
            and bool({video.sha256 for video in one.session.videos} & {video.sha256 for video in two.session.videos}))


def related_exposure(store, db, row, doc):
    links, ai_exposed = {}, False
    for other in db.execute("SELECT * FROM score_sheets WHERE case_id=? AND session_id=? AND sheet_id!=? AND (assigned_username=? OR rater_id=?)",
                            (row["case_id"], row["session_id"], row["sheet_id"], row["assigned_username"], row["rater_id"])):
        other_doc = document_for(store, other)
        if not same_filming(other_doc.source, doc.source):
            continue
        for link in other_doc.exposures:
            links[link.ref] = link.model_dump(mode="json")
        ai_exposed = ai_exposed or other_doc.sheet.ai_exposed
    return links, ai_exposed


def revise(store, sheet_id, value, user, action):
    with store.connect() as db:
        row = row_for(store, db, sheet_id, expected=value.expected_revision)
        case_revision = store.case(db, row["case_id"])["input_revision"]
        doc = document_for(store, row)
        if action in ("save", "submit") and doc.sheet.rater_kind != "human":
            raise HTTPException(403, "AI 원채점은 사람이 덮어쓰지 않습니다. 별도 검수 시트를 사용하세요.")
        if action in ("reopen", "assignment"):
            manager(user)
        else:
            owner(db, row, user)
        if action in ("save", "submit") and doc.state != "draft":
            raise HTTPException(409, "제출한 원본은 잠겼습니다. 운영자에게 재개방을 요청하세요.")
        if action == "reopen" and doc.state != "submitted":
            raise HTTPException(409, "제출한 시트만 재개방할 수 있습니다.")
        data = doc.model_dump(mode="json")
        data.update(revision=doc.revision + 1, actor=user.username, recorded_at=now(), change_reason=getattr(value, "reason", action),
                    previous=[*data["previous"], reference(row)])
        if action in ("save", "submit", "reopen"):
            inherited, ai_exposed = related_exposure(store, db, row, doc)
            data["exposures"] = list({link["ref"]: link for link in [*data["exposures"], *inherited.values()]}.values())
            data["sheet"]["ai_exposed"] = doc.sheet.ai_exposed or ai_exposed
            if data["exposures"] and doc.purpose == "independent":
                data["purpose"] = "review"
                if doc.state == "submitted" and doc.initial_submission is None:
                    data["initial_submission"] = reference(row)
        if action == "save":
            try:
                data["sheet"]["observations"] = validate_observations(doc, [item.model_dump(mode="json") for item in value.observations])["observations"]
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        elif action == "submit":
            validate_observations(doc, data["sheet"]["observations"], complete=True)
            data["state"] = "submitted"
        elif action == "reopen":
            data["state"] = "draft"
        elif action == "assignment":
            data["active"] = value.active
        elif action == "reveal":
            if doc.state != "submitted":
                raise HTTPException(409, "독립 원자료를 먼저 제출해야 공개된 다른 결과를 열 수 있습니다.")
            grant = db.execute("SELECT * FROM score_grants WHERE viewer_sheet_id=? AND ref=?", (sheet_id, value.ref)).fetchone()
            if not grant:
                raise HTTPException(403, "운영자가 명시적으로 공개한 완료본이 아닙니다.")
            target = read_document(store, grant["ref"], grant["hash"])
            if not row_for(store, db, grant["target_sheet_id"])["active"]:
                raise HTTPException(403, "공개 대상의 배정이 취소되었습니다.")
            if target.source_hash != doc.source_hash or target.state != "submitted":
                raise HTTPException(409, "공개 결과의 입력 또는 완료 상태가 일치하지 않습니다.")
            link = {"sheet_id": grant["target_sheet_id"], "revision": grant["revision"], "ref": grant["ref"], "hash": grant["hash"]}
            if not any(item["ref"] == link["ref"] for item in data["exposures"]):
                data["exposures"].append(link)
            data["purpose"] = "review" if doc.purpose == "independent" else doc.purpose
            data["sheet"]["ai_exposed"] = doc.sheet.ai_exposed or target.sheet.rater_kind == "ai"
        if action in ("reopen", "reveal") and doc.initial_submission is None:
            data["initial_submission"] = reference(row)
    verify_assets()
    if doc.source.catalog_hash != ASSET_HASHES["catalog_hash"] or doc.source.protocol_hash != ASSET_HASHES["protocol_hash"]:
        raise HTTPException(409, "입력 계약 판본/hash가 현재 채점 계약과 다릅니다.")
    durations = validate_recording_media(store, doc.source.session, doc.source.session.recording)
    for observation in data["sheet"]["observations"]:
        if any(evidence["end_seconds"] > durations[evidence["video_id"]] for evidence in observation["evidence"]):
            raise HTTPException(422, "근거 시각이 선택한 원본 영상의 실제 길이를 벗어납니다.")
    ref, digest = write_document(store, data)
    with store.connect(write=True) as db:
        current = row_for(store, db, sheet_id, expected=value.expected_revision)
        store.case(db, row["case_id"], expected=case_revision)
        if action not in ("reopen", "assignment"):
            owner(db, current, user)
        else:
            manager(user, db)
        if action in ("save", "submit", "reopen"):
            inherited, ai_exposed = related_exposure(store, db, current, doc)
            if not inherited.keys() <= {link["ref"] for link in data["exposures"]} or ai_exposed and not data["sheet"]["ai_exposed"]:
                raise HTTPException(409, "같은 입력의 다른 시트에서 결과를 열었습니다. 다시 조회한 뒤 검수 기록으로 저장하세요.")
        if action == "reveal" and not db.execute("SELECT 1 FROM score_grants WHERE viewer_sheet_id=? AND ref=?", (sheet_id, value.ref)).fetchone():
            raise HTTPException(409, "공개 배정이 변경되었습니다.")
        if action == "reveal" and not row_for(store, db, grant["target_sheet_id"])["active"]:
            raise HTTPException(403, "공개 대상의 배정이 취소되었습니다.")
        db.execute("UPDATE score_sheets SET purpose=?,state=?,active=?,revision=?,manifest_ref=?,manifest_hash=? WHERE sheet_id=?", (data["purpose"], data["state"], data["active"], data["revision"], ref, digest, sheet_id))
        store.audit(db, user.username, row["case_id"], "sheet." + action, {"sheet_id": sheet_id, "ref": ref, "hash": digest, "revision": data["revision"], "reason": data["change_reason"]})
        result = summary(row_for(store, db, sheet_id), user)
    if action == "reveal":
        return {"viewer": result, "target": target.model_dump(mode="json")}
    return result


def grant(store, sheet_id, value, user):
    manager(user)
    with store.connect(write=True) as db:
        manager(user, db)
        viewer = row_for(store, db, sheet_id, expected=value.expected_revision)
        target = row_for(store, db, value.target_sheet_id, expected=value.target_revision)
        if viewer["sheet_id"] == target["sheet_id"] or viewer["source_hash"] != target["source_hash"] or viewer["case_id"] != target["case_id"] or viewer["session_id"] != target["session_id"]:
            raise HTTPException(422, "같은 입력의 다른 평가 완료본을 선택하세요.")
        if viewer["state"] != "submitted" or target["state"] != "submitted" or not viewer["active"] or not target["active"]:
            raise HTTPException(409, "두 평가의 원자료를 먼저 제출해야 공개할 수 있습니다.")
        document_for(store, viewer)
        document_for(store, target)
        db.execute("INSERT INTO score_grants VALUES (?,?,?,?,?,?,?)", (sheet_id, target["sheet_id"], target["manifest_ref"], target["manifest_hash"], target["revision"], user.username, value.reason))
        store.audit(db, user.username, viewer["case_id"], "sheet.grant", {"viewer_sheet_id": sheet_id, "target_sheet_id": target["sheet_id"], "ref": target["manifest_ref"], "hash": target["manifest_hash"], "reason": value.reason})
        return summary(viewer, user)
