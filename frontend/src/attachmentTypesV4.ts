import type { GeminiExecutionState } from './GeminiExecution';
export type AttachmentReferenceV4 = { run_id: string; ref: string; hash: string };
export type AttachmentAssessmentV4 = {
  source: 'independent_ai' | 'completed_opinion_inference'; model: string; instruction_snapshot: unknown;
  response: { input_hash: string; instruction_version: string; instruction_hash: string; status: 'selected' | 'held'; label: string | null; reason: string; evidence_refs: string[]; counter_evidence_refs: string[]; counter_note: string | null; hold_reason: string | null };
};
export type AttachmentRunV4 = GeminiExecutionState & { run_id: string; status: string; updated_at: string; reserved_calls: number; judgement_status: string; reference: AttachmentReferenceV4 | null; steps?: (GeminiExecutionState & { attempt: number; status: string; code: string | null; billing_uncertain: boolean; remote_cleanup_pending: boolean; call_reserved: boolean })[] };
