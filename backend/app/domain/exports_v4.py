"""Explicit S1 research selections and immutable private snapshot/output references."""
from typing import Annotated, Literal
from pydantic import Field
from .catalog_v4 import BehaviorCatalogV4, ContractV4, Hash, Text
from .media_v4 import MediaKey
from .preprocess_v4 import FileV4
from .sheets_v4 import SheetReferenceV4, SheetDocumentV4
from .results_v4 import ResultReferenceV4, BasicResultV4
from .final_results_v4 import FinalReferenceV4, FinalResultV4
from .report_runs_v4 import ReportPublicationV4
from .comparisons_v4 import CohortReferenceV4, CohortPublicV4, ExternalPublicV4
from .validation_data_v4 import ValidationReferenceV4
from ..survey_v4 import SurveyResultV4


class ExportSelectionV4(ContractV4):
    case_id: MediaKey
    session_id: MediaKey
    sheet: SheetReferenceV4
    viewer_sheet_id: MediaKey | None = None
    basic: ResultReferenceV4 | None = None
    final: FinalReferenceV4 | None = None
    report_run_id: MediaKey | None = None


class ExportMemberV4(ContractV4):
    selection: ExportSelectionV4
    sheet: SheetDocumentV4
    basic: BasicResultV4 | None = None
    final: FinalResultV4 | None = None
    report: ReportPublicationV4 | None = None
    report_file: FileV4 | None = None
    pseudonym: Text
    session_alias: Text
    rater_alias: Text


class ExportSnapshotV4(ContractV4):
    artifact_kind: Literal["research-export"] = "research-export"
    export_id: MediaKey
    request_id: MediaKey
    request_hash: Hash
    actor: MediaKey
    created_at: Text
    reason: Text
    format: Literal["csv_zip", "xlsx"]
    members: tuple[ExportMemberV4, ...]
    excluded: tuple[dict, ...] = ()
    references: tuple[ValidationReferenceV4, ...] = ()
    reference_metadata: tuple[dict, ...] = ()
    cohort: CohortPublicV4 | None = None
    external_comparisons: tuple[ExternalPublicV4, ...] = Field(default=(), exclude_if=lambda value: not value)
    parent_files: tuple[FileV4, ...]
    catalog: BehaviorCatalogV4
    surveys: tuple[SurveyResultV4, ...]
    asset_hashes: dict[str, Hash]
    redactions: tuple[Text, ...] = ()
    output: FileV4 | None = None
    version: Literal["research-export-20261002-s1.1-1"] = "research-export-20261002-s1.1-1"
