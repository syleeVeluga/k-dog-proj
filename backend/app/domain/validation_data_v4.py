"""Explicit correspondence and provenance for reference-only customer comparison files."""
from typing import Annotated, Literal
from pydantic import Field, JsonValue, model_validator
from .catalog_v4 import ContractV4, Hash, Text
from .media_v4 import MediaKey
from .preprocess_v4 import FileV4


class ReferenceBindingV4(ContractV4):
    source_subject: Text
    case_id: MediaKey
    session_id: MediaKey
    expected_revision: Annotated[int, Field(ge=1)]
    match_basis: Literal["stable_id", "explicit_alias", "operator_verified"]
    reason: Text
    participation: Literal["active", "withdrawn", "unknown"] = "unknown"


class ReferenceSelectionV4(ContractV4):
    source_subject: Text
    sheet: Text
    cell: Annotated[str, Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")]
    code: Text
    window_id: Text | None = None
    source_edition: Text
    evaluator: Text | None = None
    evaluator_status: Literal["unknown", "identified"] = "unknown"
    confirmation: Literal["unconfirmed", "human_confirmed", "recheck_required", "ai_provisional", "example", "legacy_semantics", "unobserved"] = "unconfirmed"
    exposure: Literal["unknown", "independent_claimed", "ai_exposed", "human_exposed"] = "unknown"
    reason: Text

    @model_validator(mode="after")
    def identified(self):
        if (self.evaluator_status == "identified") != (self.evaluator is not None):
            raise ValueError("identified evaluator requires explicit evaluator text")
        return self


class ReferenceCellV4(ContractV4):
    sheet: Text
    cell: Text
    raw_type: Text
    raw_xml_value: str | None
    value: JsonValue
    formula: str | None
    formula_attributes: dict[str, str]
    cached_value: JsonValue
    cache_present: bool


class ReferenceRowV4(ContractV4):
    selection: ReferenceSelectionV4
    source: ReferenceCellV4
    effective_status: Text
    exclusion_reasons: tuple[Text, ...]
    independent_ground_truth: Literal[False] = False
    current_s1_score: Literal[False] = False


class ValidationReferenceV4(FileV4):
    validation_id: MediaKey


class ValidationDocumentV4(ContractV4):
    artifact_kind: Literal["validation-reference"] = "validation-reference"
    validation_id: MediaKey
    request_id: MediaKey
    request_hash: Hash
    actor: MediaKey
    recorded_at: Text
    filename: Text
    source: FileV4
    source_inventory_id: Text | None = None
    bindings: tuple[ReferenceBindingV4, ...]
    cells: tuple[ReferenceCellV4, ...]
    rows: tuple[ReferenceRowV4, ...]
    reference_only: Literal[True] = True
    score_import_enabled: Literal[False] = False
    formula_recalculated: Literal[False] = False
    ground_truth_status: Literal["pending_G03"] = "pending_G03"
