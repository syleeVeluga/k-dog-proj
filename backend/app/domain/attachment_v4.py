"""Immutable evidence-linked attachment inference, separate from raw scoring."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator
from .catalog_v4 import ContractV4, Hash, Text


class AttachmentResponseV4(ContractV4):
    input_hash: Hash
    instruction_version: Literal["attachment-20261007-rp02"]
    instruction_hash: Hash
    status: Literal["selected", "held"]
    label: Literal["곁에서 안심하는 사이", "가까이 있어도 안심이 어려운 사이", "거리를 두고 지내는 사이", "다가감과 물러섬이 함께 나오는 사이"] | None
    reason: Text
    evidence_refs: tuple[Text, ...]
    counter_evidence_refs: tuple[Text, ...]
    counter_note: Text | None
    hold_reason: Text | None

    @model_validator(mode="after")
    def judgement(self) -> Self:
        if (self.status == "held") != (self.label is None) or (self.status == "held") != bool(self.hold_reason):
            raise ValueError("held attachment requires null type and explicit reason")
        if self.status == "selected" and (not self.evidence_refs or not (self.counter_evidence_refs or self.counter_note)):
            raise ValueError("selected attachment requires support and counter-evidence review")
        refs = (*self.evidence_refs, *self.counter_evidence_refs)
        if len(set(refs)) != len(refs):
            raise ValueError("duplicate or conflicting attachment evidence references")
        return self


class AttachmentAssessmentV4(ContractV4):
    source: Literal["independent_ai", "completed_opinion_inference"]
    model: Literal["gemini-3.8-flash", "program"]
    instruction_snapshot: dict
    response: AttachmentResponseV4


class AttachmentReferenceV4(ContractV4):
    run_id: Text
    ref: Annotated[str, Field(pattern=r"^runs/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/output\.json$")]
    hash: Hash
