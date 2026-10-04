"""S1 survey aggregation: unchanged source responses, separately versioned policy."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .domain.catalog_v3 import SurveyCatalogV3
from .domain.catalog_v4 import (ContractV4, RESOURCES, SourceV4, SURVEY_POLICY_VERSION,
                                SURVEY_VERSION, Text)
from .input_models_v4 import SessionV4

QuestionId = Annotated[str, Field(pattern=r"^s(0[1-9]|1[0-9]|2[0-8])$")]
Count = Annotated[int, Field(ge=0, le=28)]


class SurveyGroupPolicyV4(ContractV4):
    question_ids: tuple[QuestionId, ...]
    aggregation: Literal["mean", "reverse_mean", "single_raw"]
    partial_status: Literal["insufficient_responses", "policy_pending", "missing"]


class SurveyPolicyV4(ContractV4):
    version: Literal["survey-policy-20261002-s1.1"] = SURVEY_POLICY_VERSION
    survey_version: Literal["survey-20260929-v3"] = SURVEY_VERSION
    source: SourceV4
    groups: tuple[SurveyGroupPolicyV4, ...]
    registration_completion: Literal["unconfirmed"]
    external_comparison: Literal["pending_D06"]

    @model_validator(mode="after")
    def source_groups(self) -> Self:
        ranges = ((1, 6), (7, 9), (10, 11), (12, 14), (15, 21), (22, 23), (24, 24), (25, 25), (26, 28))
        expected = tuple(tuple(f"s{n:02}" for n in range(a, b + 1)) for a, b in ranges)
        if tuple(group.question_ids for group in self.groups) != expected:
            raise ValueError("S1 survey groups must retain the source question boundaries")
        for group in self.groups:
            single = len(group.question_ids) == 1
            fear = group.question_ids[0] in ("s10", "s12")
            aggregation = "single_raw" if single else "reverse_mean" if group.question_ids[0] == "s26" else "mean"
            missing = "missing" if single else "insufficient_responses" if fear else "policy_pending"
            if (group.aggregation, group.partial_status) != (aggregation, missing):
                raise ValueError("S1 confirmed fear policy and pending D05 policy must remain distinct")
        return self


class SurveyValueV4(ContractV4):
    item_id: QuestionId
    raw: int | None
    converted: int | None
    reverse_scored: bool
    conversion: Literal["identity", "6-raw"]
    allowed_values: tuple[int, ...]
    status: Literal["answered", "missing"]
    blank_reason: Text | None


class SurveyDomainV4(ContractV4):
    domain: Text
    question_ids: tuple[QuestionId, ...]
    aggregation: Literal["mean", "reverse_mean", "single_raw"]
    target_count: Count
    answered_count: Count
    missing_question_ids: tuple[QuestionId, ...]
    numerator: int | None
    denominator: Annotated[int, Field(ge=1, le=28)] | None
    mean: float | None
    status: Literal["calculated", "policy_pending", "insufficient_responses", "missing"]
    reason: Text | None
    same_edition_value_available: bool


class SurveyResultV4(ContractV4):
    survey_version: Literal["survey-20260929-v3"] = SURVEY_VERSION
    policy_version: Literal["survey-policy-20261002-s1.1"] = SURVEY_POLICY_VERSION
    policy_source: SourceV4
    session_id: Text
    status: Literal["calculated", "partial", "unregistered"]
    calculation_status: Literal["complete", "partial", "unavailable"]
    answered_count: Count
    blank_reason_count: Count
    registration_status: Literal["unregistered", "partial", "all_answered", "answers_or_reasons_recorded"]
    registration_complete: None = None
    external_comparison_status: Literal["pending_approval"] = "pending_approval"
    external_comparison_reason: Text = "D06 원문 동등성·번안/사용 조건과 적용 범위 확인 대기"
    domains: tuple[SurveyDomainV4, ...]
    standalone: SurveyValueV4
    items: tuple[SurveyValueV4, ...]
    pending_policies: tuple[Text, ...]


def load_survey_policy_v4() -> SurveyPolicyV4:
    return SurveyPolicyV4.model_validate_json((RESOURCES / "rules/survey-policy-v4.json").read_bytes())


def survey_scores_v4(session: SessionV4, catalog: SurveyCatalogV3) -> SurveyResultV4:
    # Stored sessions contain mutable dictionaries; validate before reading them.
    if any(answer is not None and type(answer) is not int for answer in session.survey.values()):
        raise ValueError("survey answers must be raw integers or null, not coerced values")
    session = SessionV4.model_validate_json(session.model_dump_json())
    catalog = SurveyCatalogV3.model_validate(catalog)
    policy = load_survey_policy_v4()
    if session.survey_version != policy.survey_version or catalog.version != policy.survey_version:
        raise ValueError("S1 aggregation requires the original survey-20260929-v3 responses")
    values = tuple(SurveyValueV4(
        item_id=q.item_id, raw=session.survey[q.item_id],
        converted=None if session.survey[q.item_id] is None else
            6 - session.survey[q.item_id] if q.reverse_scored else session.survey[q.item_id],
        reverse_scored=q.reverse_scored, conversion="6-raw" if q.reverse_scored else "identity",
        allowed_values=q.allowed_values, status="missing" if session.survey[q.item_id] is None else "answered",
        blank_reason=session.survey_blank_reasons.get(q.item_id)) for q in catalog.items)
    by_id = {value.item_id: value for value in values}
    questions = {q.item_id: q for q in catalog.items}
    domains = []
    for group in policy.groups:
        ids = group.question_ids
        if ids == ("s25",):
            continue
        present = [by_id[item].converted for item in ids if by_id[item].converted is not None]
        missing = tuple(item for item in ids if by_id[item].converted is None)
        complete = not missing
        status = "calculated" if complete else "missing" if not present else group.partial_status
        reason = None if complete else "원응답 없음" if not present else (
            "확정 두려움 묶음 규칙: 하나라도 결측이면 해당 묶음 미산출" if status == "insufficient_responses"
            else "D05 부분 결측 산출 정책 미확정: 부분평균과 0 대체를 적용하지 않음")
        domains.append(SurveyDomainV4(
            domain=questions[ids[0]].report_domain, question_ids=ids, aggregation=group.aggregation,
            target_count=len(ids), answered_count=len(present), missing_question_ids=missing,
            numerator=sum(present) if complete else None, denominator=len(ids) if complete else None,
            mean=sum(present) / len(ids) if complete else None, status=status, reason=reason,
            same_edition_value_available=complete))
    count = sum(value.raw is not None for value in values)
    reasons = len(session.survey_blank_reasons)
    calculated = sum(domain.status == "calculated" for domain in domains) + (by_id["s25"].raw is not None)
    pending = ["등록 완료 기준 확인 대기", "D06 외부 비교 승인 대기"]
    if any(domain.status == "policy_pending" for domain in domains):
        pending.append("D05 비공포 묶음의 부분 결측 산출 정책 확인 대기")
    return SurveyResultV4(
        session_id=session.session_id, policy_source=policy.source,
        status="calculated" if count == 28 else "partial" if count or reasons else "unregistered",
        calculation_status="complete" if calculated == 9 else "partial" if calculated else "unavailable",
        answered_count=count, blank_reason_count=reasons,
        registration_status="all_answered" if count == 28 else "answers_or_reasons_recorded" if count + reasons == 28
            else "partial" if count or reasons else "unregistered",
        domains=tuple(domains), standalone=by_id["s25"], items=values, pending_policies=tuple(pending))
