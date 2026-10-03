"""S1 raw observations, provenance and decisions; no old-score compatibility."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .catalog_v4 import (AUTO_CODES, CATALOG_VERSION, COUNT_CODES, ContractV4, Hash,
                         ItemCode, MEMO_CODES, PROTOCOL_VERSION, SCORING_VERSION, Text)

Seconds = Annotated[float, Field(ge=0)]
OWNER_TYPES = ("허용형", "조율형", "통제형")
ATTACHMENT_TYPES = ("곁에서 안심하는 사이", "가까이 있어도 안심이 어려운 사이",
                    "거리를 두고 지내는 사이", "다가감과 물러섬이 함께 나오는 사이")


class EvidenceV4(ContractV4):
    video_id: Text
    video_sha256: Hash
    camera_id: Text
    window_id: Text
    start_seconds: Seconds
    end_seconds: Seconds
    observed_seconds: Seconds
    note: Text

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_seconds < self.start_seconds or self.observed_seconds > self.end_seconds - self.start_seconds:
            raise ValueError("evidence duration must be within the source interval")
        return self


class VocalizationV4(ContractV4):
    listened_seconds: Annotated[float, Field(gt=0)]
    cumulative_vocal_seconds: Seconds
    whole_interval_judged: bool
    note: Text

    @model_validator(mode="after")
    def valid_amount(self) -> Self:
        if self.cumulative_vocal_seconds > self.listened_seconds:
            raise ValueError("vocal amount exceeds listening duration")
        return self


class ObservationV4(ContractV4):
    code: ItemCode
    value: int | str | None
    status: Literal["observed", "unobserved", "no_opportunity", "not_performed", "invalid",
                    "insufficient_observation", "policy_pending"]
    reason: Text | None = None
    opportunity: Literal["present", "absent", "unknown"] = "unknown"
    validity: Literal["valid", "caution", "invalid", "unknown"] = "unknown"
    whole_interval_observed: bool = False
    evidence: tuple[EvidenceV4, ...] = ()
    vocalization: VocalizationV4 | None = None
    review_memo: str | None = None

    @model_validator(mode="after")
    def state_and_value(self) -> Self:
        if self.code in AUTO_CODES:
            raise ValueError("automatic S1 rows cannot be entered")
        if self.status == "observed":
            if self.value is None or self.validity in ("invalid", "unknown") or self.opportunity == "absent":
                raise ValueError("observed needs a value and valid/caution observation")
            if self.code in MEMO_CODES:
                if not isinstance(self.value, str) or not self.value.strip():
                    raise ValueError("memo requires nonblank text")
            elif type(self.value) is not int:
                raise ValueError("numeric S1 input requires an integer, not text or boolean")
            elif self.code in COUNT_CODES and self.value < 0:
                raise ValueError("count cannot be negative")
        elif self.value is not None or self.reason is None:
            raise ValueError("non-observed states require null and a reason; null is not zero")
        if self.status == "no_opportunity" and self.opportunity != "absent":
            raise ValueError("no_opportunity requires absent opportunity")
        if self.status == "invalid" and self.validity != "invalid":
            raise ValueError("invalid state requires invalid validity")
        return self


class WalkPhaseV4(ContractV4):
    code: Literal["개38", "개39", "개40", "개41", "개42", "개43"]
    proximity_exception: Literal["none", "guardian_approach", "recheck", "unknown"]
    evidence: tuple[EvidenceV4, ...] = ()
    note: str | None = None


class LinkedMemoV4(ContractV4):
    code: Literal["개59"] = "개59"
    text: Text
    item_codes: tuple[ItemCode, ...]
    evidence: tuple[EvidenceV4, ...] = ()


class ScoreSheetV4(ContractV4):
    sheet_id: Text
    case_id: Text
    session_id: Text
    batch_id: Text
    catalog_version: Literal["catalog-20261002-s1.1"] = CATALOG_VERSION
    protocol_version: Literal["protocol-20261002-s1.1"] = PROTOCOL_VERSION
    scoring_version: Literal["scoring-20261002-s1.1-app-1"] = SCORING_VERSION
    rater_id: Text
    rater_kind: Literal["ai", "human"]
    ai_exposed: bool = False
    input_revision: Annotated[int, Field(ge=1)]
    input_sha256: Hash
    observations: tuple[ObservationV4, ...]
    walk_phases: tuple[WalkPhaseV4, ...] = ()
    linked_memos: tuple[LinkedMemoV4, ...] = ()

    @model_validator(mode="after")
    def unique_rows(self) -> Self:
        for records in (self.observations, self.walk_phases):
            if len({record.code for record in records}) != len(records):
                raise ValueError("duplicate S1 item/phase")
        return self


class DerivedValueV4(ContractV4):
    key: Text
    value: int | float | str | None
    status: Literal["calculated", "missing", "invalid", "condition_unknown", "policy_pending"]
    reason: Text | None = None
    input_codes: tuple[ItemCode, ...]
    rule_version: Literal["scoring-20261002-s1.1-app-1"] = SCORING_VERSION

    @model_validator(mode="after")
    def value_state(self) -> Self:
        if self.key in ("V", "AW", "AY", "개32"):
            raise ValueError("retired derived result is not an S1 result")
        if self.status == "calculated" and self.value is None:
            raise ValueError("calculated requires a value")
        if self.status != "calculated" and (self.value is not None or self.reason is None):
            raise ValueError("uncomputed result requires null and a reason")
        if len(set(self.input_codes)) != len(self.input_codes):
            raise ValueError("duplicate result input")
        return self


class DecisionV4(ContractV4):
    key: Literal["owner_type", "attachment_type"]
    label: Text | None
    status: Literal["draft", "complete", "held"]
    evidence_codes: tuple[ItemCode, ...]
    evidence: tuple[EvidenceV4, ...]
    counter_evidence: tuple[EvidenceV4, ...] = ()
    counter_codes: tuple[ItemCode, ...] = ()
    counter_note: Text | None = None
    reason: Text
    rater_id: Text
    input_sheet_id: Text
    input_revision: Annotated[int, Field(ge=1)]
    input_sha256: Hash
    rule_version: Literal["scoring-20261002-s1.1-app-1"] = SCORING_VERSION

    @model_validator(mode="after")
    def allowed_type(self) -> Self:
        names = OWNER_TYPES if self.key == "owner_type" else ATTACHMENT_TYPES
        if self.status == "held":
            if self.label is not None:
                raise ValueError("held is a state, not an additional type")
        elif self.label not in names:
            raise ValueError("unknown S1 type name")
        if self.status == "complete" and (not self.evidence_codes or not self.evidence):
            raise ValueError("complete decision requires traceable item and scene evidence")
        if len(set(self.evidence_codes)) != len(self.evidence_codes):
            raise ValueError("duplicate decision evidence")
        if len(set(self.counter_codes)) != len(self.counter_codes) or not set(self.counter_codes) <= set(self.evidence_codes):
            raise ValueError("counter codes must be unique selected evidence codes")
        return self
