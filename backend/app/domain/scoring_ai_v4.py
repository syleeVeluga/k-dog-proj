"""Provider-local S1 observations. Source identities/timestamps are assigned by the app."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .catalog_v4 import ContractV4, ItemCode, Text
from .media_v4 import MediaKey


class LocalEvidenceV4(ContractV4):
    clip_id: MediaKey
    window_id: Text
    start_seconds: Annotated[float, Field(ge=0)]
    end_seconds: Annotated[float, Field(ge=0)]
    observed_seconds: Annotated[float, Field(ge=0)]
    note: Text

    @model_validator(mode="after")
    def time(self) -> Self:
        if self.end_seconds < self.start_seconds or self.observed_seconds > self.end_seconds-self.start_seconds:
            raise ValueError("local observation amount exceeds its actual range")
        return self


class LocalEventV4(ContractV4):
    event_id: MediaKey
    item_codes: tuple[ItemCode, ...]
    views: Annotated[tuple[LocalEvidenceV4, ...], Field(min_length=1)]
    note: Text


class LocalVocalizationV4(ContractV4):
    listened_seconds: Annotated[float, Field(gt=0)]
    cumulative_vocal_seconds: Annotated[float, Field(ge=0)]
    whole_interval_judged: bool
    note: Text


class AiRowV4(ContractV4):
    code: ItemCode
    value: int | str | None
    status: Literal["observed", "unobserved", "no_opportunity", "not_performed", "invalid", "insufficient_observation", "policy_pending"]
    reason: Text | None = None
    opportunity: Literal["present", "absent", "unknown"] = "unknown"
    validity: Literal["valid", "caution", "invalid", "unknown"] = "unknown"
    whole_interval_observed: bool = False
    evidence: tuple[LocalEvidenceV4, ...] = ()
    event_ids: tuple[MediaKey, ...] = ()
    vocalization: LocalVocalizationV4 | None = None


class LocalLinkedMemoV4(ContractV4):
    text: Text
    item_codes: tuple[ItemCode, ...]
    evidence: Annotated[tuple[LocalEvidenceV4, ...], Field(min_length=1)]


class AiResponseV4(ContractV4):
    case_id: MediaKey
    session_id: MediaKey
    batch_id: MediaKey
    observations: tuple[AiRowV4, ...]
    events: tuple[LocalEventV4, ...] = ()
    linked_memos: tuple[LocalLinkedMemoV4, ...] = ()
