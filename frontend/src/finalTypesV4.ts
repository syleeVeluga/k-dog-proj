import type { BasicResultViewV4 } from './BasicResultsV4';
import type { EvidenceV4 } from './ScoringTypesV4';

export type DomainKeyV4 = 'attachment' | 'education_attitude' | 'people_response' | 'nonsocial_response' | 'environment' | 'tendency';
export const DOMAIN_NAMES_V4: Record<DomainKeyV4, string> = { attachment: '애착', education_attitude: '교육태도', people_response: '사람 반응', nonsocial_response: '비사회적 반응', environment: '환경', tendency: '성향' };
export type BasicReferenceV4 = { result_id: string; revision: number; ref: string; hash: string };
export type OpinionReferenceV4 = { opinion_id: string; revision: number; ref: string; hash: string };
export type FinalReferenceV4 = { final_id: string; ref: string; hash: string };
export type DomainOpinionV4 = { domain: DomainKeyV4; text: string; label: string | null; reason: string; evidence_codes: string[]; counter_codes: string[]; counter_note: string | null; scene_refs: EvidenceV4[] };
export type OpinionDocumentV4 = { opinion_id: string; case_id: string; session_id: string; revision: number; actor: string; recorded_at: string; change_reason: string; policy_version: string; basic: BasicReferenceV4; evaluator: string; completion_requested: boolean; state: 'draft' | 'complete' | 'withdrawn'; completion_issues: string[]; entry_completion_policy: 'pending_G01'; domains: DomainOpinionV4[]; priority_help: string; previous: OpinionReferenceV4[] };
export type OpinionViewV4 = { reference: OpinionReferenceV4 | null; document: OpinionDocumentV4 | null; selection_issues: Record<string, string | null> };
export type OpinionMetadataV4 = { reference: OpinionReferenceV4 | null; actor: string | null; state: string | null; basic: BasicReferenceV4 | null; requires_reveal: boolean };
export type FinalDomainV4 = { domain: DomainKeyV4; label: string | null; text: string | null; source: 'completed_opinion' | 'manual_selection' | 'basic'; status: string; reason: string; evidence_codes: string[]; counter_codes: string[]; counter_note: string | null; original_label: string | null; opinion_revision: number | null };
export type FinalDocumentV4 = { final_id: string; case_id: string; session_id: string; actor: string; recorded_at: string; change_reason: string; policy_version: string; basic: BasicReferenceV4; basic_document: BasicResultViewV4['document']; opinion: OpinionReferenceV4 | null; opinion_document: OpinionDocumentV4 | null; domains: FinalDomainV4[]; priority_help: string | null; independent_ai: boolean; interpretation_policy: 'D04_pending' };
export type FinalViewV4 = { reference: FinalReferenceV4; document: FinalDocumentV4 };
export type FinalSummaryV4 = { reference: FinalReferenceV4; recorded_at: string; actor: string; basic: BasicReferenceV4; opinion: OpinionReferenceV4 | null; requires_reveal: boolean };
export type BasicSummaryV4 = BasicResultViewV4['summary'];
