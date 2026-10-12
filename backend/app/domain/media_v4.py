"""S1 receipt and media provenance contracts; receipt completion is not analysis."""

from pathlib import PurePath
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_serializer, model_validator

from .catalog_v4 import ContractV4, Hash, Text

MediaKey = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Filename = Annotated[str, Field(min_length=1, max_length=200)]
EXTENSIONS = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".insv")
CAMERA_ORIGINALS = {"CAM1": "1", "CAM2": "3", "CAM3": "2"}


class MediaParentV4(ContractV4):
    upload_id: MediaKey
    sha256: Hash
    video_id: MediaKey | None = None


class ConversionV4(ContractV4):
    tool: Text
    tool_version: Text
    settings: dict[str, JsonValue]


class ExternalProcessingV4(ContractV4):
    projection: Literal["flat", "equirectangular", "unknown"] = "unknown"
    timeline: Literal["preserved", "edited", "unknown"] = "unknown"
    tool_name: Text | None = None
    tool_version: Text | None = None
    note: Text | None = None


class ExternalMediaV4(ContractV4):
    external_processing: ExternalProcessingV4 | None = None

    @model_validator(mode="after")
    def external_origin(self) -> Self:
        if self.source_kind == "external_360_mp4":
            if self.external_processing is None or getattr(self, "parents", ()) or getattr(self, "conversion", None):
                raise ValueError("external MP4 requires processing metadata without registered parents")
            name = getattr(self, "filename", getattr(self, "original_name", None))
            if name is not None and PurePath(name).suffix.lower() != ".mp4":
                raise ValueError("external 360 input must be MP4")
            if hasattr(self, "camera_id") and self.camera_id is not None and self.camera_id != "EXT360":
                raise ValueError("external 360 media uses EXT360")
            if getattr(self, "source_original_number", None) is not None:
                raise ValueError("external 360 media has no registered original number")
        elif self.external_processing is not None:
            raise ValueError("external processing belongs only to external MP4")
        return self

    @model_serializer(mode="wrap")
    def serialize_origin(self, handler):
        value = handler(self)
        # Preserve pre-extension canonical JSON, including every existing null.
        if self.source_kind != "external_360_mp4":
            value.pop("external_processing", None)
        return value


class ExternalProcessingEditV4(ContractV4):
    session_id: MediaKey
    expected_revision: Annotated[int, Field(ge=1)]
    external_processing: ExternalProcessingV4


def external_media_reasons(video) -> tuple[str, ...]:
    if getattr(video, "source_kind", None) != "external_360_mp4":
        return ()
    value = video.external_processing
    return tuple(reason for reason, blocked in (
        ("external_projection_" + value.projection, value.projection != "flat"),
        ("external_timeline_" + value.timeline, value.timeline != "preserved")) if blocked)


class UploadCreateV4(ExternalMediaV4):
    request_id: MediaKey
    filename: Filename
    expected_size: Annotated[int, Field(gt=0)]
    expected_sha256: Hash | None = None
    case_id: MediaKey | None = None
    session_id: MediaKey | None = None
    source_kind: Literal["original", "received_conversion", "external_360_mp4"] = "original"
    parents: list[MediaParentV4] = Field(default_factory=list)
    conversion: ConversionV4 | None = None

    @model_validator(mode="after")
    def receipt_metadata(self) -> Self:
        if any(c in self.filename for c in ("/", "\\", ":")) or any(ord(c) < 32 for c in self.filename):
            raise ValueError("filename is a display name, not a path")
        extension = PurePath(self.filename).suffix.lower()
        if extension not in EXTENSIONS:
            raise ValueError("unsupported received media extension")
        if (self.case_id is None) != (self.session_id is None):
            raise ValueError("receipt scope requires both case and session")
        if len({parent.upload_id for parent in self.parents}) != len(self.parents):
            raise ValueError("duplicate conversion parent")
        if self.source_kind == "original" and (self.parents or self.conversion):
            raise ValueError("original receipt cannot claim a conversion")
        if self.source_kind == "received_conversion" and (extension != ".mp4" or not self.parents or not self.conversion):
            raise ValueError("received conversion needs MP4, parent hashes, tool and settings")
        return self


class UploadLinkV4(ContractV4):
    case_id: MediaKey
    session_id: MediaKey
    camera_id: MediaKey
    source_original_number: Text | None = None
    expected_revision: Annotated[int, Field(ge=1)]


class PreservedMediaRegistrationV4(ExternalMediaV4):
    request_id: MediaKey
    expected_revision: Annotated[int, Field(ge=1)]
    camera_id: MediaKey
    source_original_number: Text | None = None
    source_kind: Literal["original", "received_conversion", "external_360_mp4"]
    parents: list[MediaParentV4] = Field(default_factory=list)
    conversion: ConversionV4 | None = None

    @model_validator(mode="after")
    def explicit_origin(self) -> Self:
        if len({parent.upload_id for parent in self.parents}) != len(self.parents):
            raise ValueError("duplicate preserved-media parent")
        if self.source_kind == "original" and (self.parents or self.conversion):
            raise ValueError("original media cannot claim a conversion")
        if self.source_kind == "received_conversion" and (not self.parents or self.conversion is None):
            raise ValueError("received conversion requires actual parent and conversion metadata")
        return self


class StoredMediaV4(ExternalMediaV4):
    video_id: MediaKey
    upload_id: MediaKey
    original_name: Filename
    storage_ref: Text
    sha256: Hash
    size_bytes: Annotated[int, Field(gt=0)]
    camera_id: MediaKey
    source_original_number: Text | None = None
    source_kind: Literal["original", "received_conversion", "app_derived", "external_360_mp4"]
    parents: tuple[MediaParentV4, ...] = ()
    conversion: ConversionV4 | None = None
    offset_seconds: float | None = None
    media_status: Literal["pending_probe", "storage_only"]

    @model_validator(mode="after")
    def provenance(self) -> Self:
        if (PurePath(self.original_name).suffix.lower() == ".insv") != (self.media_status == "storage_only"):
            raise ValueError("INSV is storage-only, not a probed analysis input")
        if self.source_kind == "original" and (self.parents or self.conversion):
            raise ValueError("original media cannot claim conversion provenance")
        if self.source_kind in ("received_conversion", "app_derived") and (not self.parents or not self.conversion):
            raise ValueError("converted media requires parent and tool provenance")
        return self


class UploadReceiptV4(ExternalMediaV4):
    upload_id: MediaKey
    request_id: MediaKey
    creator: MediaKey
    filename: Filename
    state: Literal["receiving", "complete", "failed", "linked"]
    expected_size: int
    size_bytes: int | None
    sha256: Hash | None
    media_status: Literal["pending_probe", "storage_only"]
    source_kind: Literal["original", "received_conversion", "external_360_mp4"]
    case_id: MediaKey | None
    session_id: MediaKey | None
    video_id: MediaKey | None
    camera_id: MediaKey | None
    linked_revision: int | None
    failure_code: str | None
    created_at: Text
    updated_at: Text
    analysis_ready: Literal[False] = False
