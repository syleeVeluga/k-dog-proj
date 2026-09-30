"""Pinned basic calculations and judgement revisions, separate from event opinions."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.domain.base import Hash, Identifier, Text, require_unique
from app.domain.catalog_v3 import ContractV3, ItemCode
from app.domain.contracts_v3 import DecisionV3, DerivedValueV3, EvidenceV3, ObservationV3, Seconds
from app.domain.sheets_v3 import SheetDocumentV3, SheetReferenceV3
from app.input_models import Key


class DirectionV3(ContractV3):
    key: Text
    raw_values: dict[ItemCode, int]
    negative_sum: int | None
    positive_sum: int | None
    observed_items: int
    status: Text
    actual_contact: bool | None


class TextCalculationV3(ContractV3):
    key: Text
    text: str | None
    status: Literal["calculated", "missing", "invalid", "condition_unknown", "policy_pending"]
    reason: str | None
    input_codes: tuple[ItemCode, ...]


class ExcludedEvidenceV3(ContractV3):
    evidence: EvidenceV3
    reason: Text
    event_ids: tuple[Identifier, ...] = ()


class OwnerPointsV3(ContractV3):
    code: ItemCode
    scene: Text
    raw_value: int | None
    points: tuple[int, int, int] | None
    used: bool
    reason: Text
    used_evidence: tuple[EvidenceV3, ...]
    excluded_evidence: tuple[ExcludedEvidenceV3, ...]


class OwnerCalculationV3(ContractV3):
    items: tuple[OwnerPointsV3, ...]
    scene_means: dict[str, tuple[float, float, float]]
    totals: tuple[float, float, float]
    ratios: tuple[float, float, float] | None
    evidence_items: int
    scenes: int
    label: str | None
    status: Literal["draft", "held"]
    reason: Text
    provisional: Literal[True] = True


class VocalCalculationV3(ContractV3):
    code: ItemCode
    actual_interval_seconds: float | None
    audio_available_seconds: float | None
    listened_seconds: float | None
    cumulative_vocal_seconds: float | None
    result: DerivedValueV3


class CalculationsV3(ContractV3):
    values: tuple[DerivedValueV3, ...]
    descriptions: tuple[TextCalculationV3, ...]
    directions: tuple[DirectionV3, ...]
    owner: OwnerCalculationV3
    vocalizations: tuple[VocalCalculationV3, ...]
    raw_observations: tuple[ObservationV3, ...]
    entry_label: str | None
    entry_reason: Text
    comparisons: dict[str, tuple[ObservationV3, ...]]


class AudioRangeV3(ContractV3):
    start_sec: Seconds
    end_sec: Seconds
    basis: Literal["stream_metadata", "container_fallback"]


class AudioSourceV3(ContractV3):
    video_sha256: Hash
    duration_sec: Seconds
    width: Annotated[int, Field(ge=1)]
    height: Annotated[int, Field(ge=1)]
    fps: str | None
    audio_ranges: tuple[AudioRangeV3, ...]
    audio_status: Literal["present", "absent"]


class EvaluationContextV3(ContractV3):
    purpose: Literal["independent", "review", "consensus"]
    ai_exposed: bool
    exposures: tuple[SheetReferenceV3, ...]

    @model_validator(mode="after")
    def exposed_purpose(self) -> Self:
        if (self.exposures or self.ai_exposed) and self.purpose == "independent":
            raise ValueError("exposed judgement is a review, never a new independent rating")
        return self


class ResultReferenceV3(ContractV3):
    result_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    ref: Annotated[str, Field(pattern=r"^results/[^\\]+\.json$")]
    hash: Hash


class BasicResultV3(ContractV3):
    result_id: Identifier
    case_id: Identifier
    session_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    actor: Key
    recorded_at: Text
    change_reason: Text
    input: SheetReferenceV3
    input_document: SheetDocumentV3
    rule_version: Text
    rule_hash: Hash
    audio_sources: dict[Identifier, AudioSourceV3] = {}
    evaluation_context: EvaluationContextV3
    calculations: CalculationsV3
    decisions: tuple[DecisionV3, ...]
    decision_sources: dict[str, Literal["automatic", "human", "ai"]]
    previous: tuple[ResultReferenceV3, ...] = ()

    @model_validator(mode="after")
    def pinned_identity(self) -> Self:
        doc = self.input_document
        if (self.input.sheet_id, self.input.revision, self.case_id, self.session_id) != (doc.sheet.sheet_id, doc.revision, doc.sheet.case_id, doc.sheet.session_id):
            raise ValueError("basic result and pinned sheet identity differ")
        if any((item.input_sheet_id, item.input_revision, item.input_sha256, item.rule_version) !=
               (self.input.sheet_id, self.input.revision, self.input.hash, self.rule_version) for item in self.decisions):
            raise ValueError("decision and basic result input differ")
        require_unique(tuple(item.key for item in self.decisions), "basic decision")
        if set(self.decision_sources) != {item.key for item in self.decisions}:
            raise ValueError("decision origins must be explicit")
        return self
