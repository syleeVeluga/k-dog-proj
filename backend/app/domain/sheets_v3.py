"""Immutable evaluator sheets: assignment, original input and exposure are separate facts."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.domain.base import Hash, Identifier, Text, require_unique
from app.domain.catalog_v3 import ContractV3
from app.domain.contracts_v3 import ScoreSheetV3
from app.domain.preprocess_v3 import InputPointerV3, WindowV3
from app.input_models_v3 import SessionV3
from app.input_models import Key

AI_ACCOUNT = "kdog-ai-service"


class SheetReferenceV3(ContractV3):
    sheet_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    ref: Annotated[str, Field(pattern=r"^sheets/[^\\]+\.json$")]
    hash: Hash


class BatchPointerV3(ContractV3):
    ref: Annotated[str, Field(pattern=r"^clips/[^\\]+/clips\.json$")]
    hash: Hash


class SheetInputV3(ContractV3):
    input_revision: Annotated[int, Field(ge=1)]
    input: InputPointerV3
    catalog_hash: Hash
    protocol_hash: Hash
    window_rules_hash: Hash
    session: SessionV3
    windows: tuple[WindowV3, ...]
    preprocess: BatchPointerV3 | None = None

    @model_validator(mode="after")
    def confirmed(self) -> Self:
        if self.session.protocol_version != "protocol-20260929-v3" or not self.session.recording or not self.session.recording.confirmed:
            raise ValueError("sheets require a confirmed current recording snapshot")
        require_unique(tuple(window.window_id for window in self.windows), "snapshot window")
        return self


class SheetDocumentV3(ContractV3):
    revision: Annotated[int, Field(ge=1)]
    state: Literal["draft", "submitted"]
    assigned_username: Key
    rater_name: Text
    purpose: Literal["independent", "review", "consensus"]
    active: bool
    actor: Key
    recorded_at: Text
    change_reason: Text
    source: SheetInputV3
    source_hash: Hash
    sheet: ScoreSheetV3
    previous: tuple[SheetReferenceV3, ...] = ()
    initial_submission: SheetReferenceV3 | None = None
    exposures: tuple[SheetReferenceV3, ...] = ()
    ai_run_id: Identifier | None = None
    ai_failures: dict[str, str] = {}

    @model_validator(mode="after")
    def identity(self) -> Self:
        if self.source.session.session_id != self.sheet.session_id:
            raise ValueError("sheet and input snapshot session differ")
        if any(ref.sheet_id != self.sheet.sheet_id for ref in self.previous):
            raise ValueError("previous revisions must belong to this sheet")
        require_unique(tuple(ref.ref for ref in self.previous), "previous revision")
        require_unique(tuple(ref.ref for ref in self.exposures), "exposure")
        if self.exposures and self.purpose == "independent":
            raise ValueError("an exposed current revision is not independent")
        return self
