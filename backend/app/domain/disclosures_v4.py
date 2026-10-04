"""Interpretation disclosures are distinct from raw-sheet score disclosures."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .catalog_v4 import ContractV4, Hash, Text
from .media_v4 import MediaKey


class InterpretationReferenceV4(ContractV4):
    kind: Literal["opinion", "final"]
    document_id: MediaKey
    revision: Annotated[int, Field(ge=1)] | None
    ref: Text
    hash: Hash

    @model_validator(mode="after")
    def document_kind(self) -> Self:
        prefix = "opinions/" if self.kind == "opinion" else "finals/"
        if not self.ref.startswith(prefix) or not self.ref.endswith(".json") or "\\" in self.ref or ".." in self.ref.split("/"):
            raise ValueError("interpretation reference must identify its document kind")
        if (self.kind == "opinion") != (self.revision is not None):
            raise ValueError("only opinions have numbered revisions")
        return self


class InterpretationExposureV4(ContractV4):
    exposure_id: MediaKey
    target: InterpretationReferenceV4
    case_id: MediaKey
    session_id: MediaKey
    source_actor: MediaKey
    viewer_username: MediaKey
    viewer_rater_id: MediaKey
    basic_result_id: MediaKey
    basic_revision: Annotated[int, Field(ge=1)]
    basic_ref: Annotated[str, Field(pattern=r"^results/[^\\]+\.json$")]
    basic_hash: Hash
    video_hashes: Annotated[tuple[Hash, ...], Field(min_length=1)]
    recorded_at: Text
    reason: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
