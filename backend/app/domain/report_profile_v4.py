"""Renderer-ready S1 content; facts, claims and actual scene references stay separate."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator

from .catalog_v4 import ContractV4, Hash, ItemCode, Text
from .contracts_v4 import EvidenceV4
from .final_results_v4 import FinalReferenceV4
from .results_v4 import ResultReferenceV4
from .preprocess_v4 import FileV4
from .sheets_v4 import BatchPointerV4, InputPointerV4, SheetReferenceV4
from .comparisons_v4 import ExternalPublicV4
from ..survey_v4 import SurveyResultV4

CONTENT_VERSION = "report-content-20261002-s1.1-1"
SELECTION_VERSION = "report-scenes-20261002-s1.1-1"


class FactV4(ContractV4):
    fact_id: Text
    kind: Literal["observation", "metric", "final_type", "opinion", "ai_judgement", "survey", "recorded_event", "policy"]
    value: int | float | str | None
    unit: Text | None = None
    label: Text | None = None
    item_codes: tuple[ItemCode, ...] = ()
    evidence: tuple[EvidenceV4, ...] = ()
    source_refs: tuple[Text, ...]


class ClaimV4(ContractV4):
    claim_id: Text
    text: Text
    fact_ids: tuple[Text, ...]
    validation: Literal["source_verified", "human_verbatim"] = "source_verified"


class ReportCardV4(ContractV4):
    key: Literal["education_attitude", "attachment", "social", "walking"]
    title: Text
    status: Literal["available", "partial", "insufficient", "held"]
    label: Text | None = None
    claims: tuple[ClaimV4, ...]


class ReportSectionV4(ContractV4):
    key: Text
    title: Text
    status: Literal["available", "partial", "insufficient", "held"]
    claims: tuple[ClaimV4, ...]


class SceneV4(ContractV4):
    scene_id: Text
    common_event_id: Text
    domain: Text
    title: Text
    claims: tuple[ClaimV4, ...]
    evidence: Annotated[tuple[EvidenceV4, ...], Field(min_length=1)]
    reference_start_seconds: Annotated[float, Field(ge=0)]
    reference_end_seconds: Annotated[float, Field(ge=0)]
    priority: Literal["completed_opinion", "before_after", "domain_diversity", "chronological"]


class SceneReviewV4(ContractV4):
    candidate_id: Text
    reason: Text
    evidence: tuple[EvidenceV4, ...] = ()


class SurveyComparisonV4(ContractV4):
    key: Text
    title: Text
    survey_fact_ids: tuple[Text, ...]
    video_fact_ids: tuple[Text, ...]
    claims: tuple[ClaimV4, ...]
    direct_video_task: bool


class ValidationIssueV4(ContractV4):
    code: Text
    target: Text
    reason: Text
    blocking: bool


class ReportSourceV4(ContractV4):
    final: FinalReferenceV4
    basic: ResultReferenceV4
    sheet: SheetReferenceV4
    input: InputPointerV4
    batch: BatchPointerV4 | None
    survey: SurveyResultV4
    asset_hashes: dict[str, Hash]
    common_events_hash: Hash
    event_sources: tuple[FileV4, ...] = ()


class TimelineIntervalV4(ContractV4):
    key: Text
    kind: Literal["segment", "walk_phase"]
    video_id: Text
    camera_id: Text
    video_sha256: Hash
    state: Literal["performed", "shortened", "not_performed", "welfare_stopped"]
    source_start_seconds: float | None
    source_end_seconds: float | None
    reference_start_seconds: float | None
    reference_end_seconds: float | None
    reason: Text | None = None


class ReportProfileV4(ContractV4):
    profile_id: Text
    case_id: Text
    session_id: Text
    content_version: Literal["report-content-20261002-s1.1-1"] = CONTENT_VERSION
    selection_version: Literal["report-scenes-20261002-s1.1-1"] = SELECTION_VERSION
    source: ReportSourceV4
    source_hash: Hash
    timeline: tuple[TimelineIntervalV4, ...] = ()
    status: Literal["ready", "partial", "review_required"]
    cards: tuple[ReportCardV4, ...]
    facts: tuple[FactV4, ...]
    scenes: Annotated[tuple[SceneV4, ...], Field(max_length=3)]
    scene_notice: Text | None = None
    scene_review: tuple[SceneReviewV4, ...] = ()
    comparisons: tuple[SurveyComparisonV4, ...]
    details: tuple[ReportSectionV4, ...]
    summary: tuple[ClaimV4, ...]
    actions: Annotated[tuple[ClaimV4, ...], Field(max_length=3)]
    actions_notice: Text | None = None
    validation_issues: tuple[ValidationIssueV4, ...] = ()
    sentence_bank_status: Literal["pending_G02"] = "pending_G02"
    provider_text_status: Literal["deferred_S16"] = "deferred_S16"
    external_comparison_status: Literal["pending_D06", "approved_selected"] = "pending_D06"
    external_comparison: ExternalPublicV4 | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def renderer_contract(self) -> Self:
        if (self.external_comparison is not None) != (self.external_comparison_status == "approved_selected"):
            raise ValueError("external comparison status requires its explicitly selected snapshot")
        if self.external_comparison and (self.external_comparison.target.case_id, self.external_comparison.target.session_id,
                self.external_comparison.target.input) != (self.case_id, self.session_id, self.source.input):
            raise ValueError("external comparison belongs to another report survey input")
        if tuple(card.key for card in self.cards) != ("education_attitude", "attachment", "social", "walking"):
            raise ValueError("S1 reports contain exactly the four confirmed result cards")
        ids = {fact.fact_id for fact in self.facts}
        if len(ids) != len(self.facts):
            raise ValueError("duplicate report fact")
        claims = [*self.summary, *self.actions, *[claim for section in (*self.cards, *self.details, *self.scenes, *self.comparisons) for claim in section.claims]]
        if any(not set(claim.fact_ids) <= ids for claim in claims):
            raise ValueError("claim refers to an unknown pinned fact")
        if any(issue.blocking for issue in self.validation_issues) and self.status != "review_required":
            raise ValueError("unresolved content errors cannot be issued as normal output")
        return self
