"""42-item behavior catalog (03_행동_채점표_42항목_20260913.xlsx) and 28-item survey catalog (04_보호자_설문지_28문항.pdf). Content must come from the customer sources."""

from collections import Counter
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import Contract, Hash, Revision, Text, require_unique

Sheet = Literal["1_바디시그널", "2_개행동", "3_보호자행동"]
SegmentId = Literal["entry", "baseline", "alone", "stranger", "reunion", "ignore", "walk", "exit"]
# Procedure order (01 §2). The label is the A-column text of the source sheets.
SEGMENTS: tuple[tuple[SegmentId, str], ...] = (
    ("entry", "입장"), ("baseline", "기준"), ("alone", "혼자"), ("stranger", "낯선"),
    ("reunion", "재회"), ("ignore", "무시"), ("walk", "걷기"), ("exit", "퇴장"),
)
ALL_SEGMENTS_LABEL = "전 구간"
DomainCode = Literal["SOC_E", "SOC_H", "ATT", "SYN", "EDU", "EXIT"]
# Scoring items per domain and reference items (None), counted from the AD column (변경검토 §9).
DOMAIN_COUNTS = {"SOC_E": 5, "SOC_H": 4, "ATT": 9, "SYN": 3, "EDU": 5, "EXIT": 2, None: 14}
Axis = Literal["애착", "우호", "사회화", "각성", "거리"]
Scale = Literal["BI", "ONE"]
ValueType = Literal["scale", "count", "phase_count", "auto_ratio"]
BehaviorId = Annotated[str, Field(pattern=r"^(BS-0[1-9]|DOG-(0[1-9]|1[0-9]|2[0-4])|OWN-0[1-9])$")]
SHEET_GROUPS: tuple[tuple[str, Sheet, int], ...] = (("BS", "1_바디시그널", 9), ("DOG", "2_개행동", 24), ("OWN", "3_보호자행동", 9))
BEHAVIOR_IDS: tuple[str, ...] = tuple(
    f"{prefix}-{number:02d}" for prefix, _, count in SHEET_GROUPS for number in range(1, count + 1)
)
PHASE_COUNT_RANGE = tuple(range(0, 7))
SurveyId = Annotated[str, Field(pattern=r"^s(0[1-9]|1[0-9]|2[0-8])$")]
SURVEY_IDS: tuple[str, ...] = tuple(f"s{number:02d}" for number in range(1, 29))
SurveyDomain = Literal["A", "B", "C", "D", "E"]
# Section letter -> (first number, last number, printed title). 04 설문지 두 쪽의 구성이다.
SURVEY_DOMAINS: dict[SurveyDomain, tuple[int, int, str]] = {
    "A": (1, 9, "나의 교육 방식"), "B": (10, 14, "우리 아이의 사회성"), "C": (15, 21, "정서적 친밀감"),
    "D": (22, 25, "떨어져 있을 때 우리 아이는"), "E": (26, 28, "나의 감정 기복"),
}
SURVEY_NOT_APPLICABLE_NUMBERS = (7, 8, 9)
SURVEY_RESPONSE_SCALE = ("전혀 아니다", "아니다", "보통", "그렇다", "매우 그렇다")


class ScaleLabel(Contract):
    score: Literal[1, 2, 3, 4, 5]
    text: Text
    source_cell: Text


class CatalogItem(Contract):
    item_id: BehaviorId
    sheet: Sheet
    source_row: Revision
    segment_label: Text
    segment: SegmentId | None
    text: Text
    domain_label: Text
    domain: DomainCode | None
    axis_label: Text
    axis: Axis | None
    scale: Scale | None
    value_type: ValueType
    labels: tuple[ScaleLabel, ...]
    allowed_scores: tuple[int, ...]
    note: Text | None

    @model_validator(mode="after")
    def consistent_item(self) -> Self:
        if (self.domain is None) != (self.scale is None):
            raise ValueError("reference items have no domain code and no scale; scoring items need both")
        if self.domain is not None and self.value_type != "scale":
            raise ValueError("scoring items are 1-5 scales")
        if (self.segment is None) != (self.segment_label == ALL_SEGMENTS_LABEL):
            raise ValueError("segment is null only for 전 구간 items")
        scores = tuple(label.score for label in self.labels)
        if len(set(scores)) != len(scores):
            raise ValueError("duplicate label score")
        if self.value_type == "scale":
            if not self.labels or self.allowed_scores != scores or self.note is not None:
                raise ValueError("scale items allow exactly the labelled scores")
            if self.scale == "BI" and self.allowed_scores != (1, 2, 3, 4, 5):
                raise ValueError("BI items have labels for 1 to 5")
            if self.scale == "ONE" and self.allowed_scores != (3, 4, 5):
                raise ValueError("ONE items have labels for 3 to 5 only")
        else:
            if self.labels or self.note is None:
                raise ValueError("count/auto items carry an instruction note instead of labels")
            expected = PHASE_COUNT_RANGE if self.value_type == "phase_count" else ()
            if self.allowed_scores != expected:
                raise ValueError("count items are open integers; phase_count is 0-6; auto_ratio is not entered")
        return self


class BehaviorCatalog(Contract):
    version: Text
    source_filename: Text
    source_sha256: Hash
    provenance: Literal["excel_verified", "test_fixture"]
    items: tuple[CatalogItem, ...]

    @model_validator(mode="after")
    def exact_catalog(self) -> Self:
        ids = tuple(item.item_id for item in self.items)
        require_unique(ids, "catalog item")
        if ids != BEHAVIOR_IDS:
            raise ValueError("catalog must contain the 42 behavior items in sheet order")
        if Counter(item.domain for item in self.items) != DOMAIN_COUNTS:
            raise ValueError("domain counts differ from the 28 scoring + 14 reference layout")
        offset = 0
        for _, sheet, count in SHEET_GROUPS:
            for number, item in enumerate(self.items[offset:offset + count], 1):
                if item.sheet != sheet or item.source_row != number + 4:
                    raise ValueError("item id must follow its sheet and row")
            offset += count
        return self

    def rated_items(self) -> tuple[CatalogItem, ...]:
        """Items a rater enters; auto_ratio items are derived by the program."""
        return tuple(item for item in self.items if item.value_type != "auto_ratio")


class SurveyItem(Contract):
    item_id: SurveyId
    number: Annotated[int, Field(ge=1, le=28)]
    text: Text
    domain: SurveyDomain
    allows_not_applicable: bool
    source_page: Literal[1, 2]

    @model_validator(mode="after")
    def consistent_item(self) -> Self:
        first, last, _ = SURVEY_DOMAINS[self.domain]
        if self.item_id != f"s{self.number:02d}" or not first <= self.number <= last:
            raise ValueError("survey item id, number and section disagree")
        if self.allows_not_applicable != (self.number in SURVEY_NOT_APPLICABLE_NUMBERS):
            raise ValueError("only items 7 to 9 offer 해당 없음")
        return self


class SurveyCatalog(Contract):
    version: Text
    source_filename: Text
    source_sha256: Hash
    provenance: Literal["excel_verified", "test_fixture"]
    response_scale: tuple[Text, Text, Text, Text, Text]
    items: tuple[SurveyItem, ...]

    @model_validator(mode="after")
    def exact_survey(self) -> Self:
        if tuple(item.item_id for item in self.items) != SURVEY_IDS:
            raise ValueError("survey catalog must contain s01 through s28 in order")
        if self.response_scale != SURVEY_RESPONSE_SCALE:
            raise ValueError("response scale is the printed 1-5 agreement scale")
        return self
