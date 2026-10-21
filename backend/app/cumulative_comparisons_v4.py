"""Comparison-owned pair registry and representative survey submissions (CM02).

Raw survey bytes and case inputs are never edited here. Each write pins the actual actor, an
expected pair revision and an idempotent request; history is the immutable previous-state chain.
"""
import json
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from . import analysis, comparison_mapping_v4 as mapping, comparisons_v4 as comparisons
from .domain.cumulative_comparisons_v4 import (PairCaseV4, PairInventoryV4, PairStateReferenceV4, PairStateV4, PairViewV4,
    SubmissionReferenceV4, SubmissionSummaryV4, SubmissionV4)
from .domain.sheets_v4 import InputPointerV4
from .input_models import Model
from .input_models_v4 import ManifestV4
from .storage import encode, now, uid
from .survey_v4 import survey_scores_v4

STATE_ACTION = "comparison.pair_state"
CASE_ACTION = "comparison.pair_case"
SUBMISSION_ACTION = "comparison.submission"
REQUEST_ACTION = "comparison.pair_request"
Reason = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
RequestId = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]


class PairLinkV4(Model):
    request_id: RequestId
    case_id: Annotated[str, Field(min_length=1, max_length=200)]
    pair_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    expected_revision: Annotated[int, Field(ge=0)]
    expected_case_pair_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    expected_case_pair_revision: Annotated[int, Field(ge=1)] | None = None
    reason: Reason


class SubmissionCreateV4(Model):
    request_id: RequestId
    expected_revision: Annotated[int, Field(ge=1)]
    kind: Literal["first", "correction", "revisit"]
    case_id: Annotated[str, Field(min_length=1, max_length=200)]
    session_id: Annotated[str, Field(min_length=1, max_length=200)]
    input: InputPointerV4 | None = None
    expected_input_revision: Annotated[int, Field(ge=1)] | None = None
    evidence: Reason
    submitted_at: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")] | None = None

    @field_validator("input", mode="before")
    @classmethod
    def pointer(cls, value):
        return InputPointerV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


class PairStatusV4(Model):
    request_id: RequestId
    expected_revision: Annotated[int, Field(ge=1)]
    status: Literal["included", "excluded"]
    reason: Reason


def _latest(db, action, target):
    row = db.execute("SELECT detail_json FROM changes WHERE action=? AND target=? ORDER BY rowid DESC LIMIT 1", (action, target)).fetchone()
    return json.loads(row[0]) if row else None


def pair_head(db, pair_id):
    record = _latest(db, STATE_ACTION, pair_id)
    return PairStateReferenceV4.model_validate_json(encode(record["reference"])) if record else None


def case_pair(db, case_id):
    record = _latest(db, CASE_ACTION, case_id)
    return record["pair_id"] if record else None


def read_state(store, pointer):
    doc = comparisons._read(store, pointer, PairStateV4)
    if (doc.pair_id, doc.revision) != (pointer.pair_id, pointer.revision):
        raise HTTPException(409, "참여쌍 기록의 고정 참조가 다릅니다.")
    return doc


def read_submission(store, pointer):
    doc = comparisons._read(store, pointer, SubmissionV4)
    if doc.submission_id != pointer.submission_id:
        raise HTTPException(409, "설문 제출 기록의 고정 참조가 다릅니다.")
    return doc


def frozen_session(store, db, case_id, pointer, session_id):
    """Read an explicitly pinned input: the case's current manifest or one it lists as preserved prior input."""
    row = store.case(db, case_id)
    current = (row["manifest_ref"], row["manifest_hash"]) == (pointer.manifest_ref, pointer.manifest_hash)
    live = store.manifest(row)
    if not isinstance(live, ManifestV4):
        raise HTTPException(409, "S1 설문 입력만 누적 비교에 제출할 수 있습니다.")
    if not current and not any((item.ref, item.hash) == (pointer.manifest_ref, pointer.manifest_hash) for item in live.prior_inputs):
        raise HTTPException(409, "이 대상의 현재 또는 보존된 이전 입력이 아닙니다.")
    frozen = comparisons._read(store, comparisons.FileV4(ref=pointer.manifest_ref, hash=pointer.manifest_hash), ManifestV4, prefix="inputs/")
    if frozen.case_id != case_id:
        raise HTTPException(409, "고정 입력의 대상이 다릅니다.")
    session = next((item for item in frozen.sessions if item.session_id == session_id), None)
    if session is None:
        raise HTTPException(404, "고정 입력에 이 회차가 없습니다.")
    return frozen, session


def representative_input(store, db, state):
    """Re-verify a representative against current pair membership; corruption is a technical error."""
    if state.representative is None:
        raise HTTPException(409, "대표 설문이 확정되지 않았습니다.")
    submission = read_submission(store, state.representative)
    if submission.pair_id != state.pair_id or submission.case_id not in state.case_ids or case_pair(db, submission.case_id) != state.pair_id:
        raise HTTPException(409, "대표 설문의 대상이 현재 참여쌍에 속하지 않습니다.")
    frozen, session = frozen_session(store, db, submission.case_id, submission.input, submission.session_id)
    if frozen.input_revision != submission.input_revision or session.survey_version != submission.survey_version:
        raise HTTPException(409, "대표 설문의 고정 입력 판본이 다릅니다.")
    return submission, session


def _request(db, user, value):
    target = f"{user.username}:{value.request_id}"
    digest = analysis.digest({"kind": type(value).__name__, "request": value.model_dump(mode="json")})
    previous = _latest(db, REQUEST_ACTION, target)
    if previous and previous["request_hash"] != digest:
        raise HTTPException(409, "같은 요청 ID에 다른 참여쌍 요청을 사용할 수 없습니다.")
    return target, digest, previous


def _state(store, db, user, previous, pair_id, request_target, **update):
    base = {"case_ids": (), "status": "included", "status_reason": None, "representative": None} if previous is None else {
        key: getattr(previous, key) for key in ("case_ids", "status", "status_reason", "representative")}
    revision = 1 if previous is None else previous.revision + 1
    prior = None if previous is None else pair_head(db, pair_id)
    doc = PairStateV4.model_validate_json(encode({**{key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        for key, value in {**base, **update}.items()}, "pair_id": pair_id, "revision": revision,
        "previous": prior.model_dump(mode="json") if prior else None, "actor": user.username, "recorded_at": now()}))
    file = comparisons._write(store, "pairs", doc)
    pointer = PairStateReferenceV4(pair_id=pair_id, revision=revision, ref=file.ref, hash=file.hash)
    if read_state(store, pointer) != doc:
        raise HTTPException(409, "참여쌍 기록 저장 중 내용이 달라졌습니다.")
    store.audit(db, user.username, pair_id, STATE_ACTION, {"reference": pointer.model_dump(mode="json"), "request": request_target})
    return doc


def _current(store, db, pair_id, expected):
    head = pair_head(db, pair_id)
    if head is None:
        raise HTTPException(404, "참여쌍을 찾을 수 없습니다.")
    if head.revision != expected:
        raise HTTPException(409, "참여쌍이 다른 요청으로 변경되었습니다. 새로 조회하세요.")
    return read_state(store, head)


def link(store, value: PairLinkV4, user):
    value = PairLinkV4.model_validate_json(value.model_dump_json())
    with store.connect(write=True) as db:
        comparisons._account(db, user)
        target, digest, previous = _request(db, user, value)
        if previous:
            pair_id = previous["pair_id"]
        else:
            store.case(db, value.case_id)
            if not isinstance(store.manifest(store.case(db, value.case_id)), ManifestV4):
                raise HTTPException(409, "S1 입력 대상만 참여쌍에 연결할 수 있습니다.")
            current = case_pair(db, value.case_id)
            if current != value.expected_case_pair_id:
                raise HTTPException(409, "이 대상의 참여쌍 연결이 변경되었습니다. 새로 조회하세요.")
            if value.pair_id is None:
                if value.expected_revision != 0:
                    raise HTTPException(409, "새 참여쌍은 기존 판본 없이 만듭니다.")
                pair_id, destination = uid(), None
            else:
                pair_id, destination = value.pair_id, _current(store, db, value.pair_id, value.expected_revision)
            if current == pair_id:
                raise HTTPException(409, "이미 이 참여쌍에 연결된 대상입니다.")
            if current is not None:
                if value.expected_case_pair_revision is None:
                    raise HTTPException(422, "기존 참여쌍에서 옮길 때는 그 참여쌍의 판본을 함께 확인하세요.")
                source = _current(store, db, current, value.expected_case_pair_revision)
                moved = source.representative is not None and read_submission(store, source.representative).case_id == value.case_id
                _state(store, db, user, source, current, target, action="unlink", reason=value.reason,
                       case_ids=tuple(item for item in source.case_ids if item != value.case_id),
                       **({"representative": None} if moved else {}))
            _state(store, db, user, destination, pair_id, target, action="create" if destination is None else "link", reason=value.reason,
                   case_ids=(*(destination.case_ids if destination else ()), value.case_id))
            store.audit(db, user.username, value.case_id, CASE_ACTION, {"pair_id": pair_id, "previous_pair_id": current})
            store.audit(db, user.username, target, REQUEST_ACTION, {"request_hash": digest, "pair_id": pair_id})
    return pair_view(store, user, pair_id)


def submit(store, pair_id, value: SubmissionCreateV4, user):
    value = SubmissionCreateV4.model_validate_json(value.model_dump_json())
    loaded = mapping.load()
    with store.connect(write=True) as db:
        comparisons._account(db, user)
        target, digest, previous = _request(db, user, value)
        if previous:
            if previous["pair_id"] != pair_id:
                raise HTTPException(409, "같은 요청 ID가 다른 참여쌍에 사용되었습니다.")
        else:
            state = _current(store, db, pair_id, value.expected_revision)
            if value.case_id not in state.case_ids or case_pair(db, value.case_id) != pair_id:
                raise HTTPException(409, "이 참여쌍에 연결된 대상의 설문만 제출할 수 있습니다.")
            if (value.kind == "first") != (state.representative is None):
                raise HTTPException(409, "최초 제출은 대표가 없을 때만, 정정·재방문은 대표가 있을 때만 기록합니다.")
            if value.kind == "correction" and read_submission(store, state.representative).case_id != value.case_id:
                # A correction fixes the representative's own mis-entry; it never promotes another visit or case.
                raise HTTPException(409, "오입력 정정은 현재 대표 설문과 같은 대상에서만 기록합니다.")
            pinned = value.input
            if pinned is None:
                # Without an explicit preserved pointer the submission pins the case's current input revision.
                if value.expected_input_revision is None:
                    raise HTTPException(422, "현재 입력 판본을 함께 확인하세요.")
                row = store.case(db, value.case_id, expected=value.expected_input_revision)
                pinned = InputPointerV4(manifest_ref=row["manifest_ref"], manifest_hash=row["manifest_hash"])
            frozen, session = frozen_session(store, db, value.case_id, pinned, value.session_id)
            if session.survey_version != loaded.survey_version:
                raise HTTPException(422, "전달 기준과 같은 설문 판본인지 확인되지 않아 누적 비교에 제출할 수 없습니다.")
            survey_scores_v4(session, comparisons.SurveyCatalogV3.model_validate_json(
                (comparisons.RESOURCES / comparisons.SURVEY_ASSETS[0]).read_bytes()))
            doc = SubmissionV4(submission_id=uid(), pair_id=pair_id, case_id=value.case_id, session_id=value.session_id,
                input_revision=frozen.input_revision, input=pinned, survey_version=session.survey_version,
                policy_version=loaded.policy_version, mapping_version=loaded.version, question_signature=mapping.question_signature(),
                kind=value.kind, evidence=value.evidence, submitted_at=value.submitted_at,
                replaces=state.representative if value.kind == "correction" else None, actor=user.username, recorded_at=now())
            file = comparisons._write(store, "submissions", doc)
            pointer = SubmissionReferenceV4(submission_id=doc.submission_id, ref=file.ref, hash=file.hash)
            if read_submission(store, pointer) != doc:
                raise HTTPException(409, "설문 제출 기록 저장 중 내용이 달라졌습니다.")
            store.audit(db, user.username, doc.submission_id, SUBMISSION_ACTION,
                        {"reference": pointer.model_dump(mode="json"), "pair_id": pair_id, "case_id": value.case_id, "kind": value.kind})
            if value.kind != "revisit":
                _state(store, db, user, state, pair_id, target, action=value.kind, reason=value.evidence, representative=pointer)
            store.audit(db, user.username, target, REQUEST_ACTION, {"request_hash": digest, "pair_id": pair_id, "submission_id": doc.submission_id})
    return pair_view(store, user, pair_id)


def set_status(store, pair_id, value: PairStatusV4, user):
    value = PairStatusV4.model_validate_json(value.model_dump_json())
    with store.connect(write=True) as db:
        comparisons._account(db, user)
        target, digest, previous = _request(db, user, value)
        if previous:
            if previous["pair_id"] != pair_id:
                raise HTTPException(409, "같은 요청 ID가 다른 참여쌍에 사용되었습니다.")
        else:
            state = _current(store, db, pair_id, value.expected_revision)
            if state.status == value.status:
                raise HTTPException(409, "이미 같은 포함 상태입니다.")
            if value.status == "included" and state.representative is not None:
                # Re-including re-verifies membership and question identity; a preserved pointer alone is not eligibility.
                submission, _ = representative_input(store, db, state)
                loaded = mapping.load()
                if (submission.question_signature, submission.mapping_version, submission.policy_version) != (
                        mapping.question_signature(), loaded.version, loaded.policy_version):
                    raise HTTPException(409, "대표 설문의 문항·매핑 판본이 현재 기준과 달라 다시 포함할 수 없습니다. 대표를 다시 확인하세요.")
            _state(store, db, user, state, pair_id, target, action="exclude" if value.status == "excluded" else "include",
                   reason=value.reason, status=value.status, status_reason=value.reason if value.status == "excluded" else None)
            store.audit(db, user.username, target, REQUEST_ACTION, {"request_hash": digest, "pair_id": pair_id})
    return pair_view(store, user, pair_id)


def _view(store, db, pair_id):
    pointer = pair_head(db, pair_id)
    state = read_state(store, pointer)
    cases = []
    for case_id in state.case_ids:
        row = store.case(db, case_id)
        cases.append(PairCaseV4(case_id=case_id, event_id=row["event_id"], participant_id=row["participant_id"],
                                dog_name=row["dog_name"] or "", guardian_name=row["guardian_name"] or ""))
    submissions = []
    for (detail,) in db.execute("SELECT detail_json FROM changes WHERE action=? AND json_extract(detail_json,'$.pair_id')=? ORDER BY rowid",
                                (SUBMISSION_ACTION, pair_id)):
        reference = SubmissionReferenceV4.model_validate_json(encode(json.loads(detail)["reference"]))
        doc = read_submission(store, reference)
        submissions.append(SubmissionSummaryV4(reference=reference, kind=doc.kind, case_id=doc.case_id, session_id=doc.session_id,
            input_revision=doc.input_revision, evidence=doc.evidence, submitted_at=doc.submitted_at, actor=doc.actor,
            recorded_at=doc.recorded_at, representative=state.representative == reference))
    return PairViewV4(pair_id=pair_id, revision=state.revision, reference=pointer, status=state.status, status_reason=state.status_reason,
        representative_status="confirmed" if state.representative else "unconfirmed", cases=tuple(cases),
        submissions=tuple(submissions), actor=state.actor, recorded_at=state.recorded_at)


def pair_view(store, user, pair_id):
    with store.connect() as db:
        comparisons._account(db, user, reader=True)
        if pair_head(db, pair_id) is None:
            raise HTTPException(404, "참여쌍을 찾을 수 없습니다.")
        return _view(store, db, pair_id)


def pair_ids(db):
    return [row[0] for row in db.execute("SELECT DISTINCT target FROM changes WHERE action=? ORDER BY target", (STATE_ACTION,))]


def inventory(store, user, case_id=None):
    """Read-only; polling records no submission or edit event."""
    with store.connect() as db:
        comparisons._account(db, user, reader=True)
        if case_id is not None:
            store.case(db, case_id)
        views = tuple(_view(store, db, pair_id) for pair_id in pair_ids(db))
        linked = {case.case_id for view in views for case in view.cases}
        s1 = sum(1 for row in db.execute("SELECT manifest_schema_version FROM cases") if row[0] == "intake-4.0")
    counts = {"pairs": len(views), "included_confirmed": sum(view.status == "included" and view.representative_status == "confirmed" for view in views),
              "representative_unconfirmed": sum(view.representative_status == "unconfirmed" for view in views),
              "excluded": sum(view.status == "excluded" for view in views), "unlinked_s1_cases": max(s1 - len(linked), 0)}
    return PairInventoryV4(case_pair_id=next((view.pair_id for view in views if any(case.case_id == case_id for case in view.cases)), None)
                           if case_id else None, pairs=views, counts=counts)
