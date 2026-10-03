"""Pinned presentation inputs; photo bytes never imply a new observation."""

from typing import Annotated, Literal
from pydantic import Field

from .contracts_v4 import ContractV4, Hash, Text


class ReportHeaderV4(ContractV4):
    dog_name: Text
    guardian_name: str = ""
    participant_id: str = ""
    event_name: str = ""
    observed_date: str = ""
    generated_at: str = ""
    preview: bool = False


class SceneImageV4(ContractV4):
    scene_id: Text
    video_id: Text
    video_sha256: Hash
    camera_id: Text
    source_seconds: Annotated[float, Field(ge=0)]
    image_sha256: Hash
    mime: Literal["image/png", "image/jpeg"]
    data: bytes
