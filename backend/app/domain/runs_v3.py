"""Frozen execution contracts, independent of the legacy 55-item parser."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.domain.base import Hash, Identifier, Text, require_unique
from app.domain.catalog_v3 import AUTO_CODES, UNUSED_CODES, ContractV3, ItemCode
from app.domain.preprocess_v3 import BatchV3, InputPointerV3
from app.domain.sheets_v3 import BatchPointerV3
from app.input_models_v3 import SessionV3


class StageV3(ContractV3):
    stage: Identifier
    key: Text
    item_codes: Annotated[tuple[ItemCode, ...], Field(min_length=1, max_length=109)]
    prompt: Text
    response_schema: dict
    provider: Text
    model: Text
    production_fps: Text
    request_fps: Annotated[float, Field(gt=0)] | None
    media_resolution: Text
    provider_call: bool = True
    processing_mode: Literal["static", "agentic"] = "static"
    max_output_tokens: Annotated[int, Field(ge=256, le=65536)] = 16384
    thinking_level: Literal["low", "medium", "high"] = "medium"

    @model_validator(mode="after")
    def direct_codes(self) -> Self:
        require_unique(self.item_codes, "stage item")
        if set(self.item_codes) & set(AUTO_CODES + UNUSED_CODES):
            raise ValueError("execution groups contain direct items only")
        return self


class RunConfigV3(ContractV3):
    version: Text
    active_settings_version: Text | None = None
    settings_hash: Hash | None = None
    q11_scope_confirmed: bool = False
    stages: Annotated[tuple[StageV3, ...], Field(min_length=1, max_length=109)]
    max_attempts: Annotated[int, Field(ge=1, le=3)] = 3
    max_ai_calls: Annotated[int, Field(ge=1, le=1000)]
    max_schema_repairs: Annotated[int, Field(ge=0, le=1)] = 1

    @model_validator(mode="after")
    def groups(self) -> Self:
        require_unique(tuple((stage.stage, stage.key) for stage in self.stages), "stage group")
        return self


class RunInputV3(ContractV3):
    case_id: Identifier
    session_id: Identifier
    input_revision: Annotated[int, Field(ge=1)]
    input: InputPointerV3
    session: SessionV3
    preprocess: BatchPointerV3
    batch: BatchV3
    calculation_version: Text
    calculation_hash: Hash
    requested_by: Text

    @model_validator(mode="after")
    def identity(self) -> Self:
        batch = self.batch
        if (batch.case_id, batch.session_id, batch.input_revision, batch.input) != (
                self.case_id, self.session_id, self.input_revision, self.input):
            raise ValueError("batch and execution input differ")
        if self.session.session_id != self.session_id or self.session.recording != batch.recording or tuple(self.session.videos) != batch.sources:
            raise ValueError("recording or original sources differ from the confirmed batch")
        return self


class ReuseV3(ContractV3):
    source_run_id: Identifier
    step_id: Identifier
    stage: Identifier
    key: Text
    ref: Annotated[str, Field(pattern=r"^runs/[^\\]+/output\.json$")]
    hash: Hash
    compatibility_hash: Hash
