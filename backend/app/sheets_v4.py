"""S1 assigned sheets, immutable revisions and explicit disclosure; Excel stays gated."""

import hashlib
import json
import os
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from .domain.catalog_v4 import (ITEM_CODES, OPTIONAL_CODES, RESOURCES, VOCAL_CODES, ContractV4,
                                Text, load_catalog_v4, load_mapping_v4, load_rules_v4)
from .domain.contracts_v4 import LinkedMemoV4, ObservationV4, ScoreSheetV4, WalkPhaseV4
from .domain.media_v4 import MediaKey
from .domain.disclosures_v4 import InterpretationExposureV4
from .domain.sheets_v4 import AI_ACCOUNT, BatchPointerV4, SheetDocumentV4, SheetInputV4, SheetReferenceV4
from .domain.validation_v4 import validate_sheet_v4
from .intake import selected_session
from .input_models import Model
from .recording_v4 import build_windows_v4, observation_clear_v4, validate_recording_media_v4
from .sheets import manager, owner, reference
from .storage import encode, now, uid

Reason = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class SheetRevisionV4(ContractV4):
    expected_revision: Annotated[int, Field(ge=1)]


class SheetAssignmentV4(SheetRevisionV4):
    assigned_username: MediaKey
    rater_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
    rater_name: Reason
    purpose: Literal["independent", "review", "consensus"] = "independent"
    source_sheet_id: MediaKey | None = None
    batch_id: MediaKey | None = None
    preprocess: BatchPointerV4 | None = None


class SheetEditV4(SheetRevisionV4):
    observations: Annotated[list[ObservationV4], Field(max_length=86)]
    walk_phases: list[WalkPhaseV4] = Field(default_factory=list)
    linked_memos: list[LinkedMemoV4] = Field(default_factory=list)
    reason: Reason = "S1 원자료 저장"

    @field_validator("observations", "walk_phases", "linked_memos", mode="before")
    @classmethod
    def json_contracts(cls, value, info):
        contract = {"observations": ObservationV4, "walk_phases": WalkPhaseV4, "linked_memos": LinkedMemoV4}[info.field_name]
        return [contract.model_validate_json(json.dumps(item, ensure_ascii=False)) if isinstance(item, dict) else item for item in value]


class SheetReasonV4(SheetRevisionV4):
    reason: Reason


class SheetActiveV4(SheetReasonV4):
    active: bool


class SheetGrantV4(SheetReasonV4):
    target_sheet_id: MediaKey
    target_revision: Annotated[int, Field(ge=1)]


class SheetRevealV4(SheetRevisionV4):
    ref: Text


class SheetSummaryV4(Model):
    schema_version: Literal["4.0"] = "4.0"
    sheet_id: str
    case_id: str
    session_id: str
    rater_id: str
    rater_name: str
    assigned_username: str
    purpose: Literal["independent", "review", "consensus"]
    state: Literal["draft", "submitted"]
    revision: int
    manifest_ref: str
    manifest_hash: str
    source_hash: str
    active: bool
    own: bool
    rater_kind: Literal["human", "ai"]


class SheetViewV4(Model):
    summary: SheetSummaryV4
    document: SheetDocumentV4
    grants: list[SheetReferenceV4]
    outdated: bool
    missing_required_codes: list[str]
    policy_pending_codes: list[str]
    effective_purpose: Literal["independent", "review", "consensus"]
    interpretation_exposures: list[InterpretationExposureV4]

    @field_validator("document", mode="before")
    @classmethod
    def document_contract(cls, value):
        return SheetDocumentV4.model_validate_json(encode(value)) if isinstance(value, dict) else value

    @field_validator("grants", mode="before")
    @classmethod
    def grant_contracts(cls, value):
        return [SheetReferenceV4.model_validate_json(encode(item)) if isinstance(item, dict) else item for item in value]

    @field_validator("interpretation_exposures", mode="before")
    @classmethod
    def interpretation_contracts(cls, value):
        return [InterpretationExposureV4.model_validate_json(encode(item)) if isinstance(item, dict) else item for item in value]


class SheetRevealResultV4(Model):
    viewer: SheetSummaryV4
    target: SheetDocumentV4

    @field_validator("target", mode="before")
    @classmethod
    def target_contract(cls, value):
        return SheetDocumentV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


def asset_hashes():
    load_catalog_v4()
    for name in ("protocol", "scoring", "preprocess"):
        load_rules_v4(name)
    return {"catalog": hashlib.sha256((RESOURCES / "catalogs" / "behavior-v4.json").read_bytes()).hexdigest(),
            **{name: hashlib.sha256((RESOURCES / "rules" / f"{name}-v4.json").read_bytes()).hexdigest()
               for name in ("protocol", "scoring", "preprocess")}}


def _account(db, user):
    row = db.execute("SELECT active,role FROM users WHERE username=?", (user.username,)).fetchone()
    if not row or not row["active"] or row["role"] not in ("operator", "reviewer", "admin"):
        raise HTTPException(403, "채점 계정 권한이 없습니다.")
    return row


def _case(store, db, case_id, expected=None):
    row = store.case(db, case_id, expected=expected)
    manifest = store.manifest(row)
    if manifest.schema_version != "intake-4.0":
        raise HTTPException(409, "S1 초기화가 필요한 입력입니다.")
    if manifest.consents.analysis_feedback == "declined":
        raise HTTPException(403, "분석 동의가 거절된 자료입니다.")
    return row, manifest


def row_for(store, db, sheet_id, *, expected=None):
    row = db.execute("SELECT * FROM score_sheets WHERE sheet_id=?", (sheet_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "채점 시트를 찾을 수 없습니다.")
    _case(store, db, row["case_id"])
    if expected is not None and row["revision"] != expected:
        raise HTTPException(409, "다른 채점 변경이 저장되었습니다. 다시 조회하세요.")
    return row


def read_document(store, ref, digest):
    if not ref.startswith("sheets/"):
        raise HTTPException(409, "채점 파일 참조가 올바르지 않습니다.")
    try:
        payload = store.path(ref).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("sheet hash")
        doc = SheetDocumentV4.model_validate_json(payload)
        if hashlib.sha256(encode(doc.source.model_dump(mode="json")).encode()).hexdigest() != doc.source_hash:
            raise ValueError("source hash")
        parent = store.path(doc.source.input.manifest_ref).read_bytes()
        if hashlib.sha256(parent).hexdigest() != doc.source.input.manifest_hash:
            raise ValueError("parent input hash")
        raw = json.loads(parent)
        if raw.get("schema_version") != "intake-4.0" or raw.get("case_id") != doc.sheet.case_id or raw.get("input_revision") != doc.source.input_revision:
            raise ValueError("parent identity")
        session = next((value for value in raw["sessions"] if value["session_id"] == doc.sheet.session_id), None)
        if session != doc.source.session.model_dump(mode="json"):
            raise ValueError("source session differs from pinned parent")
        if doc.source.preprocess and hashlib.sha256(store.path(doc.source.preprocess.ref).read_bytes()).hexdigest() != doc.source.preprocess.hash:
            raise ValueError("pinned preprocess hash")
        return doc
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(409, "S1 채점 또는 부모 입력 파일의 판본·hash·내용이 일치하지 않습니다.") from exc


def document_for(store, row):
    doc = read_document(store, row["manifest_ref"], row["manifest_hash"])
    identity = (doc.sheet.sheet_id, doc.sheet.case_id, doc.sheet.session_id, doc.assigned_username, doc.sheet.rater_id,
                doc.rater_name, doc.source_hash, doc.purpose, doc.state, doc.active, doc.revision)
    if identity != tuple(row[key] for key in ("sheet_id", "case_id", "session_id", "assigned_username", "rater_id", "rater_name",
                                           "source_hash", "purpose", "state", "active", "revision")):
        raise HTTPException(409, "S1 채점 파일과 배정 참조가 다릅니다.")
    return doc


def summary(row, user):
    keys = ("sheet_id", "case_id", "session_id", "rater_id", "rater_name", "assigned_username", "purpose", "state", "revision",
            "manifest_ref", "manifest_hash", "source_hash")
    return {"schema_version": "4.0", **{key: row[key] for key in keys}, "active": bool(row["active"]),
            "own": row["assigned_username"] == user.username, "rater_kind": "ai" if row["assigned_username"] == AI_ACCOUNT else "human"}


def list_sheets(store, case_id, session_id, user):
    with store.connect() as db:
        account = _account(db, user)
        _, manifest = _case(store, db, case_id)
        if session_id not in {session.session_id for session in manifest.sessions}:
            raise HTTPException(404, "촬영 회차가 없습니다.")
        rows = db.execute("SELECT * FROM score_sheets WHERE case_id=? AND session_id=? ORDER BY rowid", (case_id, session_id))
        return [summary(row, user) for row in rows if row["assigned_username"] == user.username or account["role"] in ("operator", "admin")]


def missing_required(doc):
    rated = {item.code for item in load_catalog_v4().rated_items()} - set(OPTIONAL_CODES)
    return sorted(rated - {item.code for item in doc.sheet.observations})


def view(store, sheet_id, user):
    with store.connect() as db:
        row = row_for(store, db, sheet_id)
        owner(db, row, user)
        doc = document_for(store, row)
        grants = [{"sheet_id": item["target_sheet_id"], "revision": item["revision"], "ref": item["ref"], "hash": item["hash"]}
                  for item in db.execute("SELECT * FROM score_grants WHERE viewer_sheet_id=?", (sheet_id,))]
        case, _ = _case(store, db, row["case_id"])
        interpreted = interpretation_exposure(store, db, row, doc)
        return {"summary": summary(row, user), "document": doc.model_dump(mode="json"), "grants": grants,
                "outdated": doc.source.input_revision != case["input_revision"], "missing_required_codes": missing_required(doc),
                "policy_pending_codes": [item.code for item in load_catalog_v4().items if item.policy_pending],
                "effective_purpose": "review" if interpreted and doc.purpose == "independent" else doc.purpose,
                "interpretation_exposures": [entry.model_dump(mode="json") for entry in interpreted.values()]}


def revision(store, sheet_id, number, user):
    with store.connect() as db:
        row = row_for(store, db, sheet_id)
        owner(db, row, user)
        doc = document_for(store, row)
        if number == doc.revision:
            return doc
        link = next((value for value in doc.previous if value.revision == number), None)
        if link is None:
            raise HTTPException(404, "보존한 S1 revision이 아닙니다.")
        return read_document(store, link.ref, link.hash)


def write_document(store, data):
    doc = SheetDocumentV4.model_validate_json(encode(data))
    payload = doc.model_dump_json().encode()
    ref = f"sheets/{doc.sheet.case_id}/{doc.sheet.sheet_id}/r{doc.revision}-{uid()}.json"
    path = store.path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return ref, hashlib.sha256(payload).hexdigest()


def same_filming(one, two):
    return bool({video.sha256 for video in one.session.videos} & {video.sha256 for video in two.session.videos})


def _source_identities(store, source):
    capture = source.session.recording_s1
    used = {capture.video_id, *(value.video_id for value in capture.events),
            *(value.video_id for value in capture.video_offsets), *(value.video_id for value in capture.coverage)}
    refs = [source.input.manifest_ref, *(video.storage_ref for video in source.session.videos if video.video_id in used)]
    if source.preprocess:
        refs.append(source.preprocess.ref)
    try:
        return {ref: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                for ref in refs if (info := store.path(ref).stat())}
    except OSError as exc:
        raise HTTPException(409, "고정한 채점 원자료 파일에 접근할 수 없습니다.") from exc


def _unchanged_sources(store, source, identities):
    if identities != _source_identities(store, source):
        raise HTTPException(409, "검사 중 채점 원자료가 변경되었습니다.")


def _verify_preprocess(store, case_id, session_id, source, actor, *, historical):
    if source.preprocess is None:
        return
    from .domain.preprocess_v4 import FileV4
    from .preprocess_v4 import verified_batch
    pins = {"expected_input": FileV4(ref=source.input.manifest_ref, hash=source.input.manifest_hash),
            "expected_revision": source.input_revision} if historical else {}
    batch = verified_batch(store, case_id, session_id, source.preprocess, actor, **pins)
    if batch.batch_id != source.batch_id or batch.input_revision != source.input_revision:
        raise HTTPException(409, "전처리 snapshot이 채점 입력과 다릅니다.")


def related_exposure(store, db, row, doc):
    links, ai_exposed = {}, False
    rows = db.execute("SELECT * FROM score_sheets WHERE case_id=? AND session_id=? AND sheet_id!=? AND (assigned_username=? OR rater_id=?)",
                      (row["case_id"], row["session_id"], row["sheet_id"], row["assigned_username"], row["rater_id"]))
    for other in rows:
        other_doc = document_for(store, other)
        if same_filming(other_doc.source, doc.source):
            links.update({link.ref: link.model_dump(mode="json") for link in other_doc.exposures})
            ai_exposed = ai_exposed or other_doc.sheet.ai_exposed
    return links, ai_exposed


def interpretation_exposure(store, db, row, doc):
    from .disclosures_v4 import inherited
    records = {entry.exposure_id: entry for entry in doc.interpretation_exposures}
    records.update(inherited(db, row["case_id"], row["session_id"], row["assigned_username"], row["rater_id"], doc.source))
    return records


def assign(store, case_id, session_id, value: SheetAssignmentV4, user):
    manager(user)
    value = SheetAssignmentV4.model_validate_json(value.model_dump_json())
    assets = asset_hashes()
    with store.connect() as db:
        manager(user, db)
        case, manifest = _case(store, db, case_id, value.expected_revision)
        session = selected_session(manifest, session_id)
        account = db.execute("SELECT active,role FROM users WHERE username=?", (value.assigned_username,)).fetchone()
        if not account or not account["active"] or account["role"] not in ("operator", "reviewer", "admin") or value.assigned_username == AI_ACCOUNT:
            raise HTTPException(422, "활성 사람 평가 계정을 선택하세요.")
        if value.source_sheet_id:
            old = row_for(store, db, value.source_sheet_id)
            if (old["case_id"], old["session_id"]) != (case_id, session_id) or value.batch_id or value.preprocess:
                raise HTTPException(422, "같은 대상·회차의 원 snapshot은 batch를 바꾸지 않고 선택하세요.")
            source = document_for(store, old).source
        else:
            capture = getattr(session, "recording_s1", None)
            if capture is None or not capture.confirmed:
                raise HTTPException(422, "실제 촬영 기록을 먼저 확정하세요.")
            source = SheetInputV4.model_validate_json(encode({
                "input_revision": case["input_revision"], "input": {"manifest_ref": case["manifest_ref"], "manifest_hash": case["manifest_hash"]},
                "asset_hashes": assets, "session": session.model_dump(mode="json"),
                "windows": [window.model_dump(mode="json") for window in build_windows_v4(capture)],
                "batch_id": value.preprocess.batch_id if value.preprocess else value.batch_id or f"web-r{case['input_revision']}",
                "preprocess": value.preprocess.model_dump(mode="json") if value.preprocess else None}))
    if source.asset_hashes != assets:
        raise HTTPException(409, "현재 S1 계약과 다른 snapshot입니다.")
    _verify_preprocess(store, case_id, session_id, source, user.username, historical=value.source_sheet_id is not None)
    identities = _source_identities(store, source)
    validate_recording_media_v4(store, source.session, source.session.recording_s1)
    _unchanged_sources(store, source, identities)
    source_data = source.model_dump(mode="json")
    from .disclosures_v4 import inherited
    with store.connect() as db:
        interpreted = inherited(db, case_id, session_id, value.assigned_username, value.rater_id, source)
    purpose = "review" if interpreted and value.purpose == "independent" else value.purpose
    digest, sheet_id = hashlib.sha256(encode(source_data).encode()).hexdigest(), uid()
    data = {"revision": 1, "state": "draft", "assigned_username": value.assigned_username, "rater_name": value.rater_name,
            "purpose": purpose, "origin": "human_web", "active": True, "actor": user.username, "recorded_at": now(),
            "interpretation_exposures": [entry.model_dump(mode="json") for entry in interpreted.values()],
            "change_reason": "S1 명시 배정", "source": source_data, "source_hash": digest,
            "sheet": {"sheet_id": sheet_id, "case_id": case_id, "session_id": session_id, "batch_id": source.batch_id,
                      "rater_id": value.rater_id, "rater_kind": "human", "input_revision": source.input_revision,
                      "input_sha256": source.input.manifest_hash, "observations": []}}
    ref, file_hash = write_document(store, data)
    with store.connect(write=True) as db:
        manager(user, db)
        _case(store, db, case_id, value.expected_revision)
        _unchanged_sources(store, source, identities)
        if inherited(db, case_id, session_id, value.assigned_username, value.rater_id, source) != interpreted:
            raise HTTPException(409, "배정 중 같은 촬영의 해석을 열었습니다. 노출 이력을 다시 확인하세요.")
        account = db.execute("SELECT active,role FROM users WHERE username=?", (value.assigned_username,)).fetchone()
        if not account or not account["active"] or account["role"] not in ("operator", "reviewer", "admin"):
            raise HTTPException(409, "배정 계정 상태가 변경되었습니다.")
        for other in db.execute("SELECT * FROM score_sheets WHERE case_id=? AND session_id=?", (case_id, session_id)):
            if other["source_hash"] == digest and other["rater_id"] == value.rater_id and other["purpose"] == purpose:
                raise HTTPException(409, "같은 평가자·입력·목적의 시트가 있습니다.")
            if purpose == "independent" and (other["assigned_username"] == value.assigned_username or other["rater_id"] == value.rater_id):
                if same_filming(document_for(store, other).source, source):
                    raise HTTPException(409, "같은 촬영의 재배정·새 batch가 독립성을 초기화하지 않습니다.")
        db.execute("INSERT INTO score_sheets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (sheet_id, case_id, session_id, value.assigned_username,
                   value.rater_id, value.rater_name, digest, purpose, "draft", 1, 1, ref, file_hash))
        store.audit(db, user.username, case_id, "sheet.assign", {"sheet_id": sheet_id, "ref": ref, "hash": file_hash, "schema_version": "4.0"})
        return summary(row_for(store, db, sheet_id), user)


def _covered(ranges, start, end):
    cursor = start
    for low, high in sorted(ranges):
        if low > cursor:
            break
        cursor = max(cursor, high)
        if cursor >= end:
            return True
    return False


def _source_evidence(doc, evidence, *, code=None):
    capture = doc.source.session.recording_s1
    video = next((value for value in doc.source.session.videos if value.video_id == evidence.video_id), None)
    window = next((value for value in doc.source.windows if value.window_id == evidence.window_id), None)
    offset = capture.offset(evidence.video_id)
    if not video or video.sha256 != evidence.video_sha256 or getattr(video, "camera_id", None) != evidence.camera_id or offset is None:
        raise HTTPException(422, "근거 영상/hash/카메라/확정 동기화가 snapshot과 다릅니다.")
    if not window or window.status not in ("confirmed", "partial"):
        raise HTTPException(422, "미실시·미관찰·판본 미확인 창은 확정값 근거가 아닙니다.")
    start, end = evidence.start_seconds - offset, evidence.end_seconds - offset
    spans = [part for part in window.source_intervals if part.evidence_id is None]
    if not any(part.start_seconds <= start <= end <= part.end_seconds for part in spans):
        raise HTTPException(422, "근거 시각이 실제 관찰창의 분리된 구간 밖입니다.")
    if code in tuple(f"개{n}" for n in range(38, 44)):
        phase = next(value for value in doc.source.windows if value.window_id == f"walk_phase_{int(code[1:]) - 37}")
        if phase.start_seconds is None or not phase.start_seconds <= start <= end <= phase.end_seconds:
            raise HTTPException(422, "거리 근거가 해당 실제 걷기 국면 밖입니다.")
    return start, end


def validate_observations(doc, data, *, complete=False):
    sheet = ScoreSheetV4.model_validate_json(encode(data))
    catalog, protocol = load_catalog_v4(), load_rules_v4("protocol")
    # The six actual walking phases refine the catalog's parent walk_whole window.
    items = []
    for item in catalog.items:
        if item.code in tuple(f"개{n}" for n in range(38, 44)):
            item = item.model_copy(update={"windows": (*item.windows, f"walk_phase_{int(item.code[1:]) - 37}")})
        items.append(item)
    catalog = catalog.model_copy(update={"items": tuple(items)})
    protocol = {**protocol, "windows": [*protocol["windows"], *({"window_id": f"walk_phase_{n}"} for n in range(1, 7))]}
    validate_sheet_v4(sheet, catalog, protocol)
    required = {item.code for item in catalog.rated_items()} - set(OPTIONAL_CODES)
    if complete and required - {item.code for item in sheet.observations}:
        raise HTTPException(422, "필수 직접 입력84행 각각에 값 또는 명시한 빈값 상태·사유를 기록하세요.")
    windows = {window.window_id: window for window in doc.source.windows}
    capture = doc.source.session.recording_s1
    items = {item.code: item for item in catalog.items}
    for item in sheet.observations:
        full_ranges = {}
        clear_evidence = False
        for evidence in item.evidence:
            start, end = _source_evidence(doc, evidence, code=item.code)
            clear = observation_clear_v4(capture, evidence.video_id, evidence.start_seconds, evidence.end_seconds,
                                          modality="audio" if item.code in VOCAL_CODES else "visual", code=item.code)
            clear_evidence = clear_evidence or clear
            if clear and abs(evidence.observed_seconds - (end - start)) < 1e-6:
                full_ranges.setdefault(evidence.window_id, []).append((start, end))
        if item.status == "observed" and items[item.code].usage == "numeric" and not clear_evidence:
            raise HTTPException(422, "명시된 가림·신체 미관찰·음성 손실을 제외한 판독 근거가 필요합니다.")
        if item.status == "observed" and (items[item.code].whole_interval_required or item.code in VOCAL_CODES or item.code == "보23" and item.value == -2):
            interval_seconds = 0
            for key in items[item.code].windows:
                if key.startswith("walk_phase_"):
                    continue
                window = windows[key]
                spans = [part for part in window.source_intervals if part.evidence_id is None]
                if window.status != "confirmed" or not spans or not all(_covered(full_ranges.get(key, []), part.start_seconds, part.end_seconds) for part in spans):
                    raise HTTPException(422, "전체 관찰 항목은 실제 전체창 근거가 있어야 합니다. 일부 관찰은 null입니다.")
                interval_seconds += sum(part.end_seconds - part.start_seconds for part in spans)
            if item.vocalization and abs(item.vocalization.listened_seconds - interval_seconds) > 1e-6:
                raise HTTPException(422, "발성 청취 분모는 중복 없는 실제 전체 구간 길이여야 합니다.")
    for memo in sheet.linked_memos:
        if not set(memo.item_codes) <= set(ITEM_CODES):
            raise HTTPException(422, "개59 연결 항목이 S1 목록에 없습니다.")
        for evidence in memo.evidence:
            _source_evidence(doc, evidence)
    for phase in sheet.walk_phases:
        for evidence in phase.evidence:
            if evidence.window_id not in items[phase.code].windows:
                raise HTTPException(422, "근접 예외 근거가 해당 걷기 창과 다릅니다.")
            _source_evidence(doc, evidence, code=phase.code)
    return sheet


def analysis_input(doc: SheetDocumentV4) -> ScoreSheetV4:
    """F evidence is retained; G form-review notes are never analytic inputs."""
    data = ScoreSheetV4.model_validate(doc.sheet).model_dump(mode="json")
    for observation in data["observations"]:
        observation["review_memo"] = None
    return ScoreSheetV4.model_validate_json(encode(data))


def revise(store, sheet_id, value, user, action):
    if action not in ("save", "submit", "reopen", "assignment", "reveal"):
        raise HTTPException(422, "지원하지 않는 S1 채점 작업입니다.")
    with store.connect() as db:
        row = row_for(store, db, sheet_id, expected=value.expected_revision)
        case, _ = _case(store, db, row["case_id"])
        doc = document_for(store, row)
        if action in ("reopen", "assignment"):
            manager(user, db)
        else:
            owner(db, row, user)
        if action in ("save", "submit", "reopen") and doc.sheet.rater_kind != "human":
            raise HTTPException(403, "AI 원자료는 사람 저장으로 덮어쓰지 않습니다.")
        if action in ("save", "submit") and doc.state != "draft" or action == "reopen" and doc.state != "submitted":
            raise HTTPException(409, "현재 제출·잠금 상태에서 이 작업을 할 수 없습니다.")
        data = doc.model_dump(mode="json")
        data.update(revision=doc.revision + 1, actor=user.username, recorded_at=now(), change_reason=getattr(value, "reason", action),
                    previous=[*data["previous"], reference(row)])
        interpreted = interpretation_exposure(store, db, row, doc)
        data["interpretation_exposures"] = [entry.model_dump(mode="json") for entry in interpreted.values()]
        if interpreted and doc.purpose == "independent":
            data["purpose"] = "review"
        if action in ("save", "submit", "reopen"):
            inherited, exposed = related_exposure(store, db, row, doc)
            data["exposures"] = list({link["ref"]: link for link in [*data["exposures"], *inherited.values()]}.values())
            data["sheet"]["ai_exposed"] = doc.sheet.ai_exposed or exposed
            if data["exposures"] and doc.purpose == "independent":
                data["purpose"] = "review"
        if action == "save":
            value = SheetEditV4.model_validate_json(value.model_dump_json())
            data["sheet"].update(observations=[item.model_dump(mode="json") for item in value.observations],
                                  walk_phases=[item.model_dump(mode="json") for item in value.walk_phases],
                                  linked_memos=[item.model_dump(mode="json") for item in value.linked_memos])
        elif action == "submit":
            missing = set(OPTIONAL_CODES) - {item["code"] for item in data["sheet"]["observations"]}
            data["sheet"]["observations"].extend({"code": code, "value": None, "status": "unobserved", "reason": "선택 관찰 미실시"} for code in sorted(missing))
            data["state"] = "submitted"
        elif action == "reopen":
            data["state"] = "draft"
        elif action == "assignment":
            data["active"] = value.active
        elif action == "reveal":
            if doc.state != "submitted":
                raise HTTPException(409, "본인의 원자료를 먼저 제출해야 다른 완료본을 열 수 있습니다.")
            granted = db.execute("SELECT * FROM score_grants WHERE viewer_sheet_id=? AND ref=?", (sheet_id, value.ref)).fetchone()
            if not granted:
                raise HTTPException(403, "운영자가 명시 공개한 완료본이 아닙니다.")
            target_row = row_for(store, db, granted["target_sheet_id"])
            if not target_row["active"]:
                raise HTTPException(403, "공개 대상 배정이 취소되었습니다.")
            target = read_document(store, granted["ref"], granted["hash"])
            if target.source_hash != doc.source_hash or target.state != "submitted":
                raise HTTPException(409, "공개 완료본의 입력이 다릅니다.")
            link = {"sheet_id": granted["target_sheet_id"], "revision": granted["revision"], "ref": granted["ref"], "hash": granted["hash"]}
            if not any(item["ref"] == link["ref"] for item in data["exposures"]):
                data["exposures"].append(link)
            if doc.purpose == "independent":
                data["purpose"] = "review"
            data["sheet"]["ai_exposed"] = doc.sheet.ai_exposed or target.sheet.rater_kind == "ai"
        if doc.state == "submitted" and data["initial_submission"] is None and (action in ("reopen", "reveal") or data["purpose"] != doc.purpose):
            data["initial_submission"] = reference(row)
    if doc.source.asset_hashes != asset_hashes():
        raise HTTPException(409, "S1 입력 계약 hash가 현재 계약과 다릅니다.")
    _verify_preprocess(store, doc.sheet.case_id, doc.sheet.session_id, doc.source, user.username, historical=True)
    try:
        validated = validate_observations(doc, data["sheet"], complete=action == "submit")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    identities = _source_identities(store, doc.source)
    durations = validate_recording_media_v4(store, doc.source.session, doc.source.session.recording_s1)
    _unchanged_sources(store, doc.source, identities)
    for observation in (*validated.observations, *validated.linked_memos, *validated.walk_phases):
        if any(evidence.end_seconds > durations[evidence.video_id] for evidence in observation.evidence):
            raise HTTPException(422, "관찰 근거가 해당 영상의 실제 길이를 벗어납니다.")
    data["sheet"] = validated.model_dump(mode="json")
    ref, digest = write_document(store, data)
    with store.connect(write=True) as db:
        current = row_for(store, db, sheet_id, expected=value.expected_revision)
        _case(store, db, row["case_id"], case["input_revision"])
        _unchanged_sources(store, doc.source, identities)
        if action in ("reopen", "assignment"):
            manager(user, db)
        else:
            owner(db, current, user)
        if interpretation_exposure(store, db, current, doc) != interpreted:
            raise HTTPException(409, "저장 중 같은 촬영의 해석을 열었습니다. 노출 이력을 다시 확인하세요.")
        if action in ("save", "submit", "reopen"):
            inherited, exposed = related_exposure(store, db, current, doc)
            if not inherited.keys() <= {link["ref"] for link in data["exposures"]} or exposed and not data["sheet"]["ai_exposed"]:
                raise HTTPException(409, "같은 촬영의 다른 시트에서 결과를 열었습니다. 노출 이력을 다시 확인하세요.")
        if action == "reveal":
            grant_now = db.execute("SELECT * FROM score_grants WHERE viewer_sheet_id=? AND ref=?", (sheet_id, value.ref)).fetchone()
            if not grant_now or tuple(grant_now) != tuple(granted) or not row_for(store, db, granted["target_sheet_id"])["active"]:
                raise HTTPException(409, "공개 배정이 변경되었습니다.")
        db.execute("UPDATE score_sheets SET purpose=?,state=?,active=?,revision=?,manifest_ref=?,manifest_hash=? WHERE sheet_id=?",
                   (data["purpose"], data["state"], data["active"], data["revision"], ref, digest, sheet_id))
        store.audit(db, user.username, row["case_id"], "sheet." + action, {"sheet_id": sheet_id, "ref": ref, "hash": digest,
                    "revision": data["revision"], "reason": data["change_reason"], "schema_version": "4.0"})
        result = summary(row_for(store, db, sheet_id), user)
    return {"viewer": result, "target": target.model_dump(mode="json")} if action == "reveal" else result


def grant(store, sheet_id, value: SheetGrantV4, user):
    manager(user)
    with store.connect(write=True) as db:
        manager(user, db)
        viewer = row_for(store, db, sheet_id, expected=value.expected_revision)
        target = row_for(store, db, value.target_sheet_id, expected=value.target_revision)
        if viewer["sheet_id"] == target["sheet_id"] or any(viewer[key] != target[key] for key in ("source_hash", "case_id", "session_id")):
            raise HTTPException(422, "같은 입력의 다른 평가 완료본을 선택하세요.")
        if any(row["state"] != "submitted" or not row["active"] for row in (viewer, target)):
            raise HTTPException(409, "활성 배정의 원자료 두 개를 모두 제출하세요.")
        document_for(store, viewer)
        document_for(store, target)
        db.execute("INSERT OR IGNORE INTO score_grants VALUES (?,?,?,?,?,?,?)", (sheet_id, target["sheet_id"], target["manifest_ref"],
                   target["manifest_hash"], target["revision"], user.username, value.reason))
        store.audit(db, user.username, viewer["case_id"], "sheet.grant", {"viewer_sheet_id": sheet_id, "target_sheet_id": target["sheet_id"],
                    "ref": target["manifest_ref"], "hash": target["manifest_hash"], "reason": value.reason, "schema_version": "4.0"})
        return summary(viewer, user)


def workbook_preflight(cells: dict[str, object] | None = None):
    """Inspect declared mappings only; this never imports or approves a workbook."""
    mapping = load_mapping_v4("s1-input")
    differences, example_memos = [], []
    cells = cells or {}
    for entry in mapping["entries"]:
        address = entry["input_address"]
        sheet, cell = address.rsplit("!", 1)
        expected = f"='{sheet}'!{cell}"
        actual = cells.get(entry["internal_address"])
        if actual is not None and (not isinstance(actual, str) or actual.replace("$", "") not in (expected, f"={sheet}!{cell}")):
            differences.append({"code": entry["code"], "address": entry["internal_address"], "expected": expected, "actual": actual})
        for column in ("F", "G"):
            note_address = f"{sheet}!{column}{cell[1:]}"
            note = cells.get(note_address)
            if isinstance(note, str) and any(marker in note.lower() for marker in ("예시", "예제", "샘플", "example", "sample")):
                example_memos.append(note_address)
    return {"schema_version": "4.0", "excel_import_enabled": False, "physical_verification": "not_received_G01_G04",
            "mapping_version": mapping["version"], "entries": mapping["entries"], "differences": differences,
            "example_memo_addresses": sorted(set(example_memos)), "unverified_checks": ["physical_blank_template", "D_to_J_links",
            "H10_H15_proximity", "E40_completion_formula", "개58_개23_보12_wording", "example_memo_review"],
            "reason": "G01/G04 원본 빈양식과 승인 프로필이 없어 실제 Excel import는 비활성입니다."}


def import_workbook(*args, **kwargs):
    raise HTTPException(409, "G01/G04 원본 빈양식·승인 프로필 검증 전에는 실제 Excel import를 사용할 수 없습니다.")
