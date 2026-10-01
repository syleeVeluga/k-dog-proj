"""2026-09-29 source contracts. Row numbers are identities within this edition."""

from collections import Counter
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import Hash, Text, require_unique

CATALOG_VERSION = "catalog-20260929-v3"
SURVEY_VERSION = "survey-20260929-v3"
PROTOCOL_VERSION = "protocol-20260929-v3"
OWNER_ROWS = (5, 6, 9, 10, 11, 12, 13, 14, 16, 17, 18, 22, 23, 24, 25, 26, 27, 38, 39, 40)
SHEET_ROWS = (("바", "1_바디시그널", tuple(range(5, 46))),
              ("개", "2_개행동", tuple(range(5, 61))), ("보", "3_보호자행동", OWNER_ROWS))
ITEM_CODES = tuple(f"{prefix}{row}" for prefix, _, rows in SHEET_ROWS for row in rows)
UNUSED_CODES = ("개20", "개31", "개33", "개35")
AUTO_CODES = ("개26", "개27", "개36", "개60")
ItemCode = Literal[*ITEM_CODES]
SegmentId = Literal["entry", "baseline", "alone", "reunion", "ignore", "walk", "stranger", "exit"]
SEGMENTS = (("entry", "입장", 30), ("baseline", "기준", 20), ("alone", "혼자", 60),
            ("reunion", "재회", 30), ("ignore", "무시", 20), ("walk", "걷기", 30),
            ("stranger", "낯선", 30), ("exit", "퇴장", 30))


class ContractV3(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False,
                              revalidate_instances="always")
    schema_version: Literal["3.0"] = "3.0"


class Source(ContractV3):
    filename: Text
    sha256: Hash
    location: Text


class Label(ContractV3):
    value: int
    text: Text
    source: Source


class InputRange(ContractV3):
    kind: Literal["whole", "decimal"]
    operator: Text
    minimum: float
    maximum: float | None
    source: Source


class CatalogItemV3(ContractV3):
    code: ItemCode
    sheet: Text
    row: Annotated[int, Field(ge=5)]
    text: Text
    segment_label: Text
    domain_label: str | None
    axis_label: str | None
    usage: Literal["direct", "automatic", "unused"]
    value_type: Literal["category", "count", "seconds", "memo", "automatic", "unused"]
    labels: tuple[Label, ...]
    allowed_values: tuple[int, ...]
    input_range: InputRange | None
    instruction: str | None
    representative_rule: Text
    windows: tuple[Text, ...]
    opportunity_codes: tuple[ItemCode, ...]
    source: Source

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.code not in ITEM_CODES:
            raise ValueError("unknown source row code")
        expected = next((sheet, row) for prefix, sheet, rows in SHEET_ROWS for row in rows
                        if self.code == f"{prefix}{row}")
        if (self.sheet, self.row) != expected:
            raise ValueError("code, sheet and source row disagree")
        usage = "unused" if self.code in UNUSED_CODES else "automatic" if self.code in AUTO_CODES else "direct"
        if self.usage != usage:
            raise ValueError("incorrect usage for source row")
        if self.value_type == "category":
            if not self.labels or tuple(label.value for label in self.labels) != self.allowed_values:
                raise ValueError("category needs its exact value labels")
            require_unique(self.allowed_values, "category value")
        elif self.labels or self.allowed_values:
            raise ValueError("non-categories use instructions, not invented labels")
        if usage != "direct" and self.value_type != usage:
            raise ValueError("automatic/unused rows cannot be entered")
        return self


class BehaviorCatalogV3(ContractV3):
    version: Literal["catalog-20260929-v3"] = CATALOG_VERSION
    source: Source
    items: tuple[CatalogItemV3, ...]

    @model_validator(mode="after")
    def exact_rows(self) -> Self:
        if tuple(item.code for item in self.items) != ITEM_CODES:
            raise ValueError("expected the 117 source rows in sheet order")
        if Counter(item.usage for item in self.items) != {"direct": 109, "automatic": 4, "unused": 4}:
            raise ValueError("expected 113 used rows and 109 direct entries")
        return self

    def rated_items(self) -> tuple[CatalogItemV3, ...]:
        return tuple(item for item in self.items if item.usage == "direct")


class SurveyItemV3(ContractV3):
    item_id: Annotated[str, Field(pattern=r"^s(0[1-9]|1[0-9]|2[0-8])$")]
    external_id: Annotated[str, Field(pattern=r"^Q(0[1-9]|1[0-9]|2[0-8])$")]
    number: Annotated[int, Field(ge=1, le=28)]
    text: Text
    print_section: Literal["A", "B", "C", "D", "E"]
    report_domain: Text
    standalone: bool = False
    allowed_values: tuple[int, ...]
    labels: tuple[Label, ...]
    reverse_scored: bool
    allows_not_applicable: Literal[False] = False
    source: Source

    @model_validator(mode="after")
    def consistent(self) -> Self:
        section = "A" if self.number <= 9 else "B" if self.number <= 14 else "C" if self.number <= 21 else "D" if self.number <= 25 else "E"
        allowed = tuple(range(5)) if 10 <= self.number <= 14 else tuple(range(1, 6))
        if (self.item_id, self.external_id, self.print_section, self.allowed_values, self.reverse_scored) != (
                f"s{self.number:02d}", f"Q{self.number:02d}", section, allowed, self.number >= 26):
            raise ValueError("survey identity, section, scale or reversal disagree")
        if tuple(label.value for label in self.labels) != allowed:
            raise ValueError("survey labels must match the printed scale")
        if self.standalone != (self.number == 25):
            raise ValueError("question 25 is a standalone response")
        return self


class SurveyCatalogV3(ContractV3):
    version: Literal["survey-20260929-v3"] = SURVEY_VERSION
    source: Source
    items: tuple[SurveyItemV3, ...]

    @model_validator(mode="after")
    def exact_items(self) -> Self:
        if tuple(item.number for item in self.items) != tuple(range(1, 29)):
            raise ValueError("expected 28 survey items in print order")
        if len(set(item.report_domain for item in self.items if not item.standalone)) != 8:
            raise ValueError("print sections and eight report domains are distinct")
        return self


class WindowDefinition(ContractV3):
    window_id: Text
    segments: tuple[SegmentId, ...]
    anchor: Text
    start_seconds: float | None = None
    end_seconds: float | None = None
    actual_event_required: bool = False
    source: Source

    @model_validator(mode="after")
    def ordered_offsets(self) -> Self:
        if self.start_seconds is not None and self.start_seconds < 0:
            raise ValueError("negative window offset")
        if self.end_seconds is not None and (self.start_seconds is None or self.end_seconds < self.start_seconds):
            raise ValueError("invalid window end offset")
        if not self.segments:
            raise ValueError("window needs a segment reference")
        require_unique(self.segments, "window segment")
        return self


class SourceText(ContractV3):
    text: str | int | float
    source: Source


class ProtocolV3(ContractV3):
    version: Literal["protocol-20260929-v3"] = PROTOCOL_VERSION
    segment_order: tuple[SegmentId, ...]
    windows: tuple[WindowDefinition, ...]
    pending_policies: tuple[Text, ...]
    procedure_document: tuple[SourceText, ...]
    development_document: tuple[SourceText, ...]

    @model_validator(mode="after")
    def exact_order(self) -> Self:
        if self.segment_order != tuple(segment for segment, _, _ in SEGMENTS):
            raise ValueError("v3 procedure order differs")
        require_unique(tuple(window.window_id for window in self.windows), "window")
        return self


class MappingEntry(ContractV3):
    entry_id: Text
    survey_ids: tuple[Text, ...]
    behavior_codes: tuple[ItemCode, ...]
    windows: tuple[Text, ...]
    result_basis_ids: tuple[Text, ...] = ()
    original: dict
    source: Source

    @model_validator(mode="after")
    def unique_references(self) -> Self:
        for values, label in ((self.survey_ids, "question"), (self.behavior_codes, "behavior"),
                              (self.windows, "window"), (self.result_basis_ids, "result basis")):
            require_unique(values, label)
        return self


class MappingV3(ContractV3):
    version: Literal["mapping-20260929-v3"] = "mapping-20260929-v3"
    kind: Literal["results", "survey_behavior"]
    entries: tuple[MappingEntry, ...]

    @model_validator(mode="after")
    def unique_entries(self) -> Self:
        require_unique(tuple(entry.entry_id for entry in self.entries), "mapping entry")
        return self


class FormulaTemplate(ContractV3):
    formula: Annotated[str, Field(pattern=r"^=")]
    source: Source


class OwnerPoints(ContractV3):
    code: ItemCode
    raw_value: int
    points: tuple[Annotated[int, Field(ge=0, le=2)], Annotated[int, Field(ge=0, le=2)], Annotated[int, Field(ge=0, le=2)]]
    scene: Literal["줄 대처", "재회", "낯선 사람"]
    source: Source


class OwnerThresholds(ContractV3):
    minimum_items: Annotated[int, Field(ge=1)]
    minimum_scenes: Annotated[int, Field(ge=1)]
    dominant_ratio: Annotated[float, Field(ge=0, le=1)]
    ratio_gap: Annotated[float, Field(ge=0, le=1)]
    source: Source
    status: Literal["provisional_v0.2"]


class SeparationCombination(ContractV3):
    initial: Annotated[int, Field(ge=-2, le=2)]
    later: Annotated[int, Field(ge=-2, le=2)]
    text: Text
    source: Source


class ScoringRulesV3(ContractV3):
    version: Literal["scoring-20260929-v3"] = "scoring-20260929-v3"
    pending_policies: tuple[Text, ...]
    owner_type_thresholds: OwnerThresholds
    owner_type_points: tuple[OwnerPoints, ...]
    formula_templates: tuple[FormulaTemplate, ...]
    definitions: tuple[SourceText, ...]
    decision_document: tuple[SourceText, ...]
    comparison_document: tuple[SourceText, ...]
    interpretation_document: tuple[SourceText, ...]
    separation_combinations: tuple[SeparationCombination, ...]

    @model_validator(mode="after")
    def unique_points(self) -> Self:
        require_unique(tuple((point.code, point.raw_value) for point in self.owner_type_points), "owner point")
        require_unique(tuple(formula.source.location for formula in self.formula_templates), "formula location")
        if {(item.initial, item.later) for item in self.separation_combinations} != {
                (initial, later) for initial in range(-2, 3) for later in range(-2, 3)} or len(self.separation_combinations) != 25:
            raise ValueError("expected 25 ordered separation combinations")
        return self
