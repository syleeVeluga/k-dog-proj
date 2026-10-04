"""S1 calculations and immutable basic decisions with explicit input provenance."""

from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .catalog_v4 import ContractV4, Hash, ItemCode, SCORING_VERSION, Text
from .contracts_v4 import DecisionV4, EvidenceV4, ObservationV4
from .media_v4 import MediaKey
from .disclosures_v4 import InterpretationExposureV4
from .recording_v4 import SafeBaseResultV4
from .sheets_v4 import SheetDocumentV4, SheetReferenceV4


class MetricV4(ContractV4):
    key: Text
    value: int | float | str | None = None
    status: Literal["calculated", "missing", "invalid", "condition_unknown", "policy_pending"]
    reason: Text
    inputs: tuple[ObservationV4, ...] = ()
    used_codes: tuple[ItemCode, ...] = ()
    excluded: dict[ItemCode, Text] = {}
    numerator: int | float | None = None
    denominator: int | float | None = None
    caution: bool = False
    internal_only: bool = False

    @model_validator(mode="after")
    def value_state(self) -> Self:
        if (self.status == "calculated") != (self.value is not None):
            raise ValueError("only a calculated metric has a value")
        if self.key in ("V", "AW", "AY", "개32"):
            raise ValueError("retired S1 calculation")
        return self


class OwnerPointsV4(ContractV4):
    code: ItemCode
    value: int | None
    scene: Text
    points: tuple[int, int, int] | None
    used: bool
    reason: Text
    used_evidence: tuple[EvidenceV4, ...] = ()


class OwnerCalculationV4(ContractV4):
    items: tuple[OwnerPointsV4, ...]
    inputs: tuple[ObservationV4, ...]
    scene_means: dict[str, tuple[float, float, float]]
    totals: tuple[float, float, float]
    ratios: tuple[float, float, float] | None
    valid_items: int
    valid_scenes: int
    label: Literal["허용형", "조율형", "통제형"] | None
    status: Literal["dominant", "held", "insufficient"]
    reason: Text


class CalculationsV4(ContractV4):
    rule_version: Literal["scoring-20261002-s1.1-app-1"] = SCORING_VERSION
    metrics: tuple[MetricV4, ...]
    owner: OwnerCalculationV4
    safe_base: SafeBaseResultV4
    policy_pending_codes: tuple[ItemCode, ...] = ("보5", "개21")


class CalculationConditionsV4(ContractV4):
    same_object: bool | None = None
    same_object_reason: Text | None = None

    @model_validator(mode="after")
    def accountable_condition(self) -> Self:
        if self.same_object is not None and self.same_object_reason is None:
            raise ValueError("same-object confirmation needs its observation basis")
        return self


class EvaluationContextV4(ContractV4):
    purpose: Literal["independent", "review", "consensus"]
    ai_exposed: bool
    exposures: tuple[SheetReferenceV4, ...] = ()
    interpretation_exposures: tuple[InterpretationExposureV4, ...] = ()

    @model_validator(mode="after")
    def exposure(self) -> Self:
        if (self.exposures or self.interpretation_exposures or self.ai_exposed) and self.purpose == "independent":
            raise ValueError("exposed results cannot claim independent evaluation")
        return self


class AudioSourceV4(ContractV4):
    video_sha256: Hash
    duration_sec: Annotated[float, Field(gt=0)]
    audio_ranges: tuple[tuple[float, float], ...]
    audio_status: Literal["present", "absent"]


class ResultReferenceV4(ContractV4):
    result_id: MediaKey
    revision: Annotated[int, Field(ge=1)]
    ref: Annotated[str, Field(pattern=r"^results/[^\\]+\.json$")]
    hash: Hash


class BasicResultV4(ContractV4):
    result_id: MediaKey
    case_id: MediaKey
    session_id: MediaKey
    revision: Annotated[int, Field(ge=1)]
    actor: Text
    recorded_at: Text
    change_reason: Text
    input: SheetReferenceV4
    input_document: SheetDocumentV4
    rule_version: Literal["scoring-20261002-s1.1-app-1"] = SCORING_VERSION
    rule_hash: Hash
    rule_snapshot: dict
    conditions: CalculationConditionsV4
    audio_sources: dict[str, AudioSourceV4] = {}
    evaluation_context: EvaluationContextV4
    calculations: CalculationsV4
    automatic_decisions: tuple[DecisionV4, ...]
    manual_decisions: tuple[DecisionV4, ...] = ()
    decisions: tuple[DecisionV4, ...]
    decision_sources: dict[str, Literal["automatic", "human", "ai"]]
    previous: tuple[ResultReferenceV4, ...] = ()

    @model_validator(mode="after")
    def pinned_identity(self) -> Self:
        doc = self.input_document
        if (self.input.sheet_id, self.input.revision, self.case_id, self.session_id) != (doc.sheet.sheet_id, doc.revision, doc.sheet.case_id, doc.sheet.session_id):
            raise ValueError("result and pinned input differ")
        if self.rule_hash != doc.source.asset_hashes["scoring"] or self.rule_snapshot.get("version") != self.rule_version:
            raise ValueError("result and source scoring rule pins differ")
        expected = (self.input.sheet_id, self.input.revision, self.input.hash, self.rule_version)
        for decision in (*self.decisions, *self.automatic_decisions, *self.manual_decisions):
            if (decision.input_sheet_id, decision.input_revision, decision.input_sha256, decision.rule_version) != expected:
                raise ValueError("decision and result pins differ")
        keys = {"owner_type", "attachment_type"}
        if len({item.key for item in self.manual_decisions}) != len(self.manual_decisions):
            raise ValueError("duplicate manual decision")
        if any(len(values) != 2 or {item.key for item in values} != keys for values in (self.decisions, self.automatic_decisions)) or set(self.decision_sources) != keys:
            raise ValueError("both basic decisions and origins must be explicit")
        if any(item.result_id != self.result_id or item.revision >= self.revision for item in self.previous):
            raise ValueError("result history must belong to earlier revisions")
        if len({item.revision for item in self.previous}) != len(self.previous):
            raise ValueError("duplicate result revision")
        return self
