"""Source-defined survey means; partial-response and eligibility decisions stay pending."""

from typing import Literal

from app.domain.catalog_v3 import SURVEY_VERSION, SurveyCatalogV3
from app.input_models import Model
from app.input_models_v3 import SessionV3


class SurveyValueV3(Model):
    item_id: str
    raw: int | None
    converted: int | None
    blank_reason: str | None


class SurveyDomainV3(Model):
    domain: str
    question_ids: list[str]
    target_count: int
    answered_count: int
    numerator: int | None
    denominator: int | None
    mean: float | None
    status: Literal["calculated", "pending_partial", "insufficient_responses", "missing"]
    reason: str | None


class SurveyResultV3(Model):
    schema_version: Literal["3.0"] = "3.0"
    survey_version: Literal["survey-20260929-v3"] = SURVEY_VERSION
    session_id: str
    status: Literal["calculated", "partial", "unregistered"]
    answered_count: int
    blank_reason_count: int
    registration_status: Literal["unregistered", "partial", "all_answered", "answers_or_reasons_recorded"]
    registration_complete: None = None  # Q04 has not defined final completion criteria.
    comparison_status: Literal["pending_policy", "insufficient_responses"]
    domains: list[SurveyDomainV3]
    standalone: SurveyValueV3
    items: list[SurveyValueV3]
    pending_policies: list[str]


def survey_scores_v3(session: SessionV3, catalog: SurveyCatalogV3) -> SurveyResultV3:
    # Revalidate mutable session fields before calculating from stored inputs.
    session = SessionV3.model_validate_json(session.model_dump_json())
    if session.survey_version != catalog.version:
        raise ValueError("survey and catalog editions differ")
    values = [SurveyValueV3(item_id=q.item_id, raw=session.survey[q.item_id],
              converted=None if session.survey[q.item_id] is None else 6 - session.survey[q.item_id] if q.reverse_scored else session.survey[q.item_id],
              blank_reason=session.survey_blank_reasons.get(q.item_id)) for q in catalog.items]
    by_id = {value.item_id: value for value in values}
    groups = {}
    for q in catalog.items:
        if not q.standalone:
            groups.setdefault(q.report_domain, []).append(q.item_id)
    domains = []
    for domain, ids in groups.items():
        present = [by_id[item].converted for item in ids if by_id[item].converted is not None]
        complete = len(present) == len(ids)
        required_complete = ids in (["s07", "s08", "s09"], ["s10", "s11"], ["s12", "s13", "s14"])
        domains.append(SurveyDomainV3(domain=domain, question_ids=ids, target_count=len(ids), answered_count=len(present),
            numerator=sum(present) if complete else None, denominator=len(ids) if complete else None,
            mean=sum(present) / len(ids) if complete else None,
            status="calculated" if complete else "missing" if not present else "insufficient_responses" if required_complete else "pending_partial",
            reason=None if complete else "응답 없음" if not present else "원본 완전응답 규칙: 모든 문항 응답 필요" if required_complete else "Q04 부분응답 집계 정책 미확정"))
    count = sum(value.raw is not None for value in values)
    reasons = len(session.survey_blank_reasons)
    fear_complete = all(by_id[f"s{i:02}"].raw is not None for i in range(10, 15))
    return SurveyResultV3(session_id=session.session_id,
        status="calculated" if count == 28 else "partial" if count or reasons else "unregistered",
        answered_count=count, blank_reason_count=reasons,
        registration_status="all_answered" if count == 28 else "answers_or_reasons_recorded" if count + reasons == 28 else "partial" if count or reasons else "unregistered",
        comparison_status="pending_policy" if fear_complete else "insufficient_responses", domains=domains,
        standalone=by_id["s25"], items=values, pending_policies=["Q04 부분응답 집계·등록 완료 기준", "Q10 비교 대상 자격"])
