"""S6 review requests and program-owned report provenance."""

from typing import Annotated, Literal
import json
from pydantic import Field, field_validator

from app.domain.contracts import ItemEvaluation, ReportResult, ReportText
from app.input_models import Key, Model
from app.evaluation_models import ProviderSelection, ProviderState


class Narration(Model):
    cover: ReportText
    comments: Annotated[list[ReportText], Field(min_length=4, max_length=4)]
    cross: ReportText
    tips: Annotated[list[ReportText], Field(min_length=1, max_length=2)]


class ReviewEdit(Model):
    expected_revision: Annotated[int, Field(ge=1)]
    expected_source_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    reason: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
    item: ItemEvaluation | None = None
    narration: Narration | None = None

    @field_validator("item", "narration", mode="before")
    @classmethod
    def json_contracts(cls, value, info):
        if isinstance(value, dict):
            contract = ItemEvaluation if info.field_name == "item" else Narration
            return contract.model_validate_json(json.dumps(value))
        return value


class FrameEdit(Model):
    expected_revision: Annotated[int, Field(ge=1)]
    video_id: Key
    second: Annotated[float, Field(ge=0)]


class ReportArtifact(Model):
    source_hash: str
    report: ReportResult
    usage: dict[str, int | str | bool]


class ReportSettingsEdit(Model):
    expected_version: str
    selection: ProviderSelection


class ReportSettingsView(Model):
    version: str
    selection: ProviderState
    key_available: bool


class ExportRequest(Model):
    format: Literal["pdf", "xlsx", "csv"]
    case_id: Key | None = None
    run_id: Key | None = None
    event_id: Key | None = None
    case_ids: Annotated[list[Key], Field(min_length=1, max_length=10000)] | None = None
    expected_preview_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None


class ExportMember(Model):
    case_id: str
    event_id: str
    participant_id: str
    dog_name: str
    input_revision: int
    revision: int | None
    run_id: str | None
    status: str
    explanation_status: str


class ExportView(Model):
    export_id: str
    format: str
    created_at: str
    actor: str
    count: int
    status: str
    preview_hash: str = ""
    members: list[ExportMember] = Field(default_factory=list)


class ReportView(Model):
    revision: int
    source_hash: str
    status: str
    report: ReportResult | None
    image: dict | None
    history: list[dict]
    result: dict
