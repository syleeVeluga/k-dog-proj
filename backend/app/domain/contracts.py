"""M0 file/API contracts. Production catalog content must come from source Excel."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Revision = Annotated[int, Field(ge=1)]
BehaviorId = Annotated[str, Field(pattern=r"^(BS-(0[1-9]|1[0-6])|DOG-(0[1-9]|1[0-9]|20)|OWN-(0[1-9]|1[0-9]))$")]
SurveyId = Annotated[str, Field(pattern=r"^q(0[1-9]|[12][0-9]|30)$")]
Status = Literal[
    "scored", "not_visible", "audio_unusable", "not_performed",
    "not_applicable", "insufficient_evidence", "conflicting_evidence", "rule_pending",
]
Direction = Literal["A", "B"] | None
Domain = Literal["EDU", "SOC_P", "SOC_D", "SOC_E", "ATT", "CON", "TRN"]
BEHAVIOR_IDS = tuple(
    f"{prefix}-{number:02d}"
    for prefix, count in (("BS", 16), ("DOG", 20), ("OWN", 19))
    for number in range(1, count + 1)
)
SURVEY_IDS = tuple(f"q{number:02d}" for number in range(1, 31))


def require_unique(values: list[str] | tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False,
        revalidate_instances="always",
    )
    schema_version: Literal["1.0"] = "1.0"


class VideoReference(Contract):
    video_id: Identifier
    camera_id: Identifier
    sha256: Hash
    storage_ref: Text
    duration_sec: Positive
    audio_status: Literal["present", "absent", "unusable", "unknown"]
    clip_offset_sec: Nonnegative = 0.0
    sync_offset_sec: float | None = None
    sync_method: Literal["marker", "operator"] | None = None

    @field_validator("storage_ref")
    @classmethod
    def managed_relative_reference(cls, value: str) -> str:
        # This is a storage key, never a user-supplied OS path or URL.
        if value.startswith("/") or ":" in value or "\\" in value:
            raise ValueError("storage_ref must be a relative POSIX storage key")
        if any(part in ("", ".", "..") for part in value.split("/")):
            raise ValueError("invalid storage_ref component")
        return value

    @model_validator(mode="after")
    def synchronization_pair(self) -> Self:
        if (self.sync_offset_sec is None) != (self.sync_method is None):
            raise ValueError("sync offset requires a marker or operator correction")
        return self


class RunInput(Contract):
    run_id: Identifier
    case_id: Identifier
    event_id: Text
    participant_id: Text
    session_id: Identifier
    input_revision: Revision
    catalog_version: Text
    pipeline_version: Text
    scoring_rule_version: Text
    report_mapping_version: Text
    prompt_version: Text
    config_version: Text
    # 데이터입력!A2: normalized original responses 1..5; conversion is separate.
    survey: dict[SurveyId, Annotated[int, Field(ge=1, le=5)] | None]
    videos: Annotated[tuple[VideoReference, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def complete_input(self) -> Self:
        if set(self.survey) != set(SURVEY_IDS):
            raise ValueError("survey requires exactly q01 through q30; missing answers use null")
        if any(isinstance(value, bool) for value in self.survey.values()):
            raise ValueError("boolean survey answers are not raw numeric/text responses")
        require_unique(tuple(video.video_id for video in self.videos), "video_id")
        return self


class Evidence(Contract):
    evidence_id: Identifier
    run_id: Identifier
    case_id: Identifier
    session_id: Identifier
    video_id: Identifier
    camera_id: Identifier
    segment_id: Identifier
    source_start_sec: Nonnegative
    source_end_sec: Nonnegative
    subject: Literal["dog", "owner", "staff", "unknown"]
    modality: Literal["video", "audio", "audio_video"]
    observation: Text
    candidate_item_ids: Annotated[tuple[BehaviorId, ...], Field(min_length=1)]
    quality_flags: tuple[Text, ...] = ()
    event_group_id: Identifier | None = None

    @model_validator(mode="after")
    def ordered_interval(self) -> Self:
        if self.source_end_sec < self.source_start_sec:
            raise ValueError("evidence end precedes start")
        require_unique(self.candidate_item_ids, "candidate item")
        return self


class ItemEvaluation(Contract):
    item_id: BehaviorId
    status: Status
    selected_option_id: Text | None
    evidence_ids: tuple[Identifier, ...]
    reason: Text

    @model_validator(mode="after")
    def selected_only_when_scored(self) -> Self:
        require_unique(self.evidence_ids, "evidence_id")
        if self.status == "scored":
            if self.selected_option_id is None or not self.evidence_ids:
                raise ValueError("scored requires an option and evidence")
        elif self.selected_option_id is not None:
            raise ValueError("unscored and rule_pending options must be null")
        return self


class BranchEvaluation(Contract):
    run_id: Identifier
    branch: Literal["dog", "owner"]
    items: tuple[ItemEvaluation, ...]

    @model_validator(mode="after")
    def exact_branch_items(self) -> Self:
        expected = {
            item for item in BEHAVIOR_IDS
            if item.startswith("OWN-") == (self.branch == "owner")
        }
        ids = tuple(item.item_id for item in self.items)
        require_unique(ids, "evaluation item")
        if set(ids) != expected:
            raise ValueError("branch must contain exactly its 36 dog or 19 owner items")
        return self


class CatalogOption(Contract):
    option_id: Text
    text: Text
    score: float
    direction: Direction
    source_cell: Text


class CatalogItem(Contract):
    item_id: BehaviorId
    text: Text
    segment: Text
    domain: Domain | None
    source_sheet: Text
    source_row: Revision
    options: Annotated[tuple[CatalogOption, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_options(self) -> Self:
        require_unique(tuple(option.option_id for option in self.options), "option_id")
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
        if set(ids) != set(BEHAVIOR_IDS):
            raise ValueError("catalog must contain all 55 behavior items exactly once")
        return self


class SurveyItem(Contract):
    item_id: SurveyId
    text: Text
    domain_label: Literal["A", "B", "C", "D"]
    source_layer: Literal["원", "C", "영"]
    scoring_note: Text
    source_sheet: Text
    source_row: Revision


class SurveyCatalog(Contract):
    version: Text
    source_filename: Text
    source_sha256: Hash
    provenance: Literal["excel_verified"]
    response_instructions: Text
    allowed_responses: tuple[Literal[1, 2, 3, 4, 5], ...]
    items: tuple[SurveyItem, ...]

    @model_validator(mode="after")
    def exact_survey(self) -> Self:
        ids = tuple(item.item_id for item in self.items)
        require_unique(ids, "survey item")
        if set(ids) != set(SURVEY_IDS):
            raise ValueError("catalog requires exactly 30 survey items")
        if self.allowed_responses != (1, 2, 3, 4, 5):
            raise ValueError("source response scale is 1 through 5")
        return self


class ItemScore(Contract):
    item_id: BehaviorId
    status: Status
    raw_score: float | None
    direction: Direction
    reason: Text

    @model_validator(mode="after")
    def null_missing_score(self) -> Self:
        if self.status == "scored" and self.raw_score is None:
            raise ValueError("scored requires raw_score")
        if self.status != "scored" and (self.raw_score is not None or self.direction is not None):
            raise ValueError("unscored values and direction must be null")
        return self


class DomainScore(Contract):
    domain: Domain
    mean: float | None
    maximum: float | None
    valid_count: Annotated[int, Field(ge=0)]
    target_count: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def valid_denominator(self) -> Self:
        if self.valid_count > self.target_count:
            raise ValueError("valid_count exceeds target_count")
        if self.valid_count == 0:
            if self.mean is not None or self.maximum is not None:
                raise ValueError("empty domain must have null mean and maximum")
        elif self.mean is None or self.maximum is None or self.mean > self.maximum:
            raise ValueError("nonempty domain requires mean <= maximum")
        return self


class ScoreResult(Contract):
    run_id: Identifier
    catalog_version: Text
    scoring_rule_version: Text
    items: tuple[ItemScore, ...]
    domains: tuple[DomainScore, ...]

    @model_validator(mode="after")
    def unique_results(self) -> Self:
        require_unique(tuple(item.item_id for item in self.items), "score item")
        require_unique(tuple(domain.domain for domain in self.domains), "score domain")
        return self


class ReportDomain(Contract):
    # Slot numbers do not assert an unconfirmed domain-name mapping.
    slot: Literal[1, 2, 3, 4]
    status: Literal["ready", "mapping_pending", "insufficient_evidence"]
    label: Text | None
    value: float | None
    comment: Text
    evidence_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def pending_display(self) -> Self:
        if self.status != "ready" and self.value is not None:
            raise ValueError("pending or missing report value must be null")
        if self.status == "mapping_pending" and self.label is not None:
            raise ValueError("unconfirmed domain mapping must not assert a label")
        if self.status == "ready" and (self.label is None or self.value is None):
            raise ValueError("ready domain requires label and value")
        return self


class ReportText(Contract):
    text: Text
    evidence_ids: tuple[Identifier, ...]


class CrossType(Contract):
    status: Literal["ready", "type_rule_pending", "insufficient_evidence"]
    rule_id: Text | None
    type_name: Text | None
    explanation: Text
    evidence_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def pending_type(self) -> Self:
        if self.status == "ready" and (self.rule_id is None or self.type_name is None):
            raise ValueError("ready type requires a rule and name")
        if self.status != "ready" and self.type_name is not None:
            raise ValueError("pending type name must be null")
        if self.status == "type_rule_pending" and self.rule_id is not None:
            raise ValueError("pending type rule must be null")
        return self


class ReportResult(Contract):
    run_id: Identifier
    report_mapping_version: Text
    result_revision: Revision
    cover: ReportText
    domains: Annotated[tuple[ReportDomain, ...], Field(min_length=4, max_length=4)]
    cross_type: CrossType
    tips: Annotated[tuple[ReportText, ...], Field(min_length=1, max_length=2)]
    notice: Text

    @model_validator(mode="after")
    def four_slots(self) -> Self:
        if {domain.slot for domain in self.domains} != {1, 2, 3, 4}:
            raise ValueError("report requires four distinct domain slots")
        return self
