"""V3 raw observations and decisions; provisional Q01 names are internal only."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import Hash, Identifier, Text, require_unique
from .catalog_v3 import CATALOG_VERSION, ContractV3, ItemCode, PROTOCOL_VERSION

Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class EvidenceV3(ContractV3):
    video_id: Identifier
    video_sha256: Hash
    window_id: Text
    start_seconds: Seconds
    end_seconds: Seconds
    observed_seconds: Seconds
    note: Text
    scoring_exclusion: Literal["none", "welfare_action", "staff_stop_action", "object_instruction"] = "none"

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_seconds < self.start_seconds or self.observed_seconds > self.end_seconds - self.start_seconds:
            raise ValueError("evidence time range or observed duration is invalid")
        return self


class VocalizationV3(ContractV3):
    video_id: Identifier
    listened_seconds: Seconds
    cumulative_vocal_seconds: Seconds
    whole_interval_judged: bool
    note: Text

    @model_validator(mode="after")
    def amount(self) -> Self:
        if self.cumulative_vocal_seconds > self.listened_seconds:
            raise ValueError("vocal seconds cannot exceed actual listening")
        return self


class ObservationV3(ContractV3):
    code: ItemCode
    value: int | float | str | None
    status: Literal["observed", "unobserved", "no_opportunity", "not_performed"]
    reason: Text | None = None
    opportunity: Literal["present", "absent", "unknown"] = "unknown"
    validity: Literal["valid", "caution", "invalid", "unknown"] = "unknown"
    welfare_stopped: bool = False
    evidence: tuple[EvidenceV3, ...] = ()
    # 개32=99 is a sentinel, never an observed latency of 99 seconds.
    latency_not_occurred: bool = False
    actual_latency_seconds: Seconds | None = None
    vocalization: VocalizationV3 | None = None

    @model_validator(mode="after")
    def state_and_value(self) -> Self:
        if self.status == "observed":
            if self.value is None:
                raise ValueError("observed requires a raw value; zero is not blank")
        elif self.value is not None or self.reason is None:
            raise ValueError("missing observations need a reason and no value")
        if self.status == "no_opportunity" and self.opportunity != "absent":
            raise ValueError("no_opportunity requires absent opportunity")
        if self.status == "observed" and self.opportunity == "absent":
            raise ValueError("an observed value cannot have absent opportunity")
        if self.code == "개32" and self.status == "observed":
            if self.value == 99:
                if not self.latency_not_occurred or self.actual_latency_seconds is not None:
                    raise ValueError("raw 99 requires not-occurred sentinel and no actual latency")
            elif self.latency_not_occurred or self.actual_latency_seconds != self.value:
                raise ValueError("actual latency must preserve the raw seconds without rounding")
        elif self.latency_not_occurred or self.actual_latency_seconds is not None:
            raise ValueError("latency metadata belongs to observed 개32 only")
        if self.vocalization is not None and self.code not in ("바6", "개11", "개47", "개48", "개49", "개50"):
            raise ValueError("listening/vocal amounts belong to the six vocalization rows only")
        return self


class ScoreSheetV3(ContractV3):
    sheet_id: Identifier
    case_id: Identifier
    session_id: Identifier
    catalog_version: Literal["catalog-20260929-v3"] = CATALOG_VERSION
    protocol_version: Literal["protocol-20260929-v3"] = PROTOCOL_VERSION
    rater_id: Identifier
    rater_kind: Literal["ai", "human"]
    ai_exposed: bool = False
    observations: tuple[ObservationV3, ...]

    @model_validator(mode="after")
    def unique_codes(self) -> Self:
        require_unique(tuple(item.code for item in self.observations), "observation code")
        return self


class DerivedValueV3(ContractV3):
    key: Text
    value: float | None
    status: Literal["calculated", "missing", "invalid", "condition_unknown", "policy_pending"]
    reason: Text | None = None
    input_codes: tuple[ItemCode, ...]

    @model_validator(mode="after")
    def value_state(self) -> Self:
        if self.status == "calculated":
            if self.value is None:
                raise ValueError("calculated needs a value")
        elif self.value is not None or self.reason is None:
            raise ValueError("uncomputed values need a reason and no value")
        require_unique(self.input_codes, "derived input")
        return self


class DecisionV3(ContractV3):
    key: Text
    label: Text | None
    status: Literal["draft", "complete", "held"]
    evidence_codes: tuple[ItemCode, ...]
    evidence: tuple[EvidenceV3, ...]
    counter_evidence: tuple[EvidenceV3, ...] = ()
    counter_note: Text | None = None
    opportunity_note: Text
    reason: Text
    rater_id: Identifier
    recorded_at: Text
    input_sheet_id: Identifier
    input_revision: Annotated[int, Field(ge=1)]
    input_sha256: Hash
    rule_version: Text

    @model_validator(mode="after")
    def completeness(self) -> Self:
        if self.status == "complete" and (self.label is None or not self.evidence_codes or not self.evidence):
            raise ValueError("complete decision requires a label and traceable evidence")
        if self.status == "held" and self.label is not None:
            raise ValueError("held is a decision state, not a fifth type")
        require_unique(self.evidence_codes, "decision evidence code")
        return self
