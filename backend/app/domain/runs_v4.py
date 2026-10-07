"""Pinned S1 execution, provider stages and explicit reuse identities."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .catalog_v4 import AUTO_CODES, ContractV4, Hash, ItemCode, SCORING_VERSION, Text
from .media_v4 import MediaKey
from .preprocess_v4 import BatchV4
from .sheets_v4 import BatchPointerV4, InputPointerV4
from ..input_models import Model, Revision
from ..input_models_v4 import SessionV4


class StageV4(ContractV4):
    stage: Literal["score_v4", "calculate_v4", "attachment_v4", "publish_v4"]
    key: Text
    item_codes: Annotated[tuple[ItemCode, ...], Field(min_length=1, max_length=86)]
    window_ids: tuple[Text, ...] = ()
    prompt: Text
    response_schema: dict
    provider: Literal["gemini", "program"]
    model: Text
    input_variant: Literal["ai", "original"] = "ai"
    production_fps: Literal["one_actual_frame_per_second", "source_frames"]
    request_fps: Annotated[float, Field(gt=0, le=10)] | None
    media_resolution: Literal["low", "medium", "high"] = "medium"
    provider_call: bool = True
    processing_mode: Literal["static", "agentic"] = "static"
    max_output_tokens: Annotated[int, Field(ge=256, le=65536)] = 16384
    thinking_level: Literal["low", "medium", "high"] = "medium"

    @model_validator(mode="after")
    def direct_codes(self) -> Self:
        if len(set(self.item_codes)) != len(self.item_codes) or set(self.item_codes) & set(AUTO_CODES):
            raise ValueError("only distinct S1 direct numeric/memo codes belong to AI stages")
        expected_fps = "one_actual_frame_per_second" if self.input_variant == "ai" else "source_frames"
        if self.production_fps != expected_fps:
            raise ValueError("production FPS must identify the selected derivative")
        if not self.provider_call and (self.provider != "program" or self.model != "program"):
            raise ValueError("non-provider stages must use the program executor")
        if self.provider_call:
            if self.stage not in ("score_v4", "attachment_v4") or self.provider != "gemini" or self.model != "gemini-3.8-flash":
                raise ValueError("unsupported S1 provider stage")
            if (self.processing_mode == "agentic") != (self.request_fps is None):
                raise ValueError("static sampling requires fps; agentic requires null fps")
            if self.input_variant == "ai" and self.request_fps is not None and self.request_fps > 1:
                raise ValueError("1fps derivatives cannot supply invented high-rate frames")
        return self


class RunConfigV4(ContractV4):
    version: Literal["ai-scoring-20261002-s1.1-1", "ai-scoring-20261007-rp02"] = "ai-scoring-20261007-rp02"
    active_settings_version: Text | None = None
    settings_hash: Hash | None = None
    raw_observation_scope_confirmed: bool = False
    stages: Annotated[tuple[StageV4, ...], Field(min_length=1, max_length=90)]
    max_attempts: Annotated[int, Field(ge=1, le=3)] = 3
    max_ai_calls: Annotated[int, Field(ge=1, le=1000)] = 100
    max_schema_repairs: Annotated[int, Field(ge=0, le=1)] = 1

    @model_validator(mode="after")
    def groups(self) -> Self:
        keys = [(item.stage, item.key) for item in self.stages]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate execution stage")
        return self


class RunInputV4(ContractV4):
    case_id: MediaKey
    session_id: MediaKey
    input_revision: Annotated[int, Field(ge=1)]
    input: InputPointerV4
    session: SessionV4
    preprocess: BatchPointerV4
    batch: BatchV4
    calculation_version: Literal["scoring-20261002-s1.1-app-1"] = SCORING_VERSION
    calculation_hash: Hash
    requested_by: MediaKey

    @model_validator(mode="after")
    def identity(self) -> Self:
        batch = self.batch
        if (batch.case_id, batch.session_id, batch.input_revision, batch.input.ref, batch.input.hash, batch.batch_id) != (
                self.case_id, self.session_id, self.input_revision, self.input.manifest_ref, self.input.manifest_hash, self.preprocess.batch_id):
            raise ValueError("batch and run source pins differ")
        if self.session.session_id != self.session_id or self.session.recording_s1 != batch.recording:
            raise ValueError("recording facts differ from the selected S1 batch")
        files = {(item.storage_ref, item.sha256) for item in self.session.videos}
        if any((item.ref, item.hash) not in files for item in batch.source_files):
            raise ValueError("batch references another session's video")
        if batch.asset_hashes.get("rules/scoring-v4.json") != self.calculation_hash:
            raise ValueError("calculation and batch rule hashes differ")
        return self


class ReuseV4(ContractV4):
    source_run_id: MediaKey
    step_id: MediaKey
    stage: Literal["score_v4"]
    key: Text
    ref: Annotated[str, Field(pattern=r"^runs/[^\\]+/output\.json$")]
    hash: Hash
    compatibility_hash: Hash


class StartV4(Revision):
    request_id: MediaKey
    preprocess_ref: Text
    preprocess_hash: Hash
    settings_version: Text | None = None
    reuse_run_id: MediaKey | None = None


class ActionV4(Model):
    expected_updated_at: Text
    reason: Text


class RunStepViewV4(Model):
    stage: Literal["score_v4", "calculate_v4", "attachment_v4", "publish_v4"]
    key: Text
    attempt: Annotated[int, Field(ge=1)]
    status: str
    code: str | None
    billing_uncertain: bool
    remote_cleanup_pending: bool
    call_reserved: bool
    reused: bool
    timing: dict[str, float]
    token_meters: dict[str, int] = Field(default_factory=dict)
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None


class RunViewV4(Model):
    run_id: MediaKey
    case_id: MediaKey
    session_id: MediaKey
    kind: Literal["s1"]
    input_revision: Annotated[int, Field(ge=1)]
    status: str
    updated_at: Text
    outdated: bool
    failure_code: str | None
    result_available: bool
    steps: list[RunStepViewV4]
    planned_provider_calls: Annotated[int, Field(ge=0)]
    reserved_calls: Annotated[int, Field(ge=0)]
    max_ai_calls: Annotated[int, Field(ge=1)]
    judgement_status: Literal["policy_pending_D04", "implemented_professor_test_pending"]
