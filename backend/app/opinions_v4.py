"""Accountable S1 event opinions; free text never infers a type."""
import hashlib
import json
import os
from typing import Annotated

from fastapi import HTTPException
from pydantic import Field, field_validator

from . import judgements_v4 as judgements, sheets_v4 as sheets
from .domain.contracts_v4 import DecisionV4
from .domain.final_results_v4 import DomainOpinionV4, OpinionDocumentV4, OpinionReferenceV4
from .domain.results_v4 import ResultReferenceV4
from .input_models import Model
from .storage import encode, now, uid


class OpinionWriteV4(Model):
    expected_revision: Annotated[int, Field(ge=0)]
    basic: ResultReferenceV4
    viewer_sheet_id: str | None = None
    evaluator: Annotated[str, Field(max_length=200)] = ""
    completion_requested: bool = False
    domains: tuple[DomainOpinionV4, ...] = ()
    priority_help: Annotated[str, Field(max_length=12000)] = ""
    reason: Annotated[str, Field(min_length=1, max_length=4000)]

    @field_validator("basic", "domains", mode="before")
    @classmethod
    def contracts(cls, value, info):
        if info.field_name == "basic":
            return ResultReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value
        return tuple(DomainOpinionV4.model_validate_json(encode(item)) if isinstance(item, dict) else item for item in value)


class OpinionActionV4(Model):
    expected_revision: Annotated[int, Field(ge=1)]
    viewer_sheet_id: str | None = None
    reason: Annotated[str, Field(min_length=1, max_length=4000)]


class OpinionViewV4(Model):
    reference: OpinionReferenceV4 | None
    document: OpinionDocumentV4 | None
    selection_issues: dict[str, str | None]

    @field_validator("reference", "document", mode="before")
    @classmethod
    def contracts(cls, value, info):
        model = OpinionReferenceV4 if info.field_name == "reference" else OpinionDocumentV4
        return model.model_validate_json(encode(value)) if isinstance(value, dict) else value


class OpinionMetadataV4(Model):
    reference: OpinionReferenceV4 | None
    actor: str | None
    state: str | None
    basic: ResultReferenceV4 | None
    requires_reveal: bool

    @field_validator("reference", "basic", mode="before")
    @classmethod
    def contracts(cls, value, info):
        model = OpinionReferenceV4 if info.field_name == "reference" else ResultReferenceV4
        return model.model_validate_json(encode(value)) if isinstance(value, dict) else value


def context(store, db, case_id, session_id, user):
    sheets.manager(user, db)
    case, manifest = sheets._case(store, db, case_id)
    if not any(session.session_id == session_id for session in manifest.sessions):
        raise HTTPException(404, "해당 S1 회차가 없습니다.")
    return case


def selected_basic(store, db, case_id, session_id, requested, user, viewer_sheet_id=None):
    """Explicit basic revision; neither manager role nor event UI bypasses disclosure."""
    context(store, db, case_id, session_id, user)
    row = db.execute("SELECT * FROM basic_results WHERE result_id=?", (requested.result_id,)).fetchone()
    if not row or (row["case_id"], row["session_id"]) != (case_id, session_id):
        raise HTTPException(404, "이 개체·회차의 기본 결과를 명시적으로 선택하세요.")
    source = sheets.row_for(store, db, row["sheet_id"])
    current = judgements.document_for(store, row)
    if requested not in [ResultReferenceV4.model_validate_json(encode(judgements.reference(row))), *current.previous]:
        raise HTTPException(409, "선택한 기본 결과 revision/ref/hash가 기록과 다릅니다.")
    basic = judgements.read_result(store, requested.ref, requested.hash)
    if not source["active"]:
        raise HTTPException(403, "기본 입력 배정이 취소되었습니다.")
    if source["assigned_username"] == user.username:
        sheets.owner(db, source, user)
    else:
        if not viewer_sheet_id:
            raise HTTPException(403, "타 평가 원본은 본인의 공개 확인 시트를 통해 선택하세요.")
        viewer = sheets.row_for(store, db, viewer_sheet_id)
        sheets.owner(db, viewer, user)
        doc = sheets.document_for(store, viewer)
        inherited, _ = sheets.related_exposure(store, db, viewer, doc)
        exposed = {link.ref: link.model_dump(mode="json") for link in doc.exposures}
        exposed.update(inherited)
        link = exposed.get(basic.input.ref)
        grant = db.execute("SELECT * FROM score_grants WHERE viewer_sheet_id=? AND ref=?", (viewer_sheet_id, basic.input.ref)).fetchone()
        if (doc.state != "submitted" or doc.source_hash != basic.input_document.source_hash or link != basic.input.model_dump(mode="json")
                or not grant or grant["hash"] != basic.input.hash or grant["target_sheet_id"] != basic.input.sheet_id):
            raise HTTPException(403, "선택한 원본 revision에 대한 실제 공개 이력과 현재 공개 배정이 필요합니다.")
    return row, basic


def basic_candidates(store, case_id, session_id, user, viewer_sheet_id=None):
    with store.connect() as db:
        context(store, db, case_id, session_id, user)
        result = []
        for row in db.execute("SELECT * FROM basic_results WHERE case_id=? AND session_id=? ORDER BY rowid", (case_id, session_id)):
            current = judgements.document_for(store, row)
            links = [ResultReferenceV4.model_validate_json(encode(judgements.reference(row))), *current.previous]
            for link in links:
                try:
                    _, doc = selected_basic(store, db, case_id, session_id, link, user, viewer_sheet_id)
                except HTTPException as exc:
                    if exc.status_code == 403:
                        continue
                    raise
                shown = {"result_id": link.result_id, "revision": link.revision, "manifest_ref": link.ref, "manifest_hash": link.hash}
                result.append(judgements.summary(shown, doc))
        return result


def basic_candidate(store, case_id, session_id, result_id, revision, user, viewer_sheet_id=None):
    with store.connect() as db:
        context(store, db, case_id, session_id, user)
        row = db.execute("SELECT * FROM basic_results WHERE result_id=? AND case_id=? AND session_id=?", (result_id, case_id, session_id)).fetchone()
        if row is None:
            raise HTTPException(404, "이 회차의 기본 결과가 아닙니다.")
        current = judgements.document_for(store, row)
        links = [ResultReferenceV4.model_validate_json(encode(judgements.reference(row))), *current.previous]
        link = next((entry for entry in links if entry.revision == revision), None)
        if link is None:
            raise HTTPException(404, "보존한 기본 결과 판본이 아닙니다.")
        _, doc = selected_basic(store, db, case_id, session_id, link, user, viewer_sheet_id)
        source = sheets.row_for(store, db, row["sheet_id"])
        case = store.case(db, case_id)
        shown = {"result_id": link.result_id, "revision": link.revision, "manifest_ref": link.ref, "manifest_hash": link.hash}
        return {"summary": judgements.summary(shown, doc), "document": doc.model_dump(mode="json"),
                "sheet_changed": doc.input.revision != source["revision"],
                "source_changed": doc.input_document.source.input_revision != case["input_revision"]}


def latest(store, db, case_id, session_id):
    for row in db.execute("SELECT detail_json FROM changes WHERE target=? AND action='opinion.s1.save' ORDER BY rowid DESC", (case_id,)):
        value = json.loads(row["detail_json"])
        if value.get("session_id") == session_id:
            return OpinionReferenceV4.model_validate_json(encode({key: value[key] for key in ("opinion_id", "revision", "ref", "hash")}))
    return None


def selection(item, basic, evaluator):
    if item.label is None:
        return None, "명시 유형 선택 없음"
    if not evaluator.strip() or not item.reason.strip():
        return None, "유효 선택에는 평가자와 근거가 필요합니다."
    observations = {value.code: value for value in sheets.analysis_input(basic.input_document).observations}
    try:
        decision = DecisionV4.model_validate_json(encode({"key": "attachment_type" if item.domain == "attachment" else "owner_type",
            "label": item.label, "status": "complete", "evidence_codes": item.evidence_codes, "counter_codes": item.counter_codes,
            "evidence": [basis.model_dump(mode="json") for code in item.evidence_codes if code not in item.counter_codes for basis in observations[code].evidence],
            "counter_evidence": [basis.model_dump(mode="json") for code in item.counter_codes for basis in observations[code].evidence],
            "counter_note": item.counter_note, "reason": item.reason, "rater_id": basic.input_document.sheet.rater_id,
            "input_sheet_id": basic.input.sheet_id, "input_revision": basic.input.revision, "input_sha256": basic.input.hash,
            "rule_version": basic.rule_version}))
        judgements.validate_judgement(decision, basic)
        return decision, None
    except (ValueError, KeyError) as exc:
        return None, str(exc)


def completion(evaluator, requested, domains, basic):
    issues = []
    if not requested:
        issues.append("B40 완료 요청 없음")
    if not evaluator.strip():
        issues.append("C31 평가자 없음")
    if not any(item.text.strip() for item in domains):
        issues.append("D33~D38 실질 영역 의견 없음; D39 도움·유형 선택만으로 완료되지 않음. 입장 선택 대안은 G01 원양식 확인 대기")
    return tuple(issues)


def validate_domains(domains, basic):
    observations = {item.code: item for item in sheets.analysis_input(basic.input_document).observations}
    for domain in domains:
        allowed = set()
        for code in domain.evidence_codes:
            item = observations.get(code)
            if item is None or item.status != "observed" or item.validity not in ("valid", "caution") or not any(
                    basis.observed_seconds > 0 and basis.end_seconds > basis.start_seconds for basis in item.evidence):
                raise ValueError("의견에 명시한 근거 코드는 고정 기본 입력의 실제 유효 관찰이어야 합니다.")
            allowed.update(encode(basis.model_dump(mode="json")) for basis in item.evidence)
        if any(encode(basis.model_dump(mode="json")) not in allowed for basis in domain.scene_refs):
            raise ValueError("의견 지정 장면은 선택한 원항목의 고정 영상·hash·카메라·시각과 정확히 같아야 합니다.")


def read_document(store, ref, digest):
    try:
        if not ref.startswith("opinions/"):
            raise ValueError("opinion path")
        payload = store.path(ref).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("opinion hash")
        doc = OpinionDocumentV4.model_validate_json(payload)
        basic = judgements.read_result(store, doc.basic.ref, doc.basic.hash)
        if (basic.case_id, basic.session_id) != (doc.case_id, doc.session_id):
            raise ValueError("opinion basic identity")
        validate_domains(doc.domains, basic)
        issues = completion(doc.evaluator, doc.completion_requested, doc.domains, basic)
        if doc.completion_issues != issues or (doc.state != "withdrawn" and (doc.state == "complete") != (not issues)):
            raise ValueError("opinion completion gate")
        return doc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "S1 의견 또는 고정 기본 결과가 손상되었습니다.") from exc


def write_document(store, data):
    doc = OpinionDocumentV4.model_validate_json(encode(data))
    payload = doc.model_dump_json().encode()
    ref = f"opinions/{doc.case_id}/{doc.opinion_id}/r{doc.revision}-{uid()}.json"
    path = store.path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return OpinionReferenceV4(opinion_id=doc.opinion_id, revision=doc.revision, ref=ref, hash=hashlib.sha256(payload).hexdigest())


def view(store, case_id, session_id, user, viewer_sheet_id=None):
    from . import disclosures_v4 as disclosures
    with store.connect() as db:
        context(store, db, case_id, session_id, user)
        link = latest(store, db, case_id, session_id)
        if link is None:
            return {"reference": None, "document": None, "selection_issues": {}}
        doc = read_document(store, link.ref, link.hash)
        _, basic = selected_basic(store, db, case_id, session_id, doc.basic, user, viewer_sheet_id)
        disclosures.require(db, case_id, session_id, user, disclosures.target("opinion", link), doc.actor)
    return {"reference": link.model_dump(mode="json"), "document": doc.model_dump(mode="json"),
            "selection_issues": {item.domain: selection(item, basic, doc.evaluator)[1] for item in doc.domains if item.label is not None}}


def metadata(store, case_id, session_id, user):
    from . import disclosures_v4 as disclosures
    with store.connect() as db:
        context(store, db, case_id, session_id, user)
        link = latest(store, db, case_id, session_id)
        if link is None:
            return {"reference": None, "actor": None, "state": None, "basic": None, "requires_reveal": False}
        doc = read_document(store, link.ref, link.hash)
        return {"reference": link.model_dump(mode="json"), "actor": doc.actor, "state": doc.state,
            "basic": doc.basic.model_dump(mode="json"),
            "requires_reveal": not disclosures.allowed(db, case_id, session_id, user, disclosures.target("opinion", link), doc.actor)}


def save(store, case_id, session_id, value: OpinionWriteV4, user):
    from . import disclosures_v4 as disclosures
    value = OpinionWriteV4.model_validate_json(value.model_dump_json())
    with store.connect() as db:
        case = context(store, db, case_id, session_id, user)
        link = latest(store, db, case_id, session_id)
        if (link.revision if link else 0) != value.expected_revision:
            raise HTTPException(409, "다른 의견 수정이 저장되었습니다.")
        prior = read_document(store, link.ref, link.hash) if link else None
        if prior:
            disclosures.require(db, case_id, session_id, user, disclosures.target("opinion", link), prior.actor)
        if prior and prior.state != "draft":
            raise HTTPException(409, "완료·철회 의견은 먼저 재개방하세요.")
        basic_row, basic = selected_basic(store, db, case_id, session_id, value.basic, user, value.viewer_sheet_id)
    try:
        validate_domains(value.domains, basic)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    identities = sheets._source_identities(store, basic.input_document.source)
    issues = completion(value.evaluator, value.completion_requested, value.domains, basic)
    data = {"opinion_id": link.opinion_id if link else uid(), "case_id": case_id, "session_id": session_id,
        "revision": value.expected_revision+1, "actor": user.username, "recorded_at": now(), "change_reason": value.reason,
        "basic": value.basic.model_dump(mode="json"), "evaluator": value.evaluator, "completion_requested": value.completion_requested,
        "state": "draft" if issues else "complete", "completion_issues": issues,
        "domains": [item.model_dump(mode="json") for item in value.domains], "priority_help": value.priority_help,
        "previous": [*[item.model_dump(mode="json") for item in prior.previous], link.model_dump(mode="json")] if prior else []}
    adopted = write_document(store, data)
    with store.connect(write=True) as db:
        current = context(store, db, case_id, session_id, user)
        if current["input_revision"] != case["input_revision"] or latest(store, db, case_id, session_id) != link:
            raise HTTPException(409, "저장 중 입력 또는 의견이 변경되었습니다.")
        new_row, new_basic = selected_basic(store, db, case_id, session_id, value.basic, user, value.viewer_sheet_id)
        if tuple(new_row) != tuple(basic_row) or new_basic != basic:
            raise HTTPException(409, "저장 중 기본 결과가 변경되었습니다.")
        sheets._unchanged_sources(store, basic.input_document.source, identities)
        if link:
            read_document(store, link.ref, link.hash)
        written = read_document(store, adopted.ref, adopted.hash)
        if written != OpinionDocumentV4.model_validate_json(encode(data)) or (written.opinion_id, written.revision) != (adopted.opinion_id, adopted.revision):
            raise HTTPException(409, "새 의견 파일이 저장한 내용과 다릅니다.")
        store.audit(db, user.username, case_id, "opinion.s1.save", {**adopted.model_dump(mode="json"), "session_id": session_id})
    return view(store, case_id, session_id, user, value.viewer_sheet_id)


def action(store, case_id, session_id, value: OpinionActionV4, user, action):
    from . import disclosures_v4 as disclosures
    if action not in ("reopen", "withdraw"):
        raise HTTPException(422, "지원하지 않는 의견 작업입니다.")
    with store.connect() as db:
        case = context(store, db, case_id, session_id, user)
        link = latest(store, db, case_id, session_id)
        if link is None or link.revision != value.expected_revision:
            raise HTTPException(409, "최신 의견 revision을 지정하세요.")
        doc = read_document(store, link.ref, link.hash)
        selected_basic(store, db, case_id, session_id, doc.basic, user, value.viewer_sheet_id)
        disclosures.require(db, case_id, session_id, user, disclosures.target("opinion", link), doc.actor)
        if action == "reopen" and doc.state == "draft" or action == "withdraw" and doc.state == "withdrawn":
            raise HTTPException(409, "이미 요청한 의견 상태입니다.")
    data = doc.model_dump(mode="json")
    data.update(revision=doc.revision+1, actor=user.username, recorded_at=now(), change_reason=value.reason,
        previous=[*data["previous"], link.model_dump(mode="json")], state="draft" if action == "reopen" else "withdrawn")
    if action == "reopen":
        data["completion_requested"] = False
        data["completion_issues"] = list(completion(doc.evaluator, False, doc.domains, judgements.read_result(store, doc.basic.ref, doc.basic.hash)))
    adopted = write_document(store, data)
    with store.connect(write=True) as db:
        current = context(store, db, case_id, session_id, user)
        if current["input_revision"] != case["input_revision"] or latest(store, db, case_id, session_id) != link:
            raise HTTPException(409, "의견 상태 변경 중 입력 또는 의견이 변경되었습니다.")
        selected_basic(store, db, case_id, session_id, doc.basic, user, value.viewer_sheet_id)
        read_document(store, link.ref, link.hash)
        written = read_document(store, adopted.ref, adopted.hash)
        if written != OpinionDocumentV4.model_validate_json(encode(data)) or (written.opinion_id, written.revision) != (adopted.opinion_id, adopted.revision):
            raise HTTPException(409, "새 의견 상태 파일이 저장한 내용과 다릅니다.")
        store.audit(db, user.username, case_id, "opinion.s1.save", {**adopted.model_dump(mode="json"), "session_id": session_id, "action": action})
    return view(store, case_id, session_id, user, value.viewer_sheet_id)
