import type { SheetReferenceV4 } from './ScoringTypesV4';
import type { BasicReferenceV4, FinalReferenceV4 } from './finalTypesV4';

export type ReferenceCellV4 = { sheet: string; cell: string; raw_type: string; raw_xml_value: string | null; value: unknown; formula: string | null; formula_attributes: Record<string, string>; cached_value: unknown; cache_present: boolean };
export type ReferenceSelectionV4 = { source_subject: string; sheet: string; cell: string; code: string; window_id: string | null; source_edition: string; evaluator: string | null; evaluator_status: 'unknown' | 'identified'; confirmation: 'unconfirmed' | 'human_confirmed' | 'recheck_required' | 'ai_provisional' | 'example' | 'legacy_semantics' | 'unobserved'; exposure: 'unknown' | 'independent_claimed' | 'ai_exposed' | 'human_exposed'; reason: string };
export type ReferenceBindingV4 = { source_subject: string; case_id: string; session_id: string; expected_revision: number; match_basis: 'stable_id' | 'explicit_alias' | 'operator_verified'; reason: string; participation: 'active' | 'withdrawn' | 'unknown' };
export type ReferenceRowV4 = { selection: ReferenceSelectionV4; source: ReferenceCellV4; effective_status: string; exclusion_reasons: string[]; independent_ground_truth: false; current_s1_score: false };
export type ValidationReferenceV4 = { validation_id: string; ref: string; hash: string };
export type ValidationSummaryV4 = { reference: ValidationReferenceV4; filename: string; actor: string; source_inventory_id: string | null; row_count: number; mapped_subject_count: number; reference_only: true; score_import_enabled: false; ground_truth_status: 'pending_G03' };
export type ValidationViewV4 = ValidationSummaryV4 & { document: { filename: string; source: { ref: string; hash: string }; recorded_at: string; bindings: ReferenceBindingV4[]; rows: ReferenceRowV4[]; formula_recalculated: false } };
export type WorkbookViewV4 = { source_sha256: string; sheets: string[]; cells: ReferenceCellV4[]; profile: Record<string, unknown> };
export type ValidationPreviewV4 = { source_sha256: string; source_inventory_id: string | null; rows: ReferenceRowV4[]; bindings: ReferenceBindingV4[] };
export type ExportMemberSelectionV4 = { case_id: string; session_id: string; sheet: SheetReferenceV4; viewer_sheet_id: string | null; basic: BasicReferenceV4 | null; final: FinalReferenceV4 | null; report_run_id: string | null };
export type ExportViewV4 = { export_id: string; format: 'csv_zip' | 'xlsx'; created_at: string; member_count: number; excluded_count: number; snapshot_sha256: string; output_sha256: string; status: 'ready' };
