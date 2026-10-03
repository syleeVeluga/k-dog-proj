"""Explicit interpretation reveal, immutable viewer revisions and exposure inheritance."""
import json
from typing import Annotated
from fastapi import HTTPException
from pydantic import Field, field_validator

from .domain.disclosures_v4 import InterpretationExposureV4, InterpretationReferenceV4
from .domain.sheets_v4 import SheetDocumentV4
from .domain.media_v4 import MediaKey
from .input_models import Model
from .sheets_v4 import SheetSummaryV4
from .storage import encode, now, uid

ACTION = "interpretation.s1.reveal"


class InterpretationRevealV4(Model):
    target: InterpretationReferenceV4
    viewer_sheet_id: MediaKey
    expected_viewer_revision: Annotated[int, Field(ge=1)]
    reason: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]

    @field_validator("target", mode="before")
    @classmethod
    def contract(cls, value):
        return InterpretationReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


class InterpretationRevealResultV4(Model):
    viewer: SheetSummaryV4
    exposure: InterpretationExposureV4

    @field_validator("exposure", mode="before")
    @classmethod
    def contract(cls, value):
        return InterpretationExposureV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


def records(db, case_id, session_id):
    for row in db.execute("SELECT detail_json FROM changes WHERE target=? AND action=? ORDER BY rowid", (case_id, ACTION)):
        raw = json.loads(row["detail_json"])
        value = InterpretationExposureV4.model_validate_json(encode(raw["exposure"]))
        if value.case_id == case_id and value.session_id == session_id:
            yield value


def inherited(db, case_id, session_id, username, rater_id, source):
    hashes = {video.sha256 for video in source.session.videos}
    return {entry.exposure_id: entry for entry in records(db, case_id, session_id)
            if (entry.viewer_username == username or entry.viewer_rater_id == rater_id) and hashes.intersection(entry.video_hashes)}


def target(kind, link):
    data = link.model_dump(mode="json") if hasattr(link, "model_dump") else link
    return InterpretationReferenceV4(kind=kind, document_id=data["opinion_id" if kind == "opinion" else "final_id"],
        revision=data.get("revision") if kind == "opinion" else None, ref=data["ref"], hash=data["hash"])


def allowed(db, case_id, session_id, user, pointer, source_actor):
    return source_actor == user.username or any(entry.viewer_username == user.username and entry.target == pointer
        for entry in records(db, case_id, session_id))


def require(db, case_id, session_id, user, pointer, source_actor):
    if not allowed(db, case_id, session_id, user, pointer, source_actor):
        raise HTTPException(403, "다른 평가자의 의견·최종 해석은 원자료 제출 후 명시 공개하세요. 해석 노출은 독립성 이력에 보존됩니다.")


def resolve(store, db, case_id, session_id, pointer):
    from . import opinions_v4 as opinions, final_results_v4 as finals
    action = "opinion.s1.save" if pointer.kind == "opinion" else "final.s1.publish"
    for row in db.execute("SELECT detail_json FROM changes WHERE target=? AND action=?", (case_id, action)):
        value = json.loads(row["detail_json"])
        if value.get("session_id") != session_id or target(pointer.kind, value) != pointer:
            continue
        doc = (opinions if pointer.kind == "opinion" else finals).read_document(store, pointer.ref, pointer.hash)
        if (doc.case_id, doc.session_id) != (case_id, session_id):
            raise HTTPException(409, "해석 문서의 대상·회차가 다릅니다.")
        return doc
    raise HTTPException(404, "기록된 정확한 해석 판본을 선택하세요.")


def reveal(store, case_id, session_id, value: InterpretationRevealV4, user):
    from . import opinions_v4 as opinions, sheets_v4 as sheets
    value = InterpretationRevealV4.model_validate_json(value.model_dump_json())
    with store.connect() as db:
        case = opinions.context(store, db, case_id, session_id, user)
        source = resolve(store, db, case_id, session_id, value.target)
        basic_row, basic = opinions.selected_basic(store, db, case_id, session_id, source.basic, user, value.viewer_sheet_id)
        viewer = sheets.row_for(store, db, value.viewer_sheet_id, expected=value.expected_viewer_revision)
        sheets.owner(db, viewer, user)
        doc = sheets.document_for(store, viewer)
        if (viewer["case_id"], viewer["session_id"], doc.source_hash) != (case_id, session_id, basic.input_document.source_hash) or doc.state != "submitted":
            raise HTTPException(409, "같은 고정 입력의 본인 원자료를 먼저 제출하세요.")
        if doc.sheet.rater_kind != "human":
            raise HTTPException(403, "해석 공개는 사람의 제출 원본에 기록합니다.")
        previous_exposure = inherited(db, case_id, session_id, user.username, doc.sheet.rater_id, doc.source)
    exposure = InterpretationExposureV4(exposure_id=uid(), target=value.target, case_id=case_id, session_id=session_id,
        source_actor=source.actor, viewer_username=user.username, viewer_rater_id=doc.sheet.rater_id,
        basic_result_id=source.basic.result_id, basic_revision=source.basic.revision, basic_ref=source.basic.ref, basic_hash=source.basic.hash,
        video_hashes=tuple(sorted({video.sha256 for video in doc.source.session.videos})), recorded_at=now(), reason=value.reason)
    data = doc.model_dump(mode="json")
    merged = {entry.exposure_id: entry for entry in doc.interpretation_exposures}
    merged.update(previous_exposure); merged[exposure.exposure_id] = exposure
    data.update(revision=doc.revision+1, actor=user.username, recorded_at=exposure.recorded_at, change_reason=value.reason,
        previous=[*data["previous"], sheets.reference(viewer)],
        interpretation_exposures=[entry.model_dump(mode="json") for entry in merged.values()],
        purpose="review" if doc.purpose == "independent" else doc.purpose,
        initial_submission=data["initial_submission"] or sheets.reference(viewer))
    identities = sheets._source_identities(store, doc.source)
    ref, digest = sheets.write_document(store, data)
    with store.connect(write=True) as db:
        current_case = opinions.context(store, db, case_id, session_id, user)
        current = sheets.row_for(store, db, value.viewer_sheet_id, expected=value.expected_viewer_revision)
        sheets.owner(db, current, user)
        if current_case["input_revision"] != case["input_revision"] or tuple(current) != tuple(viewer):
            raise HTTPException(409, "공개 중 입력 또는 본인 채점이 변경되었습니다.")
        new_row, new_basic = opinions.selected_basic(store, db, case_id, session_id, source.basic, user, value.viewer_sheet_id)
        if tuple(new_row) != tuple(basic_row) or new_basic != basic or resolve(store, db, case_id, session_id, value.target) != source:
            raise HTTPException(409, "공개 중 해석 또는 고정 기본 결과가 변경되었습니다.")
        if inherited(db, case_id, session_id, user.username, doc.sheet.rater_id, doc.source) != previous_exposure:
            raise HTTPException(409, "다른 해석 공개가 먼저 저장되었습니다. 다시 조회하세요.")
        sheets._unchanged_sources(store, doc.source, identities)
        if sheets.read_document(store, ref, digest) != SheetDocumentV4.model_validate_json(encode(data)):
            raise HTTPException(409, "공개 후 본인 revision이 검사한 내용과 다릅니다.")
        db.execute("UPDATE score_sheets SET purpose=?,revision=?,manifest_ref=?,manifest_hash=? WHERE sheet_id=?",
            (data["purpose"], data["revision"], ref, digest, value.viewer_sheet_id))
        store.audit(db, user.username, case_id, ACTION, {"exposure": exposure.model_dump(mode="json"),
            "viewer": {"sheet_id": value.viewer_sheet_id, "revision": data["revision"], "ref": ref, "hash": digest}})
        summary = sheets.summary(sheets.row_for(store, db, value.viewer_sheet_id), user)
    return {"viewer": summary, "exposure": exposure.model_dump(mode="json")}
