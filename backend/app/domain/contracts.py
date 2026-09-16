"""42-item (2026-09-13) contracts: three-state item scores, rater sheets, 8-segment timing, survey answers and derived results.

Values must come from a rater or from `app.scoring`; nothing here asserts an assessment rule of its own.
"""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import Contract, Identifier, Nonnegative, Text, require_unique
from .catalog import BEHAVIOR_IDS, BehaviorId, DomainCode, SEGMENTS, SegmentId, SURVEY_IDS, SurveyId

ScoreStatus = Literal["scored", "unreadable", "not_applicable"]
# strict int rejects booleans, which Literal[1..5] would silently canonicalise to 1
Answer = Annotated[int, Field(ge=1, le=5)]
RaterKind = Literal["ai", "human"]
IndicatorKey = Literal["adaptation", "recovery", "stranger_calming", "sync_rate"]
INDICATOR_KEYS: tuple[IndicatorKey, ...] = ("adaptation", "recovery", "stranger_calming", "sync_rate")
TypeKey = Literal["attachment", "sociability_person"]
TYPE_LABELS: dict[TypeKey, tuple[str, ...]] = {
    "attachment": ("안정", "불안", "거리 둠", "일관되지 않음"),
    "sociability_person": ("편안·우호", "우호·들뜸", "담담·거리둠", "경계·긴장"),
}
# 01 §4: only these Korean names may appear; Ainsworth terms (secure/avoidant/…) are rejected by the whitelist.
DerivedStatus = Literal["calculated", "missing", "invalid"]
SurveyMeanDomain = Literal["A", "B", "C", "E"]
SeparationLabel = Literal["안정", "불안", "회피 쪽", "무덤덤"]


class StimulusMoments(Contract):
    """Manually observed event times; no pre/post window placement is implied."""

    entry: Nonnegative | None = None
    alone: Nonnegative | None = None
    stranger: Nonnegative | None = None
    reunion: Nonnegative | None = None


class ItemScore(Contract):
    item_id: BehaviorId
    score: Annotated[int, Field(ge=0)] | None
    status: ScoreStatus
    reason: Text | None = None

    @model_validator(mode="after")
    def three_states(self) -> Self:
        if self.status == "scored":
            if self.score is None:
                raise ValueError("scored requires a value; a blank is not 0")
        elif self.score is not None or self.reason is None:
            raise ValueError("unreadable and not_applicable carry no value and require a reason")
        return self


class Rater(Contract):
    rater_id: Identifier
    kind: RaterKind
    label: Text | None = None


class ScoreSheet(Contract):
    """One rater's entries for one pair; several sheets per pair are kept for agreement (ICC) analysis."""

    sheet_id: Identifier
    case_id: Identifier
    session_id: Identifier
    catalog_version: Text
    rater: Rater
    recorded_at: Text
    items: Annotated[tuple[ItemScore, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_items_and_timestamp(self) -> Self:
        require_unique(tuple(item.item_id for item in self.items), "sheet item")
        try:
            datetime.fromisoformat(self.recorded_at)
        except ValueError as error:
            raise ValueError("recorded_at must be ISO 8601") from error
        return self


class SegmentWindow(Contract):
    segment: SegmentId
    start_sec: Nonnegative
    end_sec: Nonnegative
    source: Literal["ai_proposed", "operator_draft", "operator_confirmed"]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_sec < self.start_sec:
            raise ValueError("segment end precedes start")
        if self.source == "operator_confirmed" and self.end_sec == self.start_sec:
            raise ValueError("confirmed segment must have positive duration")
        return self


class SessionSegments(Contract):
    """The eight procedure segments of one recording (01 §2). `confirmed()` tells whether an operator has fixed every window."""

    session_id: Identifier
    video_id: Identifier
    windows: tuple[SegmentWindow, ...]

    @model_validator(mode="after")
    def eight_ordered_windows(self) -> Self:
        if tuple(window.segment for window in self.windows) != tuple(segment for segment, _ in SEGMENTS):
            raise ValueError("windows must be the eight segments in procedure order")
        for earlier, later in zip(self.windows, self.windows[1:]):
            if later.start_sec < earlier.end_sec:
                raise ValueError("segments overlap")
        return self

    def confirmed(self) -> bool:
        return all(window.source == "operator_confirmed" for window in self.windows)


class SurveyAnswers(Contract):
    answers: dict[SurveyId, Answer | None]
    not_applicable: tuple[SurveyId, ...] = ()

    @model_validator(mode="after")
    def complete_and_consistent(self) -> Self:
        if set(self.answers) != set(SURVEY_IDS):
            raise ValueError("survey requires exactly s01 through s28; blanks use null")
        require_unique(self.not_applicable, "not_applicable item")
        if any(self.answers[item_id] is not None for item_id in self.not_applicable):
            raise ValueError("해당 없음 is a missing value, not a score")
        return self


class DomainSummary(Contract):
    domain: DomainCode
    target_count: Annotated[int, Field(gt=0)]
    scored_count: Annotated[int, Field(ge=0)]
    unreadable_count: Annotated[int, Field(ge=0)]
    not_applicable_count: Annotated[int, Field(ge=0)]
    excluded_count: Annotated[int, Field(ge=0)]
    mean: float | None
    lean: float | None
    width: Annotated[int, Field(ge=0, le=2)] | None
    degree: float | None

    @model_validator(mode="after")
    def counts_and_nulls(self) -> Self:
        if self.scored_count + self.unreadable_count + self.not_applicable_count + self.excluded_count != self.target_count:
            raise ValueError("item states must account for every item of the domain")
        if (self.mean is None) != (self.lean is None):
            raise ValueError("lean is derived from mean; both or neither")
        if self.scored_count == 0 and any(value is not None for value in (self.mean, self.width, self.degree)):
            raise ValueError("a domain without scored items has no values")
        return self


class Indicator(Contract):
    key: IndicatorKey
    value: float | None
    status: DerivedStatus
    reason: Text | None = None

    @model_validator(mode="after")
    def value_only_when_calculated(self) -> Self:
        if (self.status == "calculated") != (self.value is not None):
            raise ValueError("calculated indicators carry a value; missing/invalid ones do not")
        if self.status != "calculated" and self.reason is None:
            raise ValueError("missing or invalid indicators require a reason")
        return self


class TypeResult(Contract):
    key: TypeKey
    label: Text | None
    status: DerivedStatus
    reason: Text | None = None

    @model_validator(mode="after")
    def named_only_when_calculated(self) -> Self:
        if (self.status == "calculated") != (self.label is not None):
            raise ValueError("calculated types carry a label; missing/invalid ones do not")
        if self.status != "calculated" and self.reason is None:
            raise ValueError("missing or invalid types require a reason")
        if self.label is not None and self.label not in TYPE_LABELS[self.key]:
            raise ValueError("type label is not one of the agreed Korean names")
        return self


class ScoreResult(Contract):
    sheet_id: Identifier
    catalog_version: Text
    scoring_rule_version: Text
    rater: Rater
    items: tuple[ItemScore, ...]
    baseline_arousal: Annotated[int, Field(ge=1, le=5)] | None
    domains: tuple[DomainSummary, ...]
    indicators: tuple[Indicator, ...]
    types: tuple[TypeResult, ...]

    @model_validator(mode="after")
    def complete_result(self) -> Self:
        ids = tuple(item.item_id for item in self.items)
        if not ids or ids != tuple(item_id for item_id in BEHAVIOR_IDS if item_id in set(ids)):
            raise ValueError("result lists the rated items once each, in catalog order")
        if sorted(domain.domain for domain in self.domains) != sorted(("SOC_E", "SOC_H", "ATT", "SYN", "EDU", "EXIT")):
            raise ValueError("result needs one summary per domain")
        if tuple(indicator.key for indicator in self.indicators) != INDICATOR_KEYS:
            raise ValueError("result needs the four indicators in order")
        if tuple(result.key for result in self.types) != ("attachment", "sociability_person"):
            raise ValueError("result needs the two type judgements")
        return self


class SurveyItemValue(Contract):
    item_id: SurveyId
    raw: Answer | None
    converted: Answer | None
    not_applicable: bool

    @model_validator(mode="after")
    def missing_stays_missing(self) -> Self:
        if (self.raw is None) != (self.converted is None):
            raise ValueError("a missing answer has no converted value")
        if self.not_applicable and self.raw is not None:
            raise ValueError("해당 없음 has no answer")
        return self


class SurveyDomainScore(Contract):
    domain: SurveyMeanDomain
    mean: float | None
    answered_count: Annotated[int, Field(ge=0)]
    target_count: Annotated[int, Field(gt=0)]
    status: Literal["calculated", "partial", "missing"]

    @model_validator(mode="after")
    def status_matches_counts(self) -> Self:
        if self.answered_count > self.target_count:
            raise ValueError("answered_count exceeds target_count")
        expected = ("missing" if self.answered_count == 0 else
                    "calculated" if self.answered_count == self.target_count else "partial")
        if self.status != expected or (self.mean is None) != (self.answered_count == 0):
            raise ValueError("domain status and mean must follow the answered count")
        return self


class SeparationType(Contract):
    resistance: float | None
    recovery: Annotated[int, Field(ge=1, le=5)] | None
    label: SeparationLabel | None
    status: Literal["calculated", "missing"]
    reason: Text | None = None

    @model_validator(mode="after")
    def label_only_when_calculated(self) -> Self:
        complete = self.resistance is not None and self.recovery is not None
        if (self.status == "calculated") != complete or (self.label is not None) != complete:
            raise ValueError("separation type needs both resistance and recovery")
        if self.status == "missing" and self.reason is None:
            raise ValueError("missing separation type requires a reason")
        return self


class SurveyResult(Contract):
    """No total and no ranking: the survey is compared with the video, never summed (01 §6)."""

    catalog_version: Text
    scoring_rule_version: Text
    items: tuple[SurveyItemValue, ...]
    domains: tuple[SurveyDomainScore, ...]
    separation: SeparationType
    status: Literal["calculated", "partial", "unregistered"]

    @model_validator(mode="after")
    def complete_survey(self) -> Self:
        if tuple(item.item_id for item in self.items) != SURVEY_IDS:
            raise ValueError("survey result lists s01 through s28 in order")
        if tuple(domain.domain for domain in self.domains) != ("A", "B", "C", "E"):
            raise ValueError("survey means cover A, B, C and E; D is a type, not a mean")
        answered = sum(item.raw is not None for item in self.items)
        expected = "unregistered" if answered == 0 else "calculated" if answered == len(self.items) else "partial"
        if self.status != expected:
            raise ValueError("survey status must follow the answered count")
        return self
