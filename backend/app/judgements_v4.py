"""S1 immutable calculation revisions and accountable manual basic judgements."""

import hashlib
import json
import os
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from . import sheets_v4 as sheets
from .domain.catalog_v4 import VOCAL_CODES, load_mapping_v4
from .domain.contracts_v4 import DecisionV4
from .domain.results_v4 import BasicResultV4, CalculationConditionsV4
from .domain.sheets_v4 import SheetReferenceV4
from .input_models import Model, Revision
from .media import MediaError, probe
from .recording_v4 import observation_clear_v4, validate_recording_media_v4
from .scoring_v4 import (ATTACHMENT_TYPES, OWNER_TYPES, RULE_HASH, RULE_VERSION, VOCAL_WINDOWS,
                         calculate, verify_rules)
from .storage import encode, now, uid


class CalculateV4(Model):
    input: SheetReferenceV4
    same_object: bool | None = None
    same_object_reason: sheets.Reason | None = None

    @field_validator("input", mode="before")
    @classmethod
    def contract(cls, value):
        return SheetReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


class DecisionEditV4(Model):
    key: Literal["attachment_type", "owner_type"]
    label: str | None
    status: Literal["draft", "complete", "held"]
    evidence_codes: Annotated[list[str], Field(max_length=90)]
    counter_codes: Annotated[list[str], Field(max_length=90)] = []
    counter_note: sheets.Reason | None = None
    reason: sheets.Reason


class JudgementEditV4(Revision):
    reason: sheets.Reason
    decisions: Annotated[list[DecisionEditV4], Field(min_length=1, max_length=2)]


class ResultSummaryV4(Model):
    result_id: str
    revision: int
    manifest_ref: str
    manifest_hash: str
    input: SheetReferenceV4

    @field_validator("input", mode="before")
    @classmethod
    def contract(cls, value):
        return CalculateV4.contract(value)


class ResultViewV4(Model):
    summary: ResultSummaryV4
    document: BasicResultV4
    sheet_changed: bool
    source_changed: bool

    @field_validator("document", mode="before")
    @classmethod
    def contract(cls, value):
        return BasicResultV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


def result_row(store, db, result_id, user, expected=None):
    row = db.execute("SELECT * FROM basic_results WHERE result_id=?", (result_id,)).fetchone()
    if not row:
        raise HTTPException(404, "S1 기본 결과를 찾을 수 없습니다.")
    source = sheets.row_for(store, db, row["sheet_id"])
    sheets.owner(db, source, user)
    if expected is not None and row["revision"] != expected:
        raise HTTPException(409, "다른 판정 수정이 저장되었습니다. 최신 결과를 조회하세요.")
    return row, source


def read_result(store, ref, digest):
    try:
        if not ref.startswith("results/"):
            raise ValueError("result reference")
        payload = store.path(ref).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("result hash")
        doc = BasicResultV4.model_validate_json(payload)
        if sheets.read_document(store, doc.input.ref, doc.input.hash) != doc.input_document:
            raise ValueError("pinned input")
        # Old immutable results retain their rule snapshot, without implicitly re-scoring.
        from .domain.catalog_v4 import validate_source_references_v4
        validate_source_references_v4(doc.rule_snapshot)
        if doc.rule_snapshot.get("version") != doc.rule_version:
            raise ValueError("rule snapshot version")
        return doc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "S1 기본 결과 또는 고정 원자료 파일이 손상되었습니다.") from exc


def document_for(store, row):
    doc = read_result(store, row["manifest_ref"], row["manifest_hash"])
    if (doc.result_id, doc.input.sheet_id, doc.case_id, doc.session_id, doc.revision) != tuple(row[key] for key in ("result_id", "sheet_id", "case_id", "session_id", "revision")):
        raise HTTPException(409, "기본 결과 DB와 고정 문서가 다릅니다.")
    return doc


def reference(row):
    return {"result_id": row["result_id"], "revision": row["revision"], "ref": row["manifest_ref"], "hash": row["manifest_hash"]}


def summary(row, doc):
    return {**{key: row[key] for key in ("result_id", "revision", "manifest_ref", "manifest_hash")}, "input": doc.input.model_dump(mode="json")}


def list_results(store, sheet_id, user):
    with store.connect() as db:
        sheets.owner(db, sheets.row_for(store, db, sheet_id), user)
        return [summary(row, document_for(store, row)) for row in db.execute("SELECT * FROM basic_results WHERE sheet_id=? ORDER BY rowid", (sheet_id,))]


def view(store, result_id, user, revision=None):
    with store.connect() as db:
        row, source = result_row(store, db, result_id, user)
        doc = document_for(store, row)
        shown = row
        if revision is not None and revision != doc.revision:
            old = next((item for item in doc.previous if item.revision == revision), None)
            if old is None:
                raise HTTPException(404, "보존한 기본 결과 revision이 아닙니다.")
            doc = read_result(store, old.ref, old.hash)
            if doc.result_id != result_id or doc.revision != revision:
                raise HTTPException(409, "결과 이력 연결이 다릅니다.")
            shown = {"result_id": result_id, "revision": revision, "manifest_ref": old.ref, "manifest_hash": old.hash}
        case = store.case(db, row["case_id"])
        return {"summary": summary(shown, doc), "document": doc.model_dump(mode="json"),
                "sheet_changed": doc.input.revision != source["revision"], "source_changed": doc.input_document.source.input_revision != case["input_revision"]}


def pinned_sheet(store, row, requested):
    current = sheets.document_for(store, row)
    links = [sheets.reference(row), *[item.model_dump(mode="json") for item in current.previous]]
    if requested not in [SheetReferenceV4.model_validate_json(encode(link)) for link in links]:
        raise HTTPException(409, "이 시트의 명시한 revision/ref/hash를 선택하세요.")
    doc = sheets.read_document(store, requested.ref, requested.hash)
    if doc.state != "submitted":
        raise HTTPException(409, "제출한 시트 revision으로 계산하세요.")
    return doc


def evaluation_context(store, db, row):
    doc = sheets.document_for(store, row)
    inherited, ai_exposed = sheets.related_exposure(store, db, row, doc)
    links = {link.ref: link.model_dump(mode="json") for link in doc.exposures}
    links.update(inherited)
    exposed = doc.sheet.ai_exposed or ai_exposed
    return {"purpose": "review" if (links or exposed) and doc.purpose == "independent" else doc.purpose,
            "ai_exposed": exposed, "exposures": sorted(links.values(), key=lambda link: link["ref"])}


def write_result(store, data):
    doc = BasicResultV4.model_validate_json(encode(data))
    payload = doc.model_dump_json().encode()
    ref = f"results/{doc.case_id}/{doc.result_id}/r{doc.revision}-{uid()}.json"
    path = store.path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return ref, hashlib.sha256(payload).hexdigest()


def audio_amounts(store, doc):
    """Only full actual-window audio coverage from observed evidence is available."""
    available, facts = {}, {}
    capture = doc.source.session.recording_s1
    videos = {video.video_id: video for video in doc.source.session.videos}
    windows = {window.window_id: window for window in doc.source.windows}
    for item in doc.sheet.observations:
        if item.code not in VOCAL_CODES or item.status != "observed" or item.vocalization is None:
            continue
        ranges = []
        for evidence in item.evidence:
            video = videos[evidence.video_id]
            if evidence.video_id not in facts:
                try:
                    info = probe(store.path(video.storage_ref))
                except (MediaError, OSError, ValueError) as exc:
                    raise HTTPException(422, "원본 음성 범위를 확인할 수 없습니다.") from exc
                facts[video.video_id] = {"video_sha256": video.sha256, "duration_sec": info["duration_sec"],
                    "audio_ranges": [[part["start_sec"], part["end_sec"]] for part in info.get("audio_ranges", [])], "audio_status": info["audio_status"]}
            info = facts[video.video_id]
            clear = observation_clear_v4(capture, video.video_id, evidence.start_seconds, evidence.end_seconds, modality="audio", code=item.code)
            if (not clear or info["audio_status"] != "present" or evidence.observed_seconds != evidence.end_seconds-evidence.start_seconds
                    or not sheets._covered(info["audio_ranges"], evidence.start_seconds, evidence.end_seconds)):
                continue
            offset = capture.offset(video.video_id)
            if offset is not None:
                ranges.append((evidence.start_seconds-offset, evidence.end_seconds-offset))
        window = windows[VOCAL_WINDOWS[item.code]]
        spans = [part for part in window.source_intervals if part.evidence_id is None]
        available[item.code] = bool(spans) and all(sheets._covered(ranges, part.start_seconds, part.end_seconds) for part in spans)
    return available, facts


def initial_decisions(doc, ref, calculations):
    result = []
    for key, label, reason in (("owner_type", calculations.owner.label, calculations.owner.reason),
                              ("attachment_type", None, "네 애착 유형의 고정 수치 분기식 없음; 근거·반대 근거를 검토하여 선택. D04 상세 AI 반환 보류")):
        result.append({"key": key, "label": label, "status": "draft" if label else "held", "evidence_codes": [], "evidence": [],
                       "reason": reason, "rater_id": doc.sheet.rater_id, "input_sheet_id": ref.sheet_id, "input_revision": ref.revision,
                       "input_sha256": ref.hash, "rule_version": RULE_VERSION})
    return result


def create(store, sheet_id, value, user):
    rules = verify_rules()
    try:
        conditions = CalculationConditionsV4(same_object=value.same_object, same_object_reason=value.same_object_reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with store.connect() as db:
        row = sheets.row_for(store, db, sheet_id)
        sheets.owner(db, row, user)
        doc = pinned_sheet(store, row, value.input)
        context = evaluation_context(store, db, row)
    if doc.source.asset_hashes != sheets.asset_hashes():
        raise HTTPException(409, "고정 입력의 S1 자산 hash가 현재 계산 판본과 다릅니다.")
    identities = sheets._source_identities(store, doc.source)
    sheets.validate_observations(doc, doc.sheet.model_dump(mode="json"), complete=True)
    sheets._verify_preprocess(store, row["case_id"], row["session_id"], doc.source, user.username, historical=True)
    durations = validate_recording_media_v4(store, doc.source.session, doc.source.session.recording_s1)
    if any(evidence.end_seconds > durations[evidence.video_id] for item in doc.sheet.observations for evidence in item.evidence):
        raise HTTPException(422, "관찰 근거가 고정 영상의 실제 길이 밖입니다.")
    audio, facts = audio_amounts(store, doc)
    calculated = calculate(doc, rules=rules, audio_available=audio, conditions=conditions)
    decisions = initial_decisions(doc, value.input, calculated)
    result_id = uid()
    data = {"result_id": result_id, "case_id": row["case_id"], "session_id": row["session_id"], "revision": 1, "actor": user.username,
            "recorded_at": now(), "change_reason": "제출한 S1 고정 시트로 기본 계산", "input": value.input.model_dump(mode="json"),
            "input_document": doc.model_dump(mode="json"), "rule_version": RULE_VERSION, "rule_hash": RULE_HASH, "rule_snapshot": rules,
            "conditions": conditions.model_dump(mode="json"), "audio_sources": facts, "evaluation_context": context,
            "calculations": calculated.model_dump(mode="json"), "automatic_decisions": decisions, "decisions": decisions,
            "decision_sources": {item["key"]: "automatic" for item in decisions}}
    ref, digest = write_result(store, data)
    verify_rules()
    validate_recording_media_v4(store, doc.source.session, doc.source.session.recording_s1)
    with store.connect(write=True) as db:
        current = sheets.row_for(store, db, sheet_id)
        sheets.owner(db, current, user)
        pinned_sheet(store, current, value.input)
        if evaluation_context(store, db, current) != context:
            raise HTTPException(409, "계산 중 평가 노출 상태가 변경되었습니다.")
        sheets._unchanged_sources(store, doc.source, identities)
        db.execute("INSERT INTO basic_results VALUES (?,?,?,?,?,?,?)", (result_id, sheet_id, row["case_id"], row["session_id"], 1, ref, digest))
        store.audit(db, user.username, row["case_id"], "basic.calculate", {"result_id": result_id, "ref": ref, "hash": digest, "input": value.input.model_dump(mode="json")})
    return view(store, result_id, user)


def validate_judgement(decision, doc):
    if (decision.rater_id, decision.input_sheet_id, decision.input_revision, decision.input_sha256, decision.rule_version) != (doc.input_document.sheet.rater_id, doc.input.sheet_id, doc.input.revision, doc.input.hash, doc.rule_version):
        raise ValueError("판정 작성자·고정 입력·규칙 연결이 다릅니다.")
    observations = {item.code: item for item in sheets.analysis_input(doc.input_document).observations}
    selected = [observations.get(code) for code in decision.evidence_codes]
    if any(item is None or item.status != "observed" or item.validity not in ("valid", "caution") for item in selected):
        raise ValueError("판정 근거는 이 고정 시트의 유효 원관찰이어야 합니다.")
    allowed = {encode(evidence.model_dump(mode="json")) for item in selected for evidence in item.evidence}
    if any(encode(evidence.model_dump(mode="json")) not in allowed for evidence in (*decision.evidence, *decision.counter_evidence)):
        raise ValueError("판정 근거는 선택한 원관찰의 실제 시각·영상과 같아야 합니다.")
    if decision.status == "complete":
        if not decision.counter_evidence and not decision.counter_note:
            raise ValueError("반대 근거 또는 검토 후 없는 사유가 필요합니다.")
        valid_bases = [basis for basis in decision.evidence if basis.observed_seconds > 0 and basis.end_seconds > basis.start_seconds]
        if not valid_bases:
            raise ValueError("완료 판정에는 실제 확인량이 있는 근거가 필요합니다.")
        codes = {item.code for item in selected if item.code not in decision.counter_codes and any(basis in valid_bases for basis in item.evidence)}
        mapping = load_mapping_v4("results")
        relevant = set(mapping["entries"][0 if decision.key == "owner_type" else 1]["behavior_codes"])
        if not codes & relevant:
            raise ValueError("해당 영역의 원관찰 근거가 필요합니다.")
        if decision.key == "owner_type":
            eligible = {item.code: item for item in doc.calculations.owner.items if item.used}
            if not codes & eligible.keys():
                raise ValueError("교육태도 완료 판정은 실제 관찰 기회가 있는 배점 근거가 필요합니다.")
            primary = {item.code for item in doc.calculations.owner.items}
            if any(code in primary and code not in eligible for code in codes):
                raise ValueError("기회 미확인·직원 중단 뒤·합계 0 배점은 유형의 지지 근거가 아닙니다.")
        else:
            capture = doc.input_document.source.session.recording_s1
            if any(part.segment in ("alone", "reunion") and part.state == "not_performed" for part in capture.segments):
                raise ValueError("분리·재회 미실시는 관계 판정보류입니다.")
            if codes <= {"개21"}:
                raise ValueError("개21 미승인 집계 하나로 애착 유형을 확정하지 않습니다.")
        for item in selected:
            if item.code in decision.counter_codes or not any(basis in valid_bases for basis in item.evidence):
                continue
            guards = {"개22":"보12", "개23":"보12", "개48":"보12", **{f"개{n}":"보13" for n in range(38,44)}, "개30":"보14", "개34":"보14"}
            guard = observations.get(guards.get(item.code))
            if guard and guard.status == "observed" and guard.value == 3:
                raise ValueError("조건이 무효인 해당 항목은 완료 판정의 지지 근거에서 제외하세요.")
    return decision


def revise(store, result_id, value, user):
    with store.connect() as db:
        row, source = result_row(store, db, result_id, user, value.expected_revision)
        doc = document_for(store, row)
        context = evaluation_context(store, db, source)
    if doc.input_document.sheet.rater_kind != "human":
        raise HTTPException(403, "AI 원판정은 별도 검수에서 다룹니다.")
    if len({item.key for item in value.decisions}) != len(value.decisions):
        raise HTTPException(422, "같은 판정을 중복 수정하지 마세요.")
    data = doc.model_dump(mode="json")
    decisions = {item.key: item.model_dump(mode="json") for item in doc.decisions}
    manual = {item.key: item.model_dump(mode="json") for item in doc.manual_decisions}
    automatic = {item.key: item.model_dump(mode="json") for item in doc.automatic_decisions}
    observations = {item.code: item for item in sheets.analysis_input(doc.input_document).observations}
    try:
        for edit in value.decisions:
            if not set(edit.counter_codes) <= set(edit.evidence_codes):
                raise ValueError("반대 근거 코드도 선택한 원항목에 포함하세요.")
            support = [basis.model_dump(mode="json") for code in edit.evidence_codes if code not in edit.counter_codes for basis in observations[code].evidence]
            counter = [basis.model_dump(mode="json") for code in edit.counter_codes for basis in observations[code].evidence]
            decision = DecisionV4.model_validate_json(encode({**automatic[edit.key], **edit.model_dump(), "evidence": support, "counter_evidence": counter}))
            validate_judgement(decision, doc)
            manual[edit.key] = decision.model_dump(mode="json")
            apply = decision.status in ("complete", "held")
            decisions[edit.key] = manual[edit.key] if apply else automatic[edit.key]
            data["decision_sources"][edit.key] = "human" if apply else "automatic"
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    data.update(revision=doc.revision+1, actor=user.username, recorded_at=now(), change_reason=value.reason,
                previous=[*data["previous"], reference(row)], evaluation_context=context, decisions=list(decisions.values()), manual_decisions=list(manual.values()))
    ref, digest = write_result(store, data)
    with store.connect(write=True) as db:
        _, current = result_row(store, db, result_id, user, value.expected_revision)
        if evaluation_context(store, db, current) != context:
            raise HTTPException(409, "판정 저장 중 노출 상태가 변경되었습니다.")
        document_for(store, row)
        db.execute("UPDATE basic_results SET revision=?,manifest_ref=?,manifest_hash=? WHERE result_id=?", (data["revision"], ref, digest, result_id))
        store.audit(db, user.username, row["case_id"], "basic.judgement", {"result_id": result_id, "ref": ref, "hash": digest, "revision": data["revision"], "reason": value.reason})
    return view(store, result_id, user)
