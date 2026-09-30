"""Pinned basic results and accountable decisions; event opinions are separate."""

import hashlib
import json
import os
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from app import sheets
from app.domain.contracts_v3 import DecisionV3
from app.domain.results_v3 import BasicResultV3
from app.domain.sheets_v3 import SheetReferenceV3
from app.domain.validation_v3 import validate_decision_v3
from app.input_models import Model, Revision
from app.media import MediaError, probe
from app.preprocess_v3 import ASSET_HASHES, union_duration, verify_assets
from app.recording_v3 import validate_recording_media
from app.scoring_v3 import ATTACHMENT_TYPES, ENTRY_TYPES, OWNER_TYPES, RULE_HASH, RULE_VERSION, VOCAL_SEGMENTS, calculate, verify_rules
from app.storage import encode, now, uid


class CalculateV3(Model):
    input: SheetReferenceV3

    @field_validator("input", mode="before")
    @classmethod
    def contract(cls, value):
        return SheetReferenceV3.model_validate_json(json.dumps(value)) if isinstance(value, dict) else value


class DecisionEditV3(Model):
    key: Literal["attachment", "owner_type", "entry"]
    label: str | None
    status: Literal["draft", "complete", "held"]
    evidence_codes: Annotated[list[str], Field(max_length=109)]
    counter_codes: Annotated[list[str], Field(max_length=109)] = []
    counter_note: sheets.Reason | None = None
    opportunity_note: sheets.Reason
    reason: sheets.Reason


class JudgementEditV3(Revision):
    reason: sheets.Reason
    decisions: Annotated[list[DecisionEditV3], Field(min_length=1, max_length=3)]


class ResultSummaryV3(Model):
    result_id: str
    revision: int
    manifest_ref: str
    manifest_hash: str
    input: SheetReferenceV3

    @field_validator("input", mode="before")
    @classmethod
    def contract(cls, value):
        return CalculateV3.contract(value)


class ResultViewV3(Model):
    summary: ResultSummaryV3
    document: BasicResultV3
    sheet_changed: bool
    source_changed: bool

    @field_validator("document", mode="before")
    @classmethod
    def contract(cls, value):
        return BasicResultV3.model_validate_json(json.dumps(value)) if isinstance(value, dict) else value


def result_row(store, db, result_id, user, expected=None):
    row = db.execute("SELECT * FROM basic_results WHERE result_id=?", (result_id,)).fetchone()
    if not row:
        raise HTTPException(404, "기본 결과를 찾을 수 없습니다.")
    sheet_row = sheets.row_for(store, db, row["sheet_id"])
    sheets.owner(db, sheet_row, user)
    if expected is not None and row["revision"] != expected:
        raise HTTPException(409, "다른 판정 수정이 저장되었습니다. 입력을 보존하고 최신본을 조회하세요.")
    return row, sheet_row


def read_result(store, ref, digest):
    try:
        if not ref.startswith("results/"):
            raise ValueError("ref")
        raw = store.path(ref).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("hash")
        doc = BasicResultV3.model_validate_json(raw)
        source = sheets.read_document(store, doc.input.ref, doc.input.hash)
        if source != doc.input_document:
            raise ValueError("pinned input")
        return doc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "기본 결과 또는 고정 입력 파일이 손상되었습니다.") from exc


def document_for(store, row):
    doc = read_result(store, row["manifest_ref"], row["manifest_hash"])
    if (doc.result_id, doc.input.sheet_id, doc.case_id, doc.session_id, doc.revision) != tuple(row[key] for key in ("result_id", "sheet_id", "case_id", "session_id", "revision")):
        raise HTTPException(409, "기본 결과의 DB·파일 참조가 다릅니다.")
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
        row, sheet_row = result_row(store, db, result_id, user)
        doc = document_for(store, row)
        shown = row
        if revision is not None and revision != doc.revision:
            old = next((item for item in doc.previous if item.revision == revision), None)
            if not old:
                raise HTTPException(404, "보존한 기본 결과 revision이 아닙니다.")
            doc = read_result(store, old.ref, old.hash)
            shown = {"result_id": doc.result_id, "revision": doc.revision, "manifest_ref": old.ref, "manifest_hash": old.hash}
        case = store.case(db, row["case_id"])
        return {"summary": summary(shown, doc), "document": doc.model_dump(mode="json"),
                "sheet_changed": doc.input.revision != sheet_row["revision"], "source_changed": doc.input_document.source.input_revision != case["input_revision"]}


def pinned_sheet(store, row, requested):
    current = sheets.document_for(store, row)
    links = [sheets.reference(row), *[item.model_dump(mode="json") for item in current.previous]]
    if requested not in [SheetReferenceV3.model_validate_json(encode(link)) for link in links]:
        raise HTTPException(409, "이 시트의 명시한 revision/ref/hash를 선택하세요.")
    return sheets.read_document(store, requested.ref, requested.hash)


def evaluation_context(store, db, row):
    doc = sheets.document_for(store, row)
    inherited, ai_exposed = sheets.related_exposure(store, db, row, doc)
    links = {link.ref: link.model_dump(mode="json") for link in doc.exposures}
    links.update(inherited)
    exposed = doc.sheet.ai_exposed or ai_exposed
    return {"purpose": "review" if (links or exposed) and doc.purpose == "independent" else doc.purpose,
            "ai_exposed": exposed, "exposures": sorted(links.values(), key=lambda link: link["ref"])}


def write_result(store, data):
    doc = BasicResultV3.model_validate_json(encode(data))
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
    """Union of selected-camera audio metadata minus its recorded losses, on actual source time."""
    available, facts = {}, {}
    record = doc.source.session.recording
    offsets = {item.video_id: item.offset_seconds for item in record.video_offsets if item.confirmed}
    windows = {item.window_id: item for item in doc.source.windows}
    videos = {video.video_id: video for video in doc.source.session.videos}
    for item in doc.sheet.observations:
        if not item.vocalization:
            continue
        video_id = item.vocalization.video_id
        if video_id not in facts:
            try:
                facts[video_id] = {"video_sha256": videos[video_id].sha256, **probe(store.path(videos[video_id].storage_ref))}
            except MediaError as exc:
                raise HTTPException(422, str(exc)) from exc
        window = windows.get(VOCAL_SEGMENTS[item.code])
        if not window or window.start_sec is None or window.end_sec is None:
            continue
        start, end = window.start_sec + offsets.get(video_id, 0), window.end_sec + offsets.get(video_id, 0)
        pieces = [(max(start, part["start_sec"]), min(end, part["end_sec"])) for part in facts[video_id].get("audio_ranges", [])
                  if min(end, part["end_sec"]) > max(start, part["start_sec"])]
        for event in record.events:
            if event.kind != "audio_loss" or event.status != "observed" or event.video_id != video_id:
                continue
            if event.end_seconds is None:
                # Availability before a recorded loss remains usable; its unknown end cannot fill later audio.
                pieces = [(a, min(b, event.seconds)) for a, b in pieces if min(b, event.seconds) > a]
                continue
            pieces = [(left, right) for a, b in pieces for left, right in ((a, min(b, event.seconds)), (max(a, event.end_seconds), b)) if right > left]
        available[item.code] = union_duration(pieces)
    return available, facts


def initial_decisions(doc, ref, calculations):
    result = []
    for key, label, explanation in (("attachment", None, "다중 관계 근거와 반대 근거를 평가자가 검토해야 합니다. Q06 구조적 완결성 확인 대기"),
                                    ("owner_type", calculations.owner.label, calculations.owner.reason),
                                    ("entry", calculations.entry_label, calculations.entry_reason)):
        skipped = key == "attachment" and any(part.segment in ("alone", "reunion") and part.state == "not_performed" for part in doc.source.session.recording.segments)
        if skipped:
            explanation = "분리 생략/재회 미실시로 관계 판정보류; 관찰한 다른 원자료는 보존"
        result.append({"key": key, "label": label, "status": "held" if skipped else "draft", "evidence_codes": [], "evidence": [],
                       "counter_evidence": [], "opportunity_note": "고정 입력의 실제 관찰 기회 검토 필요", "reason": explanation,
                       "rater_id": doc.sheet.rater_id, "recorded_at": now(), "input_sheet_id": ref.sheet_id,
                       "input_revision": ref.revision, "input_sha256": ref.hash, "rule_version": RULE_VERSION})
    return result


def create(store, sheet_id, value, user):
    verify_rules()
    verify_assets()
    with store.connect() as db:
        row = sheets.row_for(store, db, sheet_id)
        sheets.owner(db, row, user)
        doc = pinned_sheet(store, row, value.input)
        context = evaluation_context(store, db, row)
    if any(getattr(doc.source, key) != digest for key, digest in ASSET_HASHES.items() if key != "rules_hash") or doc.source.window_rules_hash != ASSET_HASHES["rules_hash"]:
        raise HTTPException(409, "고정 입력의 카탈로그·절차·창 판본이 다릅니다.")
    sheets.validate_observations(doc, doc.sheet.model_dump(mode="json")["observations"])
    durations = validate_recording_media(store, doc.source.session, doc.source.session.recording)
    if any(evidence.end_seconds > durations[evidence.video_id] for item in doc.sheet.observations for evidence in item.evidence):
        raise HTTPException(422, "관찰 근거가 선택한 원본 길이 밖입니다.")
    if doc.source.preprocess:
        try:
            batch = store.path(doc.source.preprocess.ref).read_bytes()
            if hashlib.sha256(batch).hexdigest() != doc.source.preprocess.hash:
                raise ValueError("batch hash")
        except (OSError, ValueError) as exc:
            raise HTTPException(409, "고정한 전처리 batch가 손상되었습니다.") from exc
    audio, facts = audio_amounts(store, doc)
    calculated = calculate(doc, audio_available=audio)
    result_id = uid()
    data = {"result_id": result_id, "case_id": row["case_id"], "session_id": row["session_id"], "revision": 1,
            "actor": user.username, "recorded_at": now(), "change_reason": "명시한 시트 원본으로 기본 계산", "input": value.input.model_dump(mode="json"),
            "input_document": doc.model_dump(mode="json"), "rule_version": RULE_VERSION, "rule_hash": RULE_HASH,
            "audio_sources": facts, "evaluation_context": context, "calculations": calculated.model_dump(mode="json"), "decisions": initial_decisions(doc, value.input, calculated),
            "decision_sources": {key: "automatic" for key in ("attachment", "owner_type", "entry")}}
    ref, digest = write_result(store, data)
    verify_rules()
    verify_assets()
    validate_recording_media(store, doc.source.session, doc.source.session.recording)
    with store.connect(write=True) as db:
        current = sheets.row_for(store, db, sheet_id)
        sheets.owner(db, current, user)
        pinned_sheet(store, current, value.input)
        if evaluation_context(store, db, current) != context:
            raise HTTPException(409, "계산 중 평가 결과 노출 상태가 변경되었습니다. 다시 조회하세요.")
        db.execute("INSERT INTO basic_results VALUES (?,?,?,?,?,?,?)", (result_id, sheet_id, row["case_id"], row["session_id"], 1, ref, digest))
        store.audit(db, user.username, row["case_id"], "basic.calculate", {"result_id": result_id, "ref": ref, "hash": digest, "input": value.input.model_dump(mode="json")})
    return view(store, result_id, user)


def validate_judgement(decision, doc):
    """Shared human/AI completeness gate; no inferred numerical attachment cut-off."""
    validate_decision_v3(decision, sheets.CATALOG, sheets.PROTOCOL)
    labels = {"attachment": ATTACHMENT_TYPES, "owner_type": OWNER_TYPES, "entry": ENTRY_TYPES}
    if decision.key not in labels or decision.label is not None and decision.label not in labels[decision.key]:
        raise ValueError("원본의 기본 유형을 선택하세요. 보류는 유형이 아닌 상태입니다.")
    if (decision.rater_id, decision.input_sheet_id, decision.input_revision, decision.input_sha256, decision.rule_version) != (doc.input_document.sheet.rater_id, doc.input.sheet_id, doc.input.revision, doc.input.hash, doc.rule_version):
        raise ValueError("판정 작성자·고정 입력·규칙 연결이 다릅니다.")
    observations = {item.code: item for item in doc.input_document.sheet.observations}
    selected = [observations.get(code) for code in decision.evidence_codes]
    if any(item is None or item.status != "observed" or item.validity in ("invalid", "unknown") for item in selected):
        raise ValueError("판정 근거는 이 원본에서 관찰한 유효 항목이어야 합니다.")
    allowed = {encode(evidence.model_dump(mode="json")) for item in selected for evidence in item.evidence}
    if any(encode(evidence.model_dump(mode="json")) not in allowed for evidence in (*decision.evidence, *decision.counter_evidence)):
        raise ValueError("판정 영상 근거는 선택한 원항목의 실제 근거와 같아야 합니다.")
    record = doc.input_document.source.session.recording
    if decision.key == "attachment" and any(part.segment in ("alone", "reunion") and part.state == "not_performed" for part in record.segments):
        if decision.status != "held":
            raise ValueError("분리/재회 미실시는 관계 판정보류입니다.")
    if decision.status == "complete":
        if not decision.counter_evidence and decision.counter_note is None:
            raise ValueError("반대 근거를 기록하거나 검토 후 없는 이유를 명시하세요.")
        windows = {window.window_id: window for window in doc.input_document.source.windows}
        for item in selected:
            for basis in item.evidence:
                guard = {"ignore": "보12", "walk": "보13"}.get(windows[basis.window_id].segment)
                if item.code == "개30":
                    guard = "보14"
                condition = observations.get(guard)
                if condition and condition.status == "observed" and condition.value == 3 and basis in decision.evidence:
                    raise ValueError(f"{guard}=3인 해당 구간은 완료 판정의 사용 근거에서 제외하세요. 다른 유효 근거는 보존합니다.")
        if not decision.reason.strip() or not decision.opportunity_note.strip() or not decision.recorded_at.strip():
            raise ValueError("완료 판정의 이유·관찰 기회·작성 일자가 필요합니다.")
        observed = [basis for basis in decision.evidence if basis.observed_seconds > 0 and basis.end_seconds > basis.start_seconds]
        codes = {item.code for item in selected if any(evidence in observed for evidence in item.evidence)}
        if not observed:
            raise ValueError("완료 판정의 실제 확인량과 관찰 범위가 필요합니다.")
        if decision.key == "attachment" and (not codes & {"개9", "개10", "개17", "개19", "개21", "개22"}
                                             or not codes & {"개8", "개18", "개23", "개44", "개58"}):
            raise ValueError("관계 완료 판정은 접근과 몸 상태의 다중 근거가 필요합니다. 단일 행동·꼬리·누움으로 완료하지 않습니다.")
        if decision.key == "attachment":
            scenes = {windows[basis.window_id].segment for basis in observed}
            if not {"alone", "reunion"} <= scenes:
                raise ValueError("보호자 관계 완료 판정은 실제 분리와 재회 두 장면의 근거가 필요합니다. 낯선 반응은 보조입니다.")
        if decision.key == "owner_type" and not codes & {"보6", "보9", "보22", "보39", "보23", "보24"}:
            raise ValueError("교육태도 완료 판정은 원본 보호자 배점 항목의 근거가 필요합니다.")
        if decision.key == "owner_type" and not codes & {item.code for item in doc.calculations.owner.items if item.used}:
            raise ValueError("교육태도 완료 판정에 실제 기회·유효 배점 근거가 필요합니다.")
        if decision.key == "owner_type":
            primary = {item.code for item in doc.calculations.owner.items}
            raw_bases = {encode(basis.model_dump(mode="json")) for item in selected if item.code in primary for basis in item.evidence}
            used_bases = {encode(basis.model_dump(mode="json")) for item in doc.calculations.owner.items if item.used and item.code in codes for basis in item.used_evidence}
            if any(encode(basis.model_dump(mode="json")) in raw_bases and encode(basis.model_dump(mode="json")) not in used_bases for basis in decision.evidence):
                raise ValueError("교육태도 완료 근거에서 중단/지시 뒤 조치·제외한 배점 범위를 사용하지 마세요.")
        if decision.key == "entry" and not codes & set(("개5", "개6", "개30")):
            raise ValueError("입장 완료 판정은 원본 입장 행동 근거가 필요합니다.")
        if any(evidence.scoring_exclusion != "none" for evidence in decision.evidence):
            raise ValueError("배점 제외한 안전조치/지시 근거로 완료하지 않습니다.")
    return decision


def revise(store, result_id, value, user):
    with store.connect() as db:
        row, sheet_row = result_row(store, db, result_id, user, value.expected_revision)
        doc = document_for(store, row)
        context = evaluation_context(store, db, sheet_row)
    if doc.input_document.sheet.rater_kind != "human":
        raise HTTPException(403, "AI 기본 판정은 별도 검수 기록으로 다룹니다. 원본 작성자를 바꿔 덮어쓰지 않습니다.")
    if len({item.key for item in value.decisions}) != len(value.decisions):
        raise HTTPException(422, "같은 기본 판정을 중복 수정하지 마세요.")
    data = doc.model_dump(mode="json")
    data["evaluation_context"] = context
    decisions = {item.key: item.model_dump(mode="json") for item in doc.decisions}
    observations = {item.code: item for item in doc.input_document.sheet.observations}
    try:
        for edit in value.decisions:
            owner_bases = {item.code: item.used_evidence for item in doc.calculations.owner.items}
            supporting = [basis.model_dump(mode="json") for code in edit.evidence_codes if code not in edit.counter_codes
                          for basis in (owner_bases.get(code, observations[code].evidence) if edit.key == "owner_type" else observations[code].evidence)]
            counter = [basis.model_dump(mode="json") for code in edit.counter_codes for basis in observations[code].evidence]
            if not set(edit.counter_codes) <= set(edit.evidence_codes):
                raise ValueError("반대 근거도 선택한 원항목에 포함해야 합니다.")
            decision = DecisionV3.model_validate_json(encode({**decisions[edit.key], **edit.model_dump(exclude={"counter_codes"}),
                "evidence": supporting, "counter_evidence": counter, "recorded_at": now()}))
            validate_judgement(decision, doc)
            decisions[edit.key] = decision.model_dump(mode="json")
            data["decision_sources"][edit.key] = "human"
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    data.update(revision=doc.revision + 1, actor=user.username, recorded_at=now(), change_reason=value.reason,
                previous=[*data["previous"], reference(row)], decisions=list(decisions.values()))
    ref, digest = write_result(store, data)
    with store.connect(write=True) as db:
        _, current_sheet = result_row(store, db, result_id, user, value.expected_revision)
        if evaluation_context(store, db, current_sheet) != context:
            raise HTTPException(409, "판정 저장 중 다른 평가 결과를 열었습니다. 최신 노출 기록으로 다시 저장하세요.")
        document_for(store, row)
        db.execute("UPDATE basic_results SET revision=?,manifest_ref=?,manifest_hash=? WHERE result_id=?", (data["revision"], ref, digest, result_id))
        store.audit(db, user.username, row["case_id"], "basic.judgement", {"result_id": result_id, "ref": ref, "hash": digest, "revision": data["revision"], "reason": value.reason})
    return view(store, result_id, user)
