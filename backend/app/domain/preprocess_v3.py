"""Validated immutable v3 clip manifest and source-time window references."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.domain.base import Hash, Identifier, Text, require_unique
from app.domain.catalog_v3 import ContractV3, ItemCode, PROTOCOL_VERSION
from app.domain.recording_v3 import CaptureState, RecordingV3, Seconds
from app.input_models import StoredVideo


class WindowV3(ContractV3):
    window_id: Text
    segment: Text
    status: Literal["available", "partial", "not_performed", "no_opportunity", "unobserved", "guidance_only"]
    reason: str | None
    capture_state: CaptureState
    start_sec: Seconds | None
    end_sec: Seconds | None
    source_point_sec: Seconds | None
    event_ids: tuple[Identifier, ...]
    clip_names: tuple[Identifier, ...]
    item_codes: tuple[ItemCode, ...]

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        if (self.start_sec is None) != (self.end_sec is None):
            raise ValueError("observation windows need both boundaries or neither")
        if self.start_sec is not None and self.end_sec <= self.start_sec:
            raise ValueError("no zero-length or inverted observation window")
        if self.status not in ("available", "partial") and not self.reason:
            raise ValueError("missing or excluded windows require a reason")
        return self


class QualityEventV3(ContractV3):
    event_id: Identifier
    kind: Literal["audio_loss", "occlusion"]
    note: Text
    start_sec: Seconds
    end_sec: Seconds
    affected_codes: tuple[ItemCode, ...]


class ClipV3(ContractV3):
    name: Identifier
    segment: Text
    start_sec: Seconds
    end_sec: Seconds
    fps: Text
    window_ids: tuple[Text, ...]
    video_id: Identifier
    ref: Annotated[str, Field(pattern=r"^clips/[^\\]+\.mp4$")]
    hash: Hash
    size_bytes: Annotated[int, Field(gt=0)]
    source_time_offset_sec: Seconds
    decoded_duration_sec: Annotated[float, Field(gt=0)]
    audio_status: Literal["present", "absent"]
    audio_available_seconds: Seconds
    audio_listened_seconds: None
    vocal_seconds: None
    quality_events: tuple[QualityEventV3, ...]

    @model_validator(mode="after")
    def source_time(self) -> Self:
        if self.end_sec <= self.start_sec or self.source_time_offset_sec != self.start_sec:
            raise ValueError("clip must preserve its positive source interval and offset")
        if self.audio_available_seconds > self.end_sec - self.start_sec:
            raise ValueError("audio availability is bounded by the actual source window")
        return self


class InputPointerV3(ContractV3):
    manifest_ref: Annotated[str, Field(pattern=r"^inputs/[^/\\]+\.json$")]
    manifest_hash: Hash


class BatchV3(ContractV3):
    rules_version: Text
    rules_hash: Hash
    protocol_version: Literal["protocol-20260929-v3"] = PROTOCOL_VERSION
    protocol_hash: Hash
    catalog_hash: Hash
    rules: dict
    case_id: Identifier
    session_id: Identifier
    batch_id: Identifier
    input_revision: Annotated[int, Field(ge=1)]
    input: InputPointerV3
    video_id: Identifier
    source_sha256: Hash
    source_duration_sec: Annotated[float, Field(gt=0)]
    source_width: Annotated[int, Field(gt=0)]
    source_height: Annotated[int, Field(gt=0)]
    source_fps: Text
    source_audio: Literal["present", "absent"]
    source_audio_ranges: tuple[dict, ...]
    sources: tuple[StoredVideo, ...]
    created_at: Text
    clips: Annotated[tuple[ClipV3, ...], Field(min_length=1)]
    windows: tuple[WindowV3, ...]
    recording: RecordingV3
    provisional: bool
    provisional_reason: Text
    listening_policy: Text

    @model_validator(mode="after")
    def references(self) -> Self:
        require_unique(tuple(clip.name for clip in self.clips), "clip")
        require_unique(tuple(window.window_id for window in self.windows), "window")
        clips = {clip.name: clip for clip in self.clips}
        windows = {window.window_id: window for window in self.windows}
        for window in self.windows:
            if not set(window.clip_names) <= clips.keys():
                raise ValueError("window references a missing clip")
        for clip in self.clips:
            if not set(clip.window_ids) <= windows.keys() or clip.video_id != self.video_id or clip.end_sec > self.source_duration_sec:
                raise ValueError("clip references an unknown window/video or exceeds the source")
        video = next((video for video in self.sources if video.video_id == self.video_id), None)
        if not video or video.sha256 != self.source_sha256 or self.recording.video_id != self.video_id or not self.recording.confirmed:
            raise ValueError("batch must use its confirmed recording and original source hash")
        return self
