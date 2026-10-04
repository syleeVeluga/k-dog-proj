"""Reference comparison imports preserve provenance without writing an S1 score sheet."""
import hashlib
import json
from pathlib import PurePath
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from . import analysis, s1_workbook
from .domain.catalog_v4 import ITEM_CODES, Text
from .domain.media_v4 import MediaKey
from .domain.preprocess_v4 import FileV4
from .domain.validation_data_v4 import (ReferenceBindingV4, ReferenceCellV4, ReferenceRowV4,
    ReferenceSelectionV4, ValidationDocumentV4, ValidationReferenceV4)
from .input_models import Model
from .input_models_v4 import ManifestV4
from .report_runs_v4 import _read_file, _write_bytes, check_stamps
from .sheets_v4 import manager
from .storage import encode, now, uid

INVENTORY = {"184b1f8a58624fe0f34a0669f08410d4a3b7b072776a859c2e65feb5382a5178": "SRC05",
    "189d70cc29c6d6d4d06c9f267704f8211337a11d47f57f1444c34901cc8879d3": "SRC06",
    "8f5848f6f4479383778e0487decc69d69f80feb446e0a85f39f7974594b586ea": "SRC07"}
RECHECK = frozenset(("개8", "개10", "개12", "개30", "개34"))
ACTION = "validation.s1.register"
DELETED_SOURCE = "validation.s1.deleted_source"


class ValidationImportV4(Model):
    request_id: MediaKey
    filename: str = Field(min_length=1, max_length=240)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bindings: list[ReferenceBindingV4] = Field(default_factory=list, max_length=100)
    selections: list[ReferenceSelectionV4] = Field(min_length=1, max_length=2000)
    reason: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]

    @field_validator("bindings", "selections", mode="before")
    @classmethod
    def contracts(cls, value, info):
        kind = ReferenceBindingV4 if info.field_name == "bindings" else ReferenceSelectionV4
        return [kind.model_validate_json(encode(item)) if isinstance(item, dict) else item for item in value]


class ValidationViewV4(Model):
    reference: ValidationReferenceV4
    filename: str
    actor: str
    source_inventory_id: str | None
    row_count: int
    mapped_subject_count: int
    reference_only: Literal[True] = True
    score_import_enabled: Literal[False] = False
    ground_truth_status: Literal["pending_G03"] = "pending_G03"

    @field_validator("reference", mode="before")
    @classmethod
    def pointer(cls,value):
        return ValidationReferenceV4.model_validate_json(encode(value)) if isinstance(value,dict) else value


class ValidationFullViewV4(ValidationViewV4):
    document: ValidationDocumentV4

    @field_validator("document", mode="before")
    @classmethod
    def saved_document(cls,value):
        return ValidationDocumentV4.model_validate_json(encode(value)) if isinstance(value,dict) else value


class ValidationBlockedV4(Model):
    validation_id: str
    status: Literal["blocked"] = "blocked"
    reason: str


ValidationHistoryV4 = ValidationViewV4 | ValidationBlockedV4


class ValidationPreviewV4(Model):
    profile: dict
    source_sha256: str
    source_inventory_id: str | None
    cells: list[ReferenceCellV4]
    rows: list[ReferenceRowV4]
    bindings: list[ReferenceBindingV4]

    @field_validator("cells", "rows", "bindings", mode="before")
    @classmethod
    def contracts(cls,value,info):
        kind = {"cells":ReferenceCellV4,"rows":ReferenceRowV4,"bindings":ReferenceBindingV4}[info.field_name]
        return [kind.model_validate_json(encode(item)) if isinstance(item,dict) else item for item in value]


def _account(db, user):
    manager(user, db)


def deletion_sources(db):
    deleted = {row[0] for row in db.execute("SELECT case_id FROM cases WHERE deletion_requested=1")}
    hashes = {json.loads(row[0])["source_sha256"] for row in db.execute("SELECT detail_json FROM changes WHERE action=?",(DELETED_SOURCE,))}
    for row in db.execute("SELECT detail_json FROM changes WHERE action=?",(ACTION,)):
        record = json.loads(row[0])
        if deleted.intersection(record.get("case_ids",())):
            hashes.add(record["source_sha256"])
    return hashes


def remember_deleted_sources(db, hashes, actor):
    known = {row[0] for row in db.execute("SELECT target FROM changes WHERE action=?",(DELETED_SOURCE,))}
    for digest in set(hashes)-known:
        db.execute("INSERT INTO changes VALUES(?,?,?,?,?,?)",(uid(),actor,now(),digest,DELETED_SOURCE,encode({"source_sha256":digest})))


def _source_allowed(db, digest):
    if digest in deletion_sources(db):
        raise HTTPException(403,"삭제 대상이 포함된 전체 참고 원본은 다시 등록하거나 열 수 없습니다.")


def _bindings(store, db, bindings, *, expected=False):
    if len({item.source_subject for item in bindings}) != len(bindings):
        raise HTTPException(422, "한 원본 대상은 하나의 명시한 대상·회차에만 연결하세요.")
    for item in bindings:
        row = store.case(db, item.case_id, expected=item.expected_revision if expected else None)
        manifest = store.manifest(row)
        if not isinstance(manifest, ManifestV4) or not any(session.session_id == item.session_id for session in manifest.sessions):
            raise HTTPException(422, "대응표의 S1 대상·촬영 회차가 없습니다.")


def _classify(selection, cell, binding, inventory):
    reasons = ["reference_only_not_current_app_score"]
    status = selection.confirmation
    if binding is None:
        reasons.append("unmatched_subject")
    elif binding.participation != "active":
        reasons.append("participant_"+binding.participation)
    if selection.evaluator_status != "identified":
        reasons.append("evaluator_unknown")
    if selection.exposure != "independent_claimed":
        reasons.append("exposure_"+selection.exposure)
    if selection.source_edition != "20261002-s1.1":
        reasons.append("source_edition_not_current_s1")
    if selection.code not in ITEM_CODES and selection.code != "개59":
        status = "legacy_semantics"
        reasons.append("discarded_or_unknown_item")
    if inventory and selection.code in RECHECK:
        status = "recheck_required"
        reasons.append("source_requires_new_observation")
    text = cell.value if isinstance(cell.value, str) else ""
    if any(token in text.lower() for token in ("예시", "예제", "sample", "example")):
        status = "example"
        reasons.append("example_not_observation")
    if cell.formula is not None:
        reasons.append("stored_formula_cache_not_recalculated")
    elif cell.value is None:
        reasons.append("source_value_missing")
    if selection.confirmation != "human_confirmed":
        reasons.append("confirmation_"+selection.confirmation)
    return ReferenceRowV4(selection=selection, source=cell, effective_status=status, exclusion_reasons=tuple(reasons))


def preview(store, data: bytes, value: ValidationImportV4, user):
    value = ValidationImportV4.model_validate_json(value.model_dump_json())
    if PurePath(value.filename).name != value.filename or any(char in value.filename for char in ("/", "\\", ":")) or not value.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "XLSX 파일 이름만 지정하세요.")
    digest = hashlib.sha256(data).hexdigest()
    if digest != value.expected_sha256:
        raise HTTPException(409, "참고 원본의 SHA-256이 요청과 다릅니다.")
    with store.connect() as db:
        _account(db, user)
        _source_allowed(db,digest)
        _bindings(store, db, value.bindings, expected=True)
    try:
        workbook = s1_workbook.reference_cells(data, include_sheets=True)
        cells = tuple(ReferenceCellV4.model_validate_json(encode(cell)) for cell in workbook["cells"])
    except (ValueError, OverflowError) as exc:
        raise HTTPException(422, "참고 XLSX 셀을 읽을 수 없습니다.") from exc
    lookup = {(cell.sheet, cell.cell): cell for cell in cells}
    if len({(item.source_subject, item.sheet, item.cell) for item in value.selections}) != len(value.selections):
        raise HTTPException(422, "같은 원본 대상·셀을 중복 선택할 수 없습니다.")
    bindings = {item.source_subject: item for item in value.bindings}
    rows = []
    for selection in value.selections:
        cell = lookup.get((selection.sheet, selection.cell))
        if cell is None:
            if selection.sheet not in workbook["sheets"]:
                raise HTTPException(422, "선택한 원본 시트가 없습니다.")
            cell = ReferenceCellV4(sheet=selection.sheet, cell=selection.cell, raw_type="n", raw_xml_value=None,
                value=None, formula=None, formula_attributes={}, cached_value=None, cache_present=False)
        rows.append(_classify(selection, cell, bindings.get(selection.source_subject), INVENTORY.get(digest)))
    return {"profile": s1_workbook.profile(), "source_sha256": digest, "source_inventory_id": INVENTORY.get(digest),
        "cells": [cell.model_dump(mode="json") for cell in cells], "rows": [row.model_dump(mode="json") for row in rows],
        "bindings": [binding.model_dump(mode="json") for binding in value.bindings]}


def _record(db, validation_id):
    row = db.execute("SELECT detail_json FROM changes WHERE target=? AND action=? ORDER BY rowid DESC LIMIT 1", (validation_id, ACTION)).fetchone()
    if row is None:
        raise HTTPException(404, "검수 참고 기록이 없습니다.")
    return json.loads(row[0])


def document(store, pointer):
    pointer = ValidationReferenceV4.model_validate(pointer)
    if not pointer.ref.startswith("validation-data/"):
        raise HTTPException(409, "검수 참고 기록 경로가 다릅니다.")
    value = ValidationDocumentV4.model_validate_json(_read_file(store, pointer))
    if value.validation_id != pointer.validation_id:
        raise HTTPException(409, "검수 참고 기록의 식별자가 다릅니다.")
    _read_file(store, value.source)
    return value


def _readable(store, db, doc, user):
    _account(db, user)
    if doc.actor != user.username:
        raise HTTPException(403, "본인이 등록한 참고 원본만 열 수 있습니다.")
    _source_allowed(db,doc.source.hash)
    _bindings(store, db, doc.bindings)


def register(store, data: bytes, value: ValidationImportV4, user):
    value = ValidationImportV4.model_validate_json(value.model_dump_json())
    if hashlib.sha256(data).hexdigest() != value.expected_sha256:
        raise HTTPException(409, "참고 원본의 SHA-256이 요청과 다릅니다.")
    request_hash = analysis.digest(value.model_dump(mode="json"))
    with store.connect() as db:
        _account(db, user)
        for row in db.execute("SELECT detail_json FROM changes WHERE actor=? AND action=?", (user.username, ACTION)):
            record = json.loads(row[0])
            if record["request_id"] == value.request_id:
                if record["request_hash"] != request_hash:
                    raise HTTPException(409, "같은 요청 ID에 다른 검수 참고 입력을 사용할 수 없습니다.")
                return view(store, record["validation_id"], user)
    inspected = preview(store, data, value, user)
    validation_id = uid()
    prefix = f"validation-data/{validation_id}"
    source = _write_bytes(store, prefix+"/source.xlsx", data)
    doc = ValidationDocumentV4.model_validate_json(encode({"validation_id": validation_id, "request_id": value.request_id,
        "request_hash": request_hash, "actor": user.username, "recorded_at": now(), "filename": value.filename,
        "source": source.model_dump(mode="json"), "source_inventory_id": inspected["source_inventory_id"],
        "bindings": inspected["bindings"], "cells": inspected["cells"], "rows": inspected["rows"]}))
    file = _write_bytes(store, prefix+"/reference.json", doc.model_dump_json().encode())
    pointer = ValidationReferenceV4(validation_id=validation_id, ref=file.ref, hash=file.hash)
    stamps = {}
    _read_file(store, source, stamps); _read_file(store, pointer, stamps)
    with store.connect(write=True) as db:
        _readable(store, db, doc, user)
        _bindings(store, db, doc.bindings, expected=True)
        for row in db.execute("SELECT detail_json FROM changes WHERE actor=? AND action=?", (user.username, ACTION)):
            record = json.loads(row[0])
            if record["request_id"] == value.request_id:
                if record["request_hash"] != request_hash:
                    raise HTTPException(409, "요청 ID의 검수 참고 입력이 동시에 변경되었습니다.")
                return view(store, record["validation_id"], user)
        check_stamps(store, stamps)
        if document(store, pointer) != doc:
            raise HTTPException(409, "새 검수 참고 파일이 채택 전에 변경되었습니다.")
        store.audit(db, user.username, validation_id, ACTION, {**pointer.model_dump(mode="json"), "request_id": value.request_id,
            "request_hash": request_hash, "source_sha256":source.hash,"case_ids": sorted({item.case_id for item in doc.bindings})})
    return view(store, validation_id, user)


def view(store, validation_id, user):
    with store.connect() as db:
        record = _record(db, validation_id)
        pointer = ValidationReferenceV4.model_validate_json(encode({key: record[key] for key in ("validation_id", "ref", "hash")}))
        doc = document(store, pointer)
        _readable(store, db, doc, user)
    return {"reference": pointer.model_dump(mode="json"), "filename": doc.filename, "actor": doc.actor,
        "source_inventory_id": doc.source_inventory_id, "row_count": len(doc.rows), "mapped_subject_count": len(doc.bindings),
        "reference_only": True, "score_import_enabled": False, "ground_truth_status": "pending_G03", "document": doc.model_dump(mode="json")}


def list_records(store, user):
    with store.connect() as db:
        _account(db, user)
        ids = [row[0] for row in db.execute("SELECT DISTINCT target FROM changes WHERE actor=? AND action=?", (user.username, ACTION))]
    result = []
    for record_id in ids:
        try:
            result.append({key: value for key, value in view(store, record_id, user).items() if key != "document"})
        except (HTTPException, ValueError, OSError) as exc:
            if isinstance(exc,HTTPException) and exc.status_code not in (403,404,409,422):
                raise
            result.append(ValidationBlockedV4(validation_id=record_id,
                reason="참고 원본 또는 현재 대상·삭제·접근 조건을 확인할 수 없어 제공을 보류합니다.").model_dump())
    with store.connect() as db:
        _account(db,user)
    return result


def candidates(store,user):
    # Reference correspondence is separate from eligibility for scoring or cohorts.
    from .comparisons_v4 import CohortCandidateV4, CohortSessionCandidateV4
    from .domain.sheets_v4 import InputPointerV4
    with store.connect() as db:
        _account(db,user)
        result = []
        for row in db.execute("SELECT * FROM cases WHERE deletion_requested=0 ORDER BY event_id,participant_id"):
            manifest = store.manifest(row)
            if not isinstance(manifest,ManifestV4):continue
            result.append(CohortCandidateV4(case_id=row["case_id"],event_id=row["event_id"],participant_id=row["participant_id"],
                dog_name=row["dog_name"],input_revision=row["input_revision"],
                input=InputPointerV4(manifest_ref=row["manifest_ref"],manifest_hash=row["manifest_hash"]),
                sessions=[CohortSessionCandidateV4(session_id=session.session_id,note=session.note,survey_version=session.survey_version)
                    for session in manifest.sessions]))
        return result


def purge_deleted(db):
    deleted = {row[0] for row in db.execute("SELECT case_id FROM cases WHERE deletion_requested=1")}
    hashes = deletion_sources(db)
    revoked = set()
    records = list(db.execute("SELECT actor,target,detail_json FROM changes WHERE action=?", (ACTION,)))
    for row in records:
        record = json.loads(row["detail_json"])
        if deleted.intersection(record.get("case_ids", [])) or record["source_sha256"] in hashes:
            revoked.add(row["target"])
            remember_deleted_sources(db,(record["source_sha256"],),row["actor"])
    for reference_id in revoked:
        db.execute("DELETE FROM changes WHERE target=? AND action=?", (reference_id, ACTION))
    return revoked
