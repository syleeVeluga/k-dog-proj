"""Clip-local AI observations; original-time evidence is derived by the application."""

from typing import Annotated, Literal

from pydantic import Field

from app.domain.base import Identifier, Text
from app.domain.catalog_v3 import ContractV3, ItemCode
from app.domain.contracts_v3 import Seconds


class LocalEvidenceV3(ContractV3):
    clip_name: Identifier
    window_id: Text
    start_seconds: Seconds
    end_seconds: Seconds
    observed_seconds: Seconds
    note: Text
    scoring_exclusion: Literal["none", "welfare_action", "staff_stop_action", "object_instruction"] = "none"


class LocalVocalizationV3(ContractV3):
    clip_name: Identifier
    listened_seconds: Seconds
    cumulative_vocal_seconds: Seconds
    whole_interval_judged: bool
    note: Text


class AiRowV3(ContractV3):
    code: ItemCode
    value: int | float | str | None
    status: Literal["observed", "unobserved", "no_opportunity", "not_performed"]
    reason: Text | None
    opportunity: Literal["present", "absent", "unknown"]
    validity: Literal["valid", "caution", "invalid", "unknown"]
    welfare_stopped: bool
    evidence: tuple[LocalEvidenceV3, ...]
    latency_not_occurred: bool
    actual_latency_seconds: Seconds | None
    vocalization: LocalVocalizationV3 | None


class AiResponseV3(ContractV3):
    observations: Annotated[tuple[AiRowV3, ...], Field(min_length=1, max_length=109)]
