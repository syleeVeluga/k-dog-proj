"""Explicit participation pairs, representative survey submissions and pinned cumulative snapshots."""
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .catalog_v4 import ContractV4, Hash, Text
from .preprocess_v4 import FileV4
from .sheets_v4 import InputPointerV4

Revision = Annotated[int, Field(ge=1)]
SubmissionKind = Literal["first", "correction", "revisit"]
PairAction = Literal["create", "link", "unlink", "first", "correction", "exclude", "include"]


class SubmissionReferenceV4(FileV4):
    submission_id: Text


class PairStateReferenceV4(FileV4):
    pair_id: Text
    revision: Revision


class SubmissionV4(ContractV4):
    """One explicit survey submission fact; the raw responses stay in the pinned input manifest."""
    artifact_kind: Literal["comparison-survey-submission"] = "comparison-survey-submission"
    submission_id: Text
    pair_id: Text
    case_id: Text
    session_id: Text
    input_revision: Revision
    input: InputPointerV4
    survey_version: Literal["survey-20260929-v3"]
    policy_version: Literal["survey-policy-20261007-rp01"]
    mapping_version: Text
    question_signature: Hash
    kind: SubmissionKind
    evidence: Text
    submitted_at: Text | None = None
    replaces: SubmissionReferenceV4 | None = None
    actor: Text
    recorded_at: Text

    @model_validator(mode="after")
    def correction_chain(self) -> Self:
        if (self.kind == "correction") != (self.replaces is not None):
            raise ValueError("only a correction replaces the current representative")
        return self


class PairStateV4(ContractV4):
    """Immutable pair head revision; history is the previous-state chain, never rewritten."""
    artifact_kind: Literal["comparison-pair-state"] = "comparison-pair-state"
    pair_id: Text
    revision: Revision
    case_ids: tuple[Text, ...]
    status: Literal["included", "excluded"]
    status_reason: Text | None = None
    representative: SubmissionReferenceV4 | None = None
    previous: PairStateReferenceV4 | None = None
    action: PairAction
    reason: Text
    actor: Text
    recorded_at: Text

    @model_validator(mode="after")
    def chain(self) -> Self:
        if len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("a case is linked to a pair once")
        if (self.revision == 1) != (self.previous is None) or (self.previous and self.previous.revision != self.revision - 1):
            raise ValueError("pair state revisions form one chain")
        if (self.status == "excluded") != (self.status_reason is not None):
            raise ValueError("an excluded pair records its reason")
        return self


class SubmissionSummaryV4(ContractV4):
    reference: SubmissionReferenceV4
    kind: SubmissionKind
    case_id: Text
    session_id: Text
    input_revision: Revision
    evidence: Text
    submitted_at: Text | None
    actor: Text
    recorded_at: Text
    representative: bool


class PairCaseV4(ContractV4):
    case_id: Text
    event_id: Text
    participant_id: Text
    dog_name: Text
    guardian_name: str


class PairViewV4(ContractV4):
    pair_id: Text
    revision: Revision
    reference: PairStateReferenceV4
    status: Literal["included", "excluded"]
    status_reason: Text | None
    representative_status: Literal["confirmed", "unconfirmed"]
    cases: tuple[PairCaseV4, ...]
    submissions: tuple[SubmissionSummaryV4, ...]
    actor: Text
    recorded_at: Text


class PairInventoryV4(ContractV4):
    case_pair_id: Text | None = None
    pairs: tuple[PairViewV4, ...]
    counts: dict[str, int]
