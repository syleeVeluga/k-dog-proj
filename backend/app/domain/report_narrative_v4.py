"""Evidence-linked text generation; numeric facts and final choices stay program-owned."""
from typing import Annotated, Literal
from pydantic import Field
from .catalog_v4 import ContractV4, Hash, Text

NARRATIVE_VERSION = "report-narrative-20261007-rp03"


class NarrativeClaimV4(ContractV4):
    text: Annotated[Text, Field(max_length=300)]
    fact_ids: Annotated[tuple[Text, ...], Field(min_length=1, max_length=12)]


class NarrativeCardV4(ContractV4):
    key: Literal["education_attitude", "attachment", "social", "walking"]
    claims: Annotated[tuple[NarrativeClaimV4, ...], Field(min_length=1, max_length=2)]


class NarrativeResponseV4(ContractV4):
    input_hash: Hash
    instruction_version: Literal["report-narrative-20261007-rp03"]
    instruction_hash: Hash
    cards: Annotated[tuple[NarrativeCardV4, ...], Field(min_length=4, max_length=4)]
    details: Annotated[tuple[NarrativeClaimV4, ...], Field(max_length=6)]
    summary: Annotated[tuple[NarrativeClaimV4, ...], Field(min_length=1, max_length=3)]
    actions: Annotated[tuple[NarrativeClaimV4, ...], Field(max_length=3)]


class NarrativeAssessmentV4(ContractV4):
    model: Literal["gemini-3.8-flash"]
    instruction_snapshot: dict
    response: NarrativeResponseV4
