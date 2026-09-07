"""Per-view decisions retain coverage and measurements before program merging."""

from typing import Annotated, Literal
from pydantic import Field, model_validator

from app.domain.contracts import BehaviorId, ItemEvaluation, Status
from app.input_models import Model


class Measurement(Model):
    kind: Literal["command_count", "behavior_count", "duration_sec", "latency_sec"]
    value: Annotated[float, Field(ge=0)]
    start_sec: Annotated[float, Field(ge=0)]
    end_sec: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def interval(self):
        if self.end_sec < self.start_sec:
            raise ValueError("measurement end precedes start")
        if self.kind.endswith("count") and not self.value.is_integer():
            raise ValueError("counts must be integers")
        if self.kind.endswith("sec") and self.value > self.end_sec - self.start_sec + 0.01:
            raise ValueError("measured time exceeds observation interval")
        return self


class LedgerEvent(Model):
    step: Literal["entry", "baseline_no_response", "separation", "reunion", "command_1", "command_2",
                  "command_3", "command_4", "play", "exit", "unknown"]
    kind: Literal["command_utterance", "dog_performance", "reward_response", "owner_exit", "owner_return",
                  "dog_settled", "play_cue", "other"]
    start_sec: Annotated[float, Field(ge=0)]
    end_sec: Annotated[float, Field(ge=0)]
    subject: Literal["dog", "owner", "staff", "unknown"]
    modality: Literal["video", "audio", "audio_video"]
    command: Literal["c1", "c2", "c3", "c4", "other", "none"]
    observation: Annotated[str, Field(min_length=1, max_length=4000)]
    quality_flags: Annotated[list[str], Field(max_length=30)]


class VideoDecision(Model):
    item_id: BehaviorId
    status: Status
    selected_option_id: str | None
    observation_indices: list[Annotated[int, Field(ge=1)]]
    reason: Annotated[str, Field(min_length=1, max_length=4000)]
    coverage: Literal["sufficient", "partial", "none"]
    coverage_reason: Annotated[str, Field(min_length=1, max_length=2000)]
    measurements: Annotated[list[Measurement], Field(max_length=100)]


class VideoItem(ItemEvaluation):
    coverage: Literal["sufficient", "partial", "none"]
    coverage_reason: Annotated[str, Field(min_length=1, max_length=2000)]
    measurements: tuple[Measurement, ...]

    @model_validator(mode="after")
    def scored_coverage(self):
        if self.status == "scored" and self.coverage != "sufficient":
            raise ValueError("scored requires sufficient item coverage")
        return self
