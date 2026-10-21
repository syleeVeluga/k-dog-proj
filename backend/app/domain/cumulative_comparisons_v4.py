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


AGGREGATION_VERSION = "cumulative-comparison-20261021-cm-1"
MetricId = Literal["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09"]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Display = Annotated[str, Field(pattern=r"^\d+\.\d{2}$")]
Comparison = Literal["higher", "lower", "equal_display"]
Exclusion = Literal["excluded", "representative_unconfirmed", "version_unconfirmed"]


class CumulativeReferenceV4(FileV4):
    snapshot_id: Text


class MemberMetricV4(ContractV4):
    metric_id: MetricId
    status: Literal["valid", "insufficient", "input_check"]
    numerator: Annotated[int, Field(ge=0)] | None
    denominator: Annotated[int, Field(ge=1)] | None


class CumulativeMemberV4(ContractV4):
    pair_id: Text
    state: PairStateReferenceV4
    submission: SubmissionReferenceV4
    case_id: Text
    session_id: Text
    input_revision: Revision
    input: InputPointerV4
    metrics: tuple[MemberMetricV4, ...]


class CumulativeExclusionV4(ContractV4):
    pair_id: Text
    state: PairStateReferenceV4
    reason: Exclusion


class CumulativeMetricV4(ContractV4):
    metric_id: MetricId
    question_ids: tuple[Text, ...]
    numerator: Annotated[int, Field(ge=0)]
    denominator: Annotated[int, Field(ge=0)]
    n: Annotated[int, Field(ge=0)]
    mean: Finite | None
    display: Display | None
    included_pair_ids: tuple[Text, ...]
    response_excluded: dict[str, Literal["insufficient", "input_check"]]

    @model_validator(mode="after")
    def exact(self) -> Self:
        if self.n != len(self.included_pair_ids) or self.denominator != self.n * len(self.question_ids):
            raise ValueError("cumulative n counts pairs with a complete metric; denominator counts their answers")
        if bool(self.n) != (self.mean is not None and self.display is not None):
            raise ValueError("an empty cumulative metric has a null mean, never zero")
        return self


class CumulativeSnapshotV4(ContractV4):
    """Admission-time representative set; retries and downloads re-verify it but never re-select."""
    artifact_kind: Literal["comparison-cumulative"] = "comparison-cumulative"
    snapshot_id: Text
    aggregation_version: Literal["cumulative-comparison-20261021-cm-1"] = AGGREGATION_VERSION
    request_id: Text
    actor: Text
    recorded_at: Text
    case_id: Text
    session_id: Text
    mapping_version: Text
    mapping_hash: Hash
    question_signature: Hash
    survey_assets: dict[str, Hash]
    pair_heads: tuple[PairStateReferenceV4, ...]
    members: tuple[CumulativeMemberV4, ...]
    exclusions: tuple[CumulativeExclusionV4, ...]
    metrics: tuple[CumulativeMetricV4, ...]

    @model_validator(mode="after")
    def complete(self) -> Self:
        if tuple(item.metric_id for item in self.metrics) != tuple(f"S{n:02}" for n in range(1, 10)):
            raise ValueError("a cumulative snapshot pins all nine metrics")
        pairs = [item.pair_id for item in (*self.members, *self.exclusions)]
        if len(set(pairs)) != len(pairs) or sorted(pairs) != sorted(head.pair_id for head in self.pair_heads):
            raise ValueError("each pair head contributes once or records its exclusion")
        return self


class ComparisonRowV4(ContractV4):
    """One renderer-ready metric row; HTML, PDF and exports never recompute it."""
    metric_id: MetricId
    alias: Literal["SF", "NF"] | None
    title: Text
    question_ids: tuple[Text, ...]
    scale_minimum: int
    scale_maximum: int
    direction: Text
    individual_status: Literal["valid", "insufficient", "input_check", "version_check"]
    individual_raw: Finite | None
    individual_display: Display | None
    individual_numerator: int | None
    individual_denominator: int | None
    cumulative_n: Annotated[int, Field(ge=0)]
    cumulative_raw: Finite | None
    cumulative_display: Display | None
    cumulative_numerator: Annotated[int, Field(ge=0)]
    cumulative_denominator: Annotated[int, Field(ge=0)]
    cumulative_shown: bool
    cumulative_comparison: Comparison | None
    cumulative_sentence: Text | None
    external_status: Literal["not_mapped", "not_ready", "individual_unavailable", "ready"]
    external_reason: Text | None
    external_source_id: Text | None
    external_mean: Finite | None
    external_display: Display | None
    external_standard_deviation: Finite | None
    external_valid_n: int | None
    external_total_n: int | None
    external_literature: Text | None
    external_doi: Text | None
    external_comparison: Comparison | None
    external_sentence_id: Literal["TXT-H", "TXT-L", "TXT-E"] | None
    external_sentence: Text | None
    notice_id: Literal["TXT-M", "TXT-V", "TXT-I"] | None
    notice: Text | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        valid = self.individual_status == "valid"
        if valid != (self.individual_display is not None) or valid == (self.notice_id is not None):
            raise ValueError("an invalid individual metric shows a notice instead of values")
        if self.cumulative_shown != (valid and self.cumulative_n >= 2) or (self.cumulative_comparison is None) != (not self.cumulative_shown):
            raise ValueError("cumulative markers need a valid individual value and n of at least 2")
        if (self.external_status == "ready") != (self.external_mean is not None) or (self.external_status == "ready") != (self.external_sentence_id is not None):
            raise ValueError("external values appear only for a ready mapped source")
        if self.alias is None and self.external_status != "not_mapped":
            raise ValueError("only SF/NF link a research reference")
        return self


class CumulativePublicV4(ContractV4):
    reference: CumulativeReferenceV4
    aggregation_version: Literal["cumulative-comparison-20261021-cm-1"] = AGGREGATION_VERSION
    mapping_version: Text
    mapping_hash: Hash
    cutoff: Text
    as_of: Text
    included_pairs: Annotated[int, Field(ge=0)]
    exclusion_counts: dict[str, int]
    label: Text
    note: Text
    external_limitation: Text
    rows: tuple[ComparisonRowV4, ...]

    @model_validator(mode="after")
    def nine(self) -> Self:
        if tuple(row.metric_id for row in self.rows) != tuple(f"S{n:02}" for n in range(1, 10)):
            raise ValueError("survey comparison rows cover S01-S09 in order")
        return self
