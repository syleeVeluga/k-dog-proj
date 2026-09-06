"""M2 contracts: model observations contain no participant identity or scores."""

from typing import Annotated, Literal

from pydantic import Field

from app.domain.contracts import BehaviorId, Evidence, RunInput
from app.input_models import Key, Model, Revision
from app.domain.contracts import CatalogItem, ScoreResult
from app.evaluation_models import EvaluationArtifact, SurveyResult
from app.video_models import VideoDecision, VideoItem


SEGMENTS = ("entry", "separation", "reunion", "training", "play", "exit", "unknown")


class AnalysisRequest(Revision):
    reanalyze: bool = False
    reuse_run_id: Key | None = None


class Observation(Model):
    segment_id: Literal["entry", "separation", "reunion", "training", "play", "exit", "unknown"]
    start_sec: Annotated[float, Field(ge=0)]
    end_sec: Annotated[float, Field(ge=0)]
    subject: Literal["dog", "owner", "staff", "unknown"]
    modality: Literal["video", "audio", "audio_video"]
    observation: Annotated[str, Field(min_length=1, max_length=4000)]
    candidate_item_ids: Annotated[list[BehaviorId], Field(min_length=1, max_length=55)]
    quality_flags: Annotated[list[str], Field(max_length=30)]


class ObservationResponse(Model):
    observations: Annotated[list[Observation], Field(max_length=2000)]
    unconfirmed_conditions: Annotated[list[str], Field(max_length=100)]


class VideoResponse(ObservationResponse):
    items: Annotated[list[VideoDecision], Field(min_length=1, max_length=55)]


class MediaInfo(Model):
    video_id: str
    storage_ref: str
    sha256: str
    size_bytes: int
    duration_sec: Annotated[float, Field(gt=0)]
    codec: str
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    audio_status: Literal["present", "absent"]
    mime_type: str
    quality_flags: list[str]


class PreparedInput(Model):
    run_input: RunInput
    media: list[MediaInfo]
    errors: dict[str, str]


class ObservationArtifact(Model):
    run_id: str
    video_id: str
    evidence: list[Evidence]
    unconfirmed_conditions: list[str]
    usage: dict[str, int | str | bool]
    video_items: list[VideoItem] = []
    review_item_ids: list[BehaviorId] = []


class StepView(Model):
    stage: str
    branch_key: str
    attempt: int
    status: str
    retry_at: str | None
    usage: dict[str, int | str | bool]


class RunView(Model):
    run_id: str
    session_id: str
    input_revision: int
    status: str
    created_at: str
    is_current: bool
    steps: list[StepView]
    evidence: list[Evidence]
    media: list[MediaInfo]
    media_errors: dict[str, str]
    unconfirmed_conditions: list[str]
    reused_from: list[str]
    evaluations: list[EvaluationArtifact] = []
    scores: ScoreResult | None = None
    survey_scores: SurveyResult | None = None
    behavior_items: list[CatalogItem] = []
    evaluation_mode: str = "legacy"
    video_assessments: list[ObservationArtifact] = []


class AnalysisView(Model):
    configured: bool
    message: str
    runs: list[RunView]
