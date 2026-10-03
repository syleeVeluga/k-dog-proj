"""Pinned same-edition cohorts and separately attested research/technical gates."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator

from .catalog_v4 import ContractV4, Hash, Text
from .preprocess_v4 import FileV4
from .sheets_v4 import InputPointerV4
from ..survey_v4 import SurveyResultV4

POLICY_VERSION = "comparison-20261002-s1.1-1"
SurveyEdition = Literal["survey-20260929-v3"]
SurveyPolicy = Literal["survey-policy-20261002-s1.1"]
Finite = Annotated[float,Field(allow_inf_nan=False)]
Count = Annotated[int,Field(ge=0)]
Revision = Annotated[int,Field(ge=1)]


class CohortSelectionV4(ContractV4):
    case_id: Text
    session_id: Text
    expected_revision: Revision
    input: InputPointerV4


class CohortMemberV4(ContractV4):
    case_id: Text
    session_id: Text
    input_revision: Revision
    input: InputPointerV4
    survey: SurveyResultV4


class CohortDomainV4(ContractV4):
    domain: Text
    question_ids: tuple[Text,...]
    scale_minimum: int
    scale_maximum: int
    mean: Finite | None
    n: Count
    sum_values: Finite | None
    included_case_ids: tuple[Text,...]
    excluded: dict[str,str]

    @model_validator(mode="after")
    def population(self) -> Self:
        if self.n != len(self.included_case_ids) or len(set(self.included_case_ids))!=self.n:
            raise ValueError("cohort n counts distinct included cases")
        if bool(self.n) != (self.mean is not None and self.sum_values is not None):
            raise ValueError("empty cohort has null mean, never zero")
        if self.mean is not None and not self.scale_minimum<=self.mean<=self.scale_maximum:
            raise ValueError("cohort mean outside original response scale")
        return self


class CohortReferenceV4(FileV4):
    snapshot_id: Text
    revision: Literal[1] = 1


class CohortSnapshotV4(ContractV4):
    artifact_kind: Literal["comparison-cohort"] = "comparison-cohort"
    snapshot_id: Text
    revision: Literal[1] = 1
    title: Text
    actor: Text
    recorded_at: Text
    reason: Text
    policy_version: Literal["comparison-20261002-s1.1-1"] = POLICY_VERSION
    survey_version: SurveyEdition = "survey-20260929-v3"
    survey_policy: SurveyPolicy = "survey-policy-20261002-s1.1"
    asset_hashes: dict[str,Hash]
    selection_policy: Literal["one_case_one_explicit_session"] = "one_case_one_explicit_session"
    identity_limitation: Text = "case_id 기준으로 중복을 차단합니다. 다른 행사에 등록된 동일 개체의 전역 ID는 확인되지 않아 이름으로 추정·병합하지 않습니다."
    members: Annotated[tuple[CohortMemberV4,...],Field(min_length=1)]
    domains: tuple[CohortDomainV4,...]

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if len({member.case_id for member in self.members})!=len(self.members):
            raise ValueError("one case may contribute only one explicitly selected session")
        return self


class CohortPublicDomainV4(ContractV4):
    domain: Text
    question_ids: tuple[Text,...]
    scale_minimum: int
    scale_maximum: int
    mean: Finite | None
    n: Count
    excluded_count: Count
    exclusion_reasons: dict[str,Count]


class CohortPublicV4(ContractV4):
    reference: CohortReferenceV4
    title: Text
    survey_version: SurveyEdition = "survey-20260929-v3"
    survey_policy: SurveyPolicy = "survey-policy-20261002-s1.1"
    domains: tuple[CohortPublicDomainV4,...]
    selection_count: Count
    selection_note: Text
    interpretation_note: Text = "명시한 동일 판본 자체 집단의 실제 평균과 영역별 유효 n입니다. 전국 규준·백분위·진단값이 아닙니다."


class ComparisonScopeV4(ContractV4):
    measurement: Literal["self_report_survey"] = "self_report_survey"
    survey_version: Text
    policy_version: Text
    domain: Text
    question_ids: Annotated[tuple[Text,...],Field(min_length=1)]
    question_text_hash: Hash
    scale_minimum: int
    scale_maximum: int
    direction: Text
    aggregation: Text
    missing_policy: Text
    population_requirements: dict[str,str] = {}


class ResearchCheckV4(ContractV4):
    status: Literal["confirmed","pending","rejected"]
    note: Text
    evidence_location: Text


class ResearchReviewV4(ContractV4):
    source_id: Text
    source_asset_hash: Hash
    confirmed_by: Text
    confirmed_at: Text
    evidence: Annotated[tuple[FileV4,...],Field(min_length=1)]
    scope: ComparisonScopeV4
    numerical_table: ResearchCheckV4
    question_equivalence: ResearchCheckV4
    scale_direction: ResearchCheckV4
    missing_policy: ResearchCheckV4
    translation_usage: ResearchCheckV4
    population_scope: ResearchCheckV4
    reason: Text

    @model_validator(mode="after")
    def meaningful_confirmation(self) -> Self:
        if any(not value.strip() for value in (self.confirmed_by,self.confirmed_at,self.reason)):
            raise ValueError("research confirmation needs an identified confirmer, date and reason")
        for key in ("numerical_table","question_equivalence","scale_direction","missing_policy","translation_usage","population_scope"):
            check=getattr(self,key)
            if not check.note.strip() or not check.evidence_location.strip():
                raise ValueError("each research check needs its supporting location and assessment")
        return self


class ResearchConfirmationV4(ResearchReviewV4):
    artifact_kind: Literal["comparison-research"] = "comparison-research"
    confirmation_id: Text
    revision: Revision
    actor: Text
    recorded_at: Text


class ResearchReferenceV4(FileV4):
    confirmation_id: Text
    revision: Revision


class TechnicalActivationV4(ContractV4):
    source_id: Text
    revision: Revision
    actor: Text
    recorded_at: Text
    enabled: bool
    confirmation: ResearchReferenceV4 | None
    reason: Text


class ExternalValuesV4(ContractV4):
    mean: Finite
    standard_deviation: Annotated[float,Field(ge=0,allow_inf_nan=False)]
    valid_n: Annotated[int,Field(ge=1)]
    total_n: Annotated[int,Field(ge=1)]

    @model_validator(mode="after")
    def sample_sizes(self) -> Self:
        if self.valid_n>self.total_n:raise ValueError("subscale valid n cannot exceed total study n")
        return self


class ExternalGateV4(ContractV4):
    source_id: Text
    status: Literal["blocked","approved"]
    reason: Text
    scope: ComparisonScopeV4 | None = None
    confirmation: ResearchReferenceV4 | None = None
    activation_revision: Revision | None = None
    values: ExternalValuesV4 | None = None

    @model_validator(mode="after")
    def no_blocked_numbers(self) -> Self:
        if self.status=="blocked" and any(value is not None for value in (self.values,self.scope,self.confirmation,self.activation_revision)):
            raise ValueError("blocked external comparison exposes no values or approved scope")
        if self.status=="approved" and any(value is None for value in (self.values,self.scope,self.confirmation,self.activation_revision)):
            raise ValueError("approved comparison must pin both research and technical activation")
        return self
