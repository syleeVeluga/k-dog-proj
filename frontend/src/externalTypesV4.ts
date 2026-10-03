import type { CohortSelectionV4 } from './comparisonTypesV4';

export type FileReferenceV4 = { schema_version?: '4.0'; ref: string; hash: string };
export type ResearchReferenceV4 = FileReferenceV4 & { confirmation_id: string; revision: number };
export type ExternalReferenceV4 = FileReferenceV4 & { snapshot_id: string; revision: number };
export type ResearchCheckKeyV4 = 'numerical_table' | 'question_equivalence' | 'scale_direction' | 'missing_policy' | 'translation_usage' | 'population_scope';
export type ResearchCheckV4 = { status: 'pending' | 'confirmed' | 'rejected'; note: string; evidence_location: string };
export type ComparisonScopeV4 = { measurement: 'self_report_survey'; survey_version: string; policy_version: string; domain: string; question_ids: string[]; question_text_hash: string; scale_minimum: number; scale_maximum: number; direction: string; aggregation: string; missing_policy: string; population_requirements: Record<string, string> };
export type ResearchDocumentV4 = Record<ResearchCheckKeyV4, ResearchCheckV4> & { source_id: string; source_asset_hash: string; confirmed_by: string; confirmed_at: string; evidence: FileReferenceV4[]; scope: ComparisonScopeV4; reason: string; revision: number; actor: string; recorded_at: string };
export type ExternalValuesV4 = { mean: number; standard_deviation: number; valid_n: number; total_n: number };
export type ResearchInventoryV4 = { asset_hash: string; sources: { source_id: string; title: string; literature: string; doi: string; scope: ComparisonScopeV4; reference_values: ExternalValuesV4; number_provenance: string }[]; confirmations: Record<string, ResearchReferenceV4 | null>; documents: Record<string, ResearchDocumentV4 | null>; activations: Record<string, { revision: number; enabled: boolean; reason: string; recorded_at: string; confirmation: ResearchReferenceV4 | null } | null> };
export type ExternalSummaryV4 = { reference: ExternalReferenceV4; target: CohortSelectionV4; source_ids: string[]; source_titles: string[]; status: 'approved' | 'blocked'; reason: string; recorded_at: string };
export type ExternalPublicV4 = { reference: ExternalReferenceV4; target: CohortSelectionV4; entries: { title: string; literature: string; doi: string; population_scope: string; number_provenance: string; gate: { source_id: string; status: 'approved'; scope: ComparisonScopeV4; confirmation: ResearchReferenceV4; activation_revision: number; values: ExternalValuesV4 }; local_mean: number; local_n: number }[] };
