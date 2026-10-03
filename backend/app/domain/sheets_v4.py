"""Immutable S1 evaluator inputs, original submissions and disclosure references."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .catalog_v4 import ContractV4, Hash, Text
from .contracts_v4 import ScoreSheetV4
from .media_v4 import MediaKey
from .disclosures_v4 import InterpretationExposureV4
from .recording_v4 import RecordingWindowV4, unique
from app.input_models_v4 import SessionV4

AI_ACCOUNT = "kdog-ai-service"


class SheetReferenceV4(ContractV4):
    sheet_id: MediaKey
    revision: Annotated[int, Field(ge=1)]
    ref: Annotated[str, Field(pattern=r"^sheets/[^\\]+\.json$")]
    hash: Hash


class InputPointerV4(ContractV4):
    manifest_ref: Annotated[str, Field(pattern=r"^inputs/[^/\\]+\.json$")]
    manifest_hash: Hash


class BatchPointerV4(ContractV4):
    ref: Annotated[str, Field(pattern=r"^clips/[^\\]+\.json$")]
    hash: Hash
    batch_id: MediaKey


class SheetInputV4(ContractV4):
    input_revision: Annotated[int, Field(ge=1)]
    input: InputPointerV4
    asset_hashes: dict[str, Hash]
    session: SessionV4
    windows: tuple[RecordingWindowV4, ...]
    batch_id: MediaKey
    preprocess: BatchPointerV4 | None = None

    @model_validator(mode="after")
    def confirmed_input(self) -> Self:
        capture = getattr(self.session, "recording_s1", None)
        if capture is None or not capture.confirmed:
            raise ValueError("S1 sheets require a confirmed recording-fact snapshot")
        if set(self.asset_hashes) != {"catalog", "protocol", "scoring", "preprocess"}:
            raise ValueError("snapshot requires every S1 contract asset hash")
        unique(tuple(window.window_id for window in self.windows), "snapshot window")
        if self.preprocess is not None and self.preprocess.batch_id != self.batch_id:
            raise ValueError("batch pointer does not identify this input batch")
        return self


class SheetDocumentV4(ContractV4):
    revision: Annotated[int, Field(ge=1)]
    state: Literal["draft", "submitted"]
    assigned_username: MediaKey
    rater_name: Text
    purpose: Literal["independent", "review", "consensus"]
    origin: Literal["human_web", "ai_service", "historical_import"]
    active: bool
    actor: MediaKey
    recorded_at: Text
    change_reason: Text
    source: SheetInputV4
    source_hash: Hash
    sheet: ScoreSheetV4
    previous: tuple[SheetReferenceV4, ...] = ()
    initial_submission: SheetReferenceV4 | None = None
    exposures: tuple[SheetReferenceV4, ...] = ()
    interpretation_exposures: tuple[InterpretationExposureV4, ...] = ()
    ai_run_id: MediaKey | None = None
    ai_failures: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def identity(self) -> Self:
        if (self.source.session.session_id, self.source.input_revision, self.source.input.manifest_hash, self.source.batch_id) != (
                self.sheet.session_id, self.sheet.input_revision, self.sheet.input_sha256, self.sheet.batch_id):
            raise ValueError("S1 sheet and input snapshot identity differ")
        if any(link.sheet_id != self.sheet.sheet_id or link.revision >= self.revision for link in self.previous):
            raise ValueError("previous revisions must precede this same sheet")
        unique(tuple(link.ref for link in self.previous), "previous reference")
        unique(tuple(link.revision for link in self.previous), "previous revision")
        unique(tuple(link.ref for link in self.exposures), "exposure")
        unique(tuple(item.exposure_id for item in self.interpretation_exposures), "interpretation exposure")
        if any((item.case_id, item.session_id) != (self.sheet.case_id, self.sheet.session_id) for item in self.interpretation_exposures):
            raise ValueError("interpretation exposure belongs to another case or session")
        if (self.exposures or self.interpretation_exposures) and self.purpose == "independent":
            raise ValueError("exposed revisions cannot be classified as independent")
        if self.initial_submission and self.initial_submission not in self.previous:
            raise ValueError("initial submission must identify a preserved revision")
        if self.sheet.rater_kind == "ai":
            if self.assigned_username != AI_ACCOUNT or self.origin != "ai_service":
                raise ValueError("AI identity cannot be represented as a human assignment")
            if self.state == "submitted" and self.ai_run_id is None:
                raise ValueError("completed AI original requires its execution identity")
        elif self.origin == "ai_service" or self.assigned_username == AI_ACCOUNT or self.ai_run_id is not None:
            raise ValueError("human original cannot claim an AI service identity")
        if self.origin == "historical_import" and self.purpose == "independent":
            raise ValueError("historical imports do not establish blind independent ratings")
        return self
