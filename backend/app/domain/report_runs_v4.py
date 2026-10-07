"""Immutable S1 report admission, rendered files and validated publication contracts."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .catalog_v4 import ContractV4, Hash, Text
from .media_v4 import MediaKey
from .preprocess_v4 import FileV4
from .final_results_v4 import FinalReferenceV4, FinalResultV4
from .report_profile_v4 import ReportProfileV4
from .report_render_v4 import ReportHeaderV4
from .sheets_v4 import InputPointerV4
from .comparisons_v4 import CohortPublicV4, CohortReferenceV4, ExternalReferenceV4

REPORT_RUN_VERSION = "report-run-20261002-s1.1-1"
REPORT_STAGES = ("content_v4", "validate_content_v4", "render_v4", "validate_output_v4", "publish_report_v4")


class ReportStageV4(ContractV4):
    stage: Literal["content_v4", "validate_content_v4", "render_v4", "validate_output_v4", "publish_report_v4"]
    key: Literal["report"] = "report"
    provider: Literal["program", "gemini"] = "program"
    provider_call: bool = False
    model: Literal["program", "gemini-3.8-flash"] = "program"
    prompt: Text | None = Field(default=None, exclude_if=lambda value: value is None)
    response_schema: dict | None = Field(default=None, exclude_if=lambda value: value is None)
    thinking_level: Literal["low", "medium", "high"] | None = Field(default=None, exclude_if=lambda value: value is None)
    max_output_tokens: Annotated[int, Field(ge=128, le=65536)] | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def provider_scope(self) -> Self:
        if self.provider_call:
            if self.stage != "content_v4" or self.provider != "gemini" or self.model != "gemini-3.8-flash" or not all((self.prompt, self.response_schema, self.thinking_level, self.max_output_tokens)):
                raise ValueError("only report content uses the pinned provider contract")
        elif self.provider != "program" or self.model != "program" or any(value is not None for value in (self.prompt, self.response_schema, self.thinking_level, self.max_output_tokens)):
            raise ValueError("program report stage cannot claim provider settings")
        return self


class ReportConfigV4(ContractV4):
    version: Literal["report-run-20261002-s1.1-1", "report-run-20261007-rp03"] = REPORT_RUN_VERSION
    stages: tuple[ReportStageV4, ...]
    max_attempts: Annotated[int, Field(ge=1, le=3)] = 3
    max_schema_repairs: Annotated[int, Field(ge=0, le=1)] = 0
    max_ai_calls: Annotated[int, Field(ge=0, le=3)] = 0
    template_hashes: dict[str, Hash]
    content_hashes: dict[str, Hash]
    provider_text_status: Literal["deferred_S16", "generated_professor_test_pending"] = "deferred_S16"
    comparison_snapshot: CohortReferenceV4 | None = None
    external_comparison: ExternalReferenceV4 | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def stage_order(self) -> Self:
        if tuple(item.stage for item in self.stages) != REPORT_STAGES:
            raise ValueError("report stages must preserve validation before publication")
        generated = self.version == "report-run-20261007-rp03"
        if sum(item.provider_call for item in self.stages) != int(generated) or bool(self.max_ai_calls) != generated or (self.provider_text_status == "generated_professor_test_pending") != generated:
            raise ValueError("report version and provider budget/status differ")
        return self


class ReportInputV4(ContractV4):
    case_id: MediaKey
    session_id: MediaKey
    input_revision: Annotated[int, Field(ge=1)]
    admission_input: InputPointerV4
    requested_by: MediaKey
    viewer_sheet_id: MediaKey | None = None
    final: FinalReferenceV4
    final_document: FinalResultV4
    profile: ReportProfileV4
    profile_hash: Hash
    header: ReportHeaderV4
    current_opinion: FileV4 | None = None
    current_basic: FileV4
    source_sheet_head: FileV4
    media_sources: tuple[FileV4, ...] = ()
    cohort: CohortPublicV4 | None = None

    @model_validator(mode="after")
    def identity(self) -> Self:
        if (self.final.final_id, self.case_id, self.session_id) != (self.final_document.final_id, self.final_document.case_id, self.final_document.session_id):
            raise ValueError("report final source identity differs")
        if (self.profile.case_id, self.profile.session_id, self.profile.source.final) != (self.case_id, self.session_id, self.final):
            raise ValueError("report content differs from the explicitly selected final result")
        if self.profile.source.basic != self.final_document.basic or self.profile.source.sheet != self.final_document.basic_document.input:
            raise ValueError("report source basis must be pinned through final/basic/raw input")
        if self.header.preview:
            raise ValueError("report runs issue validated program content")
        return self


class ReportImageV4(ContractV4):
    scene_id: Text
    video_id: MediaKey
    video_sha256: Hash
    camera_id: Text
    source_seconds: Annotated[float, Field(ge=0)]
    mime: Literal["image/png"] = "image/png"
    file: FileV4


class ReportPreparedV4(ContractV4):
    profile: ReportProfileV4
    profile_hash: Hash
    images: Annotated[tuple[ReportImageV4, ...], Field(max_length=3)] = ()
    image_issues: dict[str, str] = Field(default_factory=dict)


class ReportRenderedV4(ContractV4):
    profile_hash: Hash
    header_hash: Hash
    html: FileV4
    pdf: FileV4
    images: Annotated[tuple[ReportImageV4, ...], Field(max_length=3)] = ()
    image_issues: dict[str, str] = Field(default_factory=dict)


class ReportPublicationV4(ContractV4):
    artifact_kind: Literal["report-publication"] = "report-publication"
    report_id: MediaKey
    case_id: MediaKey
    session_id: MediaKey
    run_id: MediaKey
    input_hash: Hash
    config_hash: Hash
    final: FinalReferenceV4
    input_revision: Annotated[int, Field(ge=1)]
    header: ReportHeaderV4
    profile: ReportProfileV4
    output: ReportRenderedV4
    cohort: CohortPublicV4 | None = None
    created_at: Text
    publication_state: Literal["issued"] = "issued"
    pending_reasons: tuple[Literal["G02"], ...] = ("G02",)
    normal_publish_available: Literal[True] = True
    content: FileV4 | None = Field(default=None, exclude_if=lambda value: value is None)
    input_profile_hash: Hash | None = Field(default=None, exclude_if=lambda value: value is None)


class ReportReuseV4(ContractV4):
    source_run_id: MediaKey
    step_id: MediaKey
    stage: Literal["content_v4"] = "content_v4"
    key: Literal["report"] = "report"
    ref: Text
    hash: Hash
    compatibility_hash: Hash
