"""S6 review requests and program-owned report provenance."""

from typing import Annotated
from pydantic import Field

from app.legacy.contracts_v1 import ReportResult, ReportText
from app.input_models import Model


class Narration(Model):
    cover: ReportText
    comments: Annotated[list[ReportText], Field(min_length=4, max_length=4)]
    cross: ReportText
    tips: Annotated[list[ReportText], Field(min_length=1, max_length=2)]


class ReportArtifact(Model):
    source_hash: str
    report: ReportResult
    usage: dict[str, int | str | bool]


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
