"""Immutable S1 media derivatives; observation facts never come from frame counts."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .catalog_v4 import ContractV4, Hash, ItemCode, Text
from .media_v4 import MediaKey
from .recording_v4 import RecordingV4, RecordingWindowV4

Seconds = Annotated[float, Field(ge=0)]


class FileV4(ContractV4):
    ref: Text
    hash: Hash


class TimeRangeV4(ContractV4):
    start_seconds: float
    end_seconds: float

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("time ranges must be positive")
        return self


class PreprocessRequestV4(ContractV4):
    request_id: MediaKey
    expected_revision: Annotated[int, Field(ge=1)]
    camera_priority: tuple[MediaKey, ...] = ("CAM1", "CAM2", "CAM3")
    audio_video_id: MediaKey | None = None
    ai_frames_per_second: Literal[1] = 1
    reuse: FileV4 | None = None

    @model_validator(mode="after")
    def cameras(self) -> Self:
        if len(set(self.camera_priority)) != len(self.camera_priority):
            raise ValueError("camera priority must not repeat a camera")
        return self


class ClipFileV4(FileV4):
    size_bytes: Annotated[int, Field(gt=0)]
    duration_seconds: Seconds
    source_time_offset_seconds: Seconds
    frame_times_seconds: tuple[Seconds, ...]
    source_frame_times_seconds: tuple[Seconds, ...]
    audio_ranges: tuple[TimeRangeV4, ...]
    fps_policy: Literal["source_frames", "one_actual_frame_per_second"]

    @model_validator(mode="after")
    def frame_map(self) -> Self:
        if len(self.frame_times_seconds) != len(self.source_frame_times_seconds) or not self.frame_times_seconds:
            raise ValueError("each real derivative frame needs its actual original source timestamp")
        if any(b <= a for a, b in zip(self.frame_times_seconds, self.frame_times_seconds[1:])):
            raise ValueError("derivative frame times must advance without duplication")
        return self


class PhysicalClipV4(ContractV4):
    clip_id: MediaKey
    video_id: MediaKey
    camera_id: MediaKey
    source_start_seconds: Seconds
    source_end_seconds: Seconds
    offset_seconds: float
    window_ids: tuple[MediaKey, ...]
    status: Literal["complete", "partial", "failed", "no_frames"]
    reason: Text | None = None
    original: ClipFileV4 | None = None
    ai: ClipFileV4 | None = None


class ViewWindowV4(ContractV4):
    video_id: MediaKey
    camera_id: MediaKey | None
    offset_seconds: float | None
    source_start_seconds: Seconds | None = None
    source_end_seconds: Seconds | None = None
    clip_ids: tuple[MediaKey, ...] = ()
    availability: Literal["available", "partial", "missing", "offset_unconfirmed", "camera_unassigned",
                          "conversion_required", "failed", "no_frames"]
    visual_state: Literal["unobserved", "whole_observed", "partial_observed", "occluded", "body_unobserved"] = "unobserved"
    visual_ranges: tuple[TimeRangeV4, ...] = ()
    audio_ranges: tuple[TimeRangeV4, ...] = ()
    reasons: tuple[Text, ...] = ()
    quality_event_ids: tuple[MediaKey, ...] = ()


class WindowV4(ContractV4):
    window: RecordingWindowV4
    item_codes: tuple[ItemCode, ...]
    views: tuple[ViewWindowV4, ...]
    media_available_seconds: Seconds
    representative_audio_video_id: MediaKey | None = None
    audio_selection_reason: Text
    audio_available_seconds: Seconds
    audio_loss_ranges: tuple[TimeRangeV4, ...] = ()
    audio_listened_seconds: None = None
    vocal_seconds: None = None


class BatchV4(ContractV4):
    artifact_kind: Literal["preprocess-batch"] = "preprocess-batch"
    batch_id: MediaKey
    claim_token: MediaKey
    case_id: MediaKey
    session_id: MediaKey
    input_revision: Annotated[int, Field(ge=1)]
    input: FileV4
    created_at: Text
    status: Literal["complete", "partial"]
    request: PreprocessRequestV4
    compatibility_hash: Hash
    asset_hashes: dict[str, Hash]
    cut_settings: dict
    encoder_version: Text
    source_files: tuple[FileV4, ...]
    source_metadata: tuple[dict, ...]
    recording: RecordingV4
    clips: tuple[PhysicalClipV4, ...]
    windows: tuple[WindowV4, ...]
    reuse_manifest: FileV4 | None = None
    camera_layout_status: Literal["provisional_D01"] = "provisional_D01"

    @model_validator(mode="after")
    def references(self) -> Self:
        ids = {clip.clip_id for clip in self.clips}
        windows = {window.window.window_id for window in self.windows}
        if len(ids) != len(self.clips) or len(windows) != len(self.windows):
            raise ValueError("physical clips and logical windows must have unique identities")
        for clip in self.clips:
            if clip.source_end_seconds <= clip.source_start_seconds or not set(clip.window_ids) <= windows:
                raise ValueError("clip time/window references differ")
            if clip.status == "complete" and (clip.original is None or clip.ai is None):
                raise ValueError("a complete clip needs both source-FPS and AI derivatives")
        for window in self.windows:
            for view in window.views:
                if not set(view.clip_ids) <= ids:
                    raise ValueError("logical view points to an absent physical clip")
            duration = sum(value.end_seconds - value.start_seconds for value in window.window.source_intervals
                           if value.evidence_id is None)
            if max(window.audio_available_seconds, window.media_available_seconds) > duration + 1e-6:
                raise ValueError("multiple cameras cannot multiply the actual observation window")
        return self


class PreprocessStatusV4(ContractV4):
    case_id: MediaKey
    session_id: MediaKey
    input_revision: int
    ready: bool
    status: Literal["not_ready", "ready", "running", "interrupted", "failed", "complete", "partial"]
    message: Text
    outdated: bool = False
    result_pointer: FileV4 | None = None
    result: BatchV4 | None = None
