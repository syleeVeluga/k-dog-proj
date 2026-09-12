"""S4 provider choices and S5 program results, kept separate from model arithmetic."""

from typing import Annotated, Literal
from pydantic import Field

from app.domain.contracts import BranchEvaluation, ItemEvaluation, ScoreResult
from app.input_models import Model


class EvaluationResponse(Model):
    branch: Literal["dog", "owner"]
    items: list[ItemEvaluation]


class EvaluationArtifact(Model):
    evaluation: BranchEvaluation
    scores: ScoreResult
    usage: dict[str, int | str | bool]
    single_view_item_ids: list[str] = []
    review_overridden_item_ids: list[str] = []


class SurveyValue(Model):
    item_id: str
    raw: int | None
    converted: int | None
    source_layer: str
    status: Literal["calculated", "missing", "rule_pending"]


class SurveyGroup(Model):
    group: str
    mean: float | None
    valid_count: int
    target_count: int | None
    status: Literal["calculated", "missing", "rule_pending"]


class SurveyResult(Model):
    run_id: str
    catalog_version: str
    scoring_rule_version: str
    items: list[SurveyValue]
    groups: list[SurveyGroup]
    overall_reference: float | None
    status: Literal["calculated", "partial", "unregistered"]
    mapping_status: Literal["mapping_pending"] = "mapping_pending"
    cross_type_status: Literal["type_rule_pending"] = "type_rule_pending"


class ProviderState(Model):
    provider: str
    model: str


class ProviderSelection(ProviderState):
    provider: Literal["gemini", "openai", "anthropic"]
    model: Annotated[str, Field(max_length=150, pattern=r"^([a-zA-Z0-9][a-zA-Z0-9._-]*)?$")]


class BranchSettings(Model):
    dog: ProviderSelection
    owner: ProviderSelection


class SettingsEdit(Model):
    expected_version: str
    branches: BranchSettings


class BranchState(Model):
    dog: ProviderState
    owner: ProviderState


class SettingsView(Model):
    version: str
    branches: BranchState
    key_available: dict[str, bool]
