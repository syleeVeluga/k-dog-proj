"""Comparison-owned pair registry and representative survey submissions (CM02).

Raw survey bytes and case inputs are never edited here. Each write pins the actual actor, an
expected pair revision and an idempotent request; history is the immutable previous-state chain.
"""
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from . import analysis, comparison_mapping_v4 as mapping, comparisons_v4 as comparisons
from .domain.cumulative_comparisons_v4 import (ComparisonRowV4, CumulativeExclusionV4, CumulativeMemberV4, CumulativeMetricV4,
    CumulativePublicV4, CumulativeReferenceV4, CumulativeSnapshotV4, MemberMetricV4, PairCaseV4, PairInventoryV4, PairStateReferenceV4,
    PairStateV4, PairViewV4, SubmissionReferenceV4, SubmissionSummaryV4, SubmissionV4)
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


# CM03: admission-time cumulative aggregation pinned into report outputs.
SNAPSHOT_ACTION = "comparison.cumulative.snapshot"
CUMULATIVE_SENTENCES = {
    "higher": "{domain} 설문 점수는 {ours}점으로, 우리 누적 참여견 평균 {cumulative}점(n={n})보다 높게 나타났습니다.",
    "lower": "{domain} 설문 점수는 {ours}점으로, 우리 누적 참여견 평균 {cumulative}점(n={n})보다 낮게 나타났습니다.",
    "equal_display": "{domain} 설문 점수는 {ours}점으로, 소수 둘째 자리 표시 기준에서 우리 누적 참여견 평균(n={n})과 같습니다.",
}
NOT_READY = "사용 가능한 외부 비교 기준 정의가 없습니다."


def display(numerator, denominator):
    """Excel ROUND(x,2) for non-negative exact ratios: half-up on the exact value, never on binary floats."""
    return str((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def local_date(recorded_at):
    """Operator-facing reference date in Korea time (UTC+9, no daylight saving)."""
    from datetime import datetime, timedelta, timezone
    return datetime.fromisoformat(recorded_at).astimezone(timezone(timedelta(hours=9))).date().isoformat()


def compare(ours, other):
    left, right = Decimal(ours), Decimal(other)
    return "higher" if left > right else "lower" if left < right else "equal_display"


def _assets():
    return {name: hashlib.sha256((comparisons.RESOURCES / name).read_bytes()).hexdigest()
            for name in (comparisons.SURVEY_ASSETS[0], "rules/survey-policy-20261007.json")}


def _member_metrics(session, loaded):
    values = mapping.evaluate(dict(session.survey), loaded)
    return tuple(MemberMetricV4(metric_id=key, **values[key]) for key in mapping.METRIC_IDS)


def _aggregate(members, loaded):
    result = []
    for metric in loaded.metrics:
        included, excluded, numerator = [], {}, 0
        for member in members:
            value = next(item for item in member.metrics if item.metric_id == metric.metric_id)
            if value.status == "valid":
                included.append(member.pair_id); numerator += value.numerator
            else:
                excluded[member.pair_id] = value.status
        denominator = len(included) * len(metric.question_ids)
        result.append(CumulativeMetricV4(metric_id=metric.metric_id, question_ids=metric.question_ids, numerator=numerator,
            denominator=denominator, n=len(included), mean=numerator / denominator if included else None,
            display=display(numerator, denominator) if included else None, included_pair_ids=tuple(included), response_excluded=excluded))
    return tuple(result)


def _select(store, db, loaded):
    """Read every pair head once; corruption or broken membership is a technical error, never an exclusion."""
    heads, members, exclusions = [], [], []
    signature = mapping.question_signature()
    for pair_id in pair_ids(db):
        head = pair_head(db, pair_id)
        state = read_state(store, head)
        heads.append(head)
        if state.status == "excluded":
            exclusions.append(CumulativeExclusionV4(pair_id=pair_id, state=head, reason="excluded")); continue
        if state.representative is None:
            exclusions.append(CumulativeExclusionV4(pair_id=pair_id, state=head, reason="representative_unconfirmed")); continue
        submission, session = representative_input(store, db, state)
        if (submission.question_signature, submission.survey_version, session.survey_version) != (signature, loaded.survey_version, loaded.survey_version):
            exclusions.append(CumulativeExclusionV4(pair_id=pair_id, state=head, reason="version_unconfirmed")); continue
        members.append(CumulativeMemberV4(pair_id=pair_id, state=head, submission=state.representative, case_id=submission.case_id,
            session_id=submission.session_id, input_revision=submission.input_revision, input=submission.input,
            metrics=_member_metrics(session, loaded)))
    return tuple(heads), tuple(members), tuple(exclusions)


def build_snapshot(store, user, request_id, case_id, session_id):
    """Pin the representative set and nine metric aggregates once, for one new report admission."""
    loaded = mapping.load()
    with store.connect() as db:
        comparisons._account(db, user, reader=True)
        heads, members, exclusions = _select(store, db, loaded)
    doc = CumulativeSnapshotV4(snapshot_id=uid(), request_id=request_id, actor=user.username, recorded_at=now(), case_id=case_id,
        session_id=session_id, mapping_version=loaded.version, mapping_hash=mapping.asset_hash(), question_signature=mapping.question_signature(),
        survey_assets=_assets(), pair_heads=heads, members=members, exclusions=exclusions, metrics=_aggregate(members, loaded))
    file = comparisons._write(store, "cumulative", doc)
    return doc, CumulativeReferenceV4(snapshot_id=doc.snapshot_id, ref=file.ref, hash=file.hash)


def adopt_snapshot(store, db, doc, pointer, user):
    """Inside the admission write: the candidate set must still be current, otherwise retry with a new request."""
    if tuple(pair_head(db, pair_id) for pair_id in pair_ids(db)) != doc.pair_heads:
        raise HTTPException(409, "누적 비교 대상이 접수 중 변경되었습니다. 다시 발급을 요청하세요.")
    if (mapping.asset_hash(), _assets()) != (doc.mapping_hash, doc.survey_assets) or comparisons._read(store, pointer, CumulativeSnapshotV4) != doc:
        raise HTTPException(409, "누적 비교 기준 또는 snapshot이 접수 중 변경되었습니다.")
    store.audit(db, user.username, doc.snapshot_id, SNAPSHOT_ACTION, {"reference": pointer.model_dump(mode="json"), "request_id": doc.request_id,
        "case_id": doc.case_id, "session_id": doc.session_id})


def snapshot_document(store, pointer, db=None, *, recompute=True):
    """Re-verify a pinned snapshot from its own parents; the current registry is never consulted.

    Issued outputs (recompute=False) are read in their own edition: parent hashes are checked but the
    current mapping/catalog never re-evaluates or blocks them. New admissions and workers recompute.
    """
    pointer = CumulativeReferenceV4.model_validate(pointer)
    doc = comparisons._read(store, pointer, CumulativeSnapshotV4)
    if doc.snapshot_id != pointer.snapshot_id:
        raise HTTPException(409, "누적 비교 snapshot 참조가 다릅니다.")
    if db is None:
        with store.connect() as reader:
            record = _latest(reader, SNAPSHOT_ACTION, pointer.snapshot_id)
    else:
        record = _latest(db, SNAPSHOT_ACTION, pointer.snapshot_id)
    if record is None or record["reference"] != pointer.model_dump(mode="json"):
        raise HTTPException(409, "채택되지 않은 누적 비교 snapshot입니다.")
    if not recompute:
        for item in snapshot_files(store, pointer):
            comparisons._read(store, item, _Raw, prefix=item.ref.split("/")[0] + "/")
        return doc
    if doc.mapping_hash != mapping.asset_hash():
        raise HTTPException(409, "누적 비교 문항 매핑 판본이 변경되어 새 실행에 사용할 수 없습니다.")
    loaded = mapping.load()
    for exclusion in doc.exclusions:
        read_state(store, exclusion.state)
    for member in doc.members:
        state = read_state(store, member.state)
        submission = read_submission(store, member.submission)
        if state.representative != member.submission or (submission.pair_id, submission.case_id, submission.session_id, submission.input) != (
                member.pair_id, member.case_id, member.session_id, member.input):
            raise HTTPException(409, "누적 비교의 대표 설문 고정 참조가 다릅니다.")
        frozen = comparisons._read(store, comparisons.FileV4(ref=member.input.manifest_ref, hash=member.input.manifest_hash), ManifestV4, prefix="inputs/")
        session = next((item for item in frozen.sessions if item.session_id == member.session_id), None)
        if session is None or frozen.input_revision != member.input_revision or _member_metrics(session, loaded) != member.metrics:
            raise HTTPException(409, "누적 비교의 대표 설문 원응답이 고정값과 다릅니다.")
    if _aggregate(doc.members, loaded) != doc.metrics:
        raise HTTPException(409, "누적 평균·유효 n이 고정 원자료와 다릅니다.")
    return doc


class _Raw:
    """Hash-only read: the bytes are verified, not reparsed under the current models."""
    @staticmethod
    def model_validate_json(raw):
        return raw


def snapshot_files(store, pointer):
    pointer = CumulativeReferenceV4.model_validate(pointer)
    doc = comparisons._read(store, pointer, CumulativeSnapshotV4)
    files = {pointer.ref: pointer.hash}
    for item in (*doc.members, *doc.exclusions):
        files[item.state.ref] = item.state.hash
    for member in doc.members:
        files[member.submission.ref] = member.submission.hash
        files[member.input.manifest_ref] = member.input.manifest_hash
    return tuple(comparisons.FileV4(ref=ref, hash=digest) for ref, digest in sorted(files.items()))


def public_rows(doc, pointer, survey, external=None, external_reasons=None):
    """Renderer-ready rows from the pinned snapshot, the report's own survey and its pinned external snapshot."""
    loaded = mapping.load()
    individual = mapping.evaluate({item.item_id: item.raw for item in survey.items}, loaded)
    entries = {entry.gate.source_id: entry for entry in (external.entries if external else ())}
    edition_ok = (survey.survey_version, survey.policy_version) == (loaded.survey_version, loaded.policy_version)
    rows = []
    for metric, aggregate in zip(loaded.metrics, doc.metrics, strict=True):
        own = individual[metric.metric_id] if edition_ok else {"status": "version_check", "numerator": None, "denominator": None}
        status = own["status"]
        valid = status == "valid"
        ours = display(own["numerator"], own["denominator"]) if valid else None
        shown = valid and aggregate.n >= loaded.minimum_cumulative_n
        cumulative = compare(ours, aggregate.display) if shown else None
        notice_id = None if valid else {"insufficient": "TXT-M", "input_check": "TXT-I", "version_check": "TXT-V"}[status]
        source = next((item for item in loaded.external_sources if item.metric_id == metric.metric_id), None)
        entry = entries.get(source.source_id) if source and valid else None
        if source is None:
            external_status, reason = "not_mapped", None
        elif not valid:
            external_status, reason = "individual_unavailable", "개별 응답이 비교 조건을 충족하지 않아 외부 비교를 표시하지 않습니다."
        elif entry is None:
            external_status, reason = "not_ready", (external_reasons or {}).get(source.source_id) or NOT_READY
        else:
            external_status, reason = "ready", None
        values = entry.gate.values if entry else None
        reference = display(Decimal(str(values.mean)), 1) if values else None
        external_comparison = compare(ours, reference) if entry else None
        sentence_id = {"higher": "TXT-H", "lower": "TXT-L", "equal_display": "TXT-E"}[external_comparison] if entry else None
        rows.append(ComparisonRowV4(metric_id=metric.metric_id, alias=metric.alias, title=metric.title, question_ids=metric.question_ids,
            scale_minimum=metric.scale_minimum, scale_maximum=metric.scale_maximum, direction=metric.direction, individual_status=status,
            individual_raw=own["numerator"] / own["denominator"] if valid else None, individual_display=ours,
            individual_numerator=own["numerator"], individual_denominator=own["denominator"], cumulative_n=aggregate.n,
            cumulative_raw=aggregate.mean, cumulative_display=aggregate.display, cumulative_numerator=aggregate.numerator,
            cumulative_denominator=aggregate.denominator, cumulative_shown=shown, cumulative_comparison=cumulative,
            cumulative_sentence=CUMULATIVE_SENTENCES[cumulative].format(domain=metric.title, ours=ours, cumulative=aggregate.display, n=aggregate.n) if shown else None,
            external_status=external_status, external_reason=reason, external_source_id=source.source_id if source else None,
            external_mean=values.mean if values else None, external_display=reference, external_standard_deviation=values.standard_deviation if values else None,
            external_valid_n=values.valid_n if values else None, external_total_n=values.total_n if values else None,
            external_literature=entry.literature if entry else None, external_doi=entry.doi if entry else None,
            external_comparison=external_comparison, external_sentence_id=sentence_id,
            external_sentence=loaded.sentences[sentence_id].format(domain=metric.title, ours=ours, reference=reference) if entry else None,
            notice_id=notice_id, notice=loaded.sentences[notice_id].format(domain=metric.title) if notice_id else None))
    counts = {}
    for item in doc.exclusions:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    return CumulativePublicV4(reference=pointer, mapping_version=doc.mapping_version, mapping_hash=doc.mapping_hash, cutoff=doc.recorded_at,
        as_of=local_date(doc.recorded_at), included_pairs=len(doc.members), exclusion_counts=counts, label=loaded.cumulative_label,
        note=loaded.cumulative_note, external_limitation=loaded.external_limitation, rows=tuple(rows))
