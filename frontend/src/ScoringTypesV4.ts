import type { Session, SegmentId } from './types';
import type { RecordingV4 } from './recordingTypesV4';

export type BehaviorItemV4 = {
  code: string; text: string; scale_text: string; segment: SegmentId; segment_label: string; axis_label: string;
  usage: 'numeric' | 'memo' | 'automatic'; value_type: 'category' | 'count' | 'memo' | 'automatic';
  allowed_values: number[]; labels: { value: number; text: string }[]; display_order: number[]; category_priority: number[];
  optional: boolean; whole_interval_required: boolean; windows: string[]; policy_pending: string[]; automatic_formula: string | null;
};
export type BehaviorCatalogV4 = { version: string; items: BehaviorItemV4[] };
export type EvidenceV4 = { video_id: string; video_sha256: string; camera_id: string; window_id: string; start_seconds: number | ''; end_seconds: number | ''; observed_seconds: number | ''; note: string };
export type ObservationV4 = {
  code: string; value: number | string | null;
  status: 'observed' | 'unobserved' | 'no_opportunity' | 'not_performed' | 'invalid' | 'insufficient_observation' | 'policy_pending';
  reason: string | null; opportunity: 'present' | 'absent' | 'unknown'; validity: 'valid' | 'caution' | 'invalid' | 'unknown';
  whole_interval_observed: boolean; evidence: EvidenceV4[];
  vocalization: { listened_seconds: number | ''; cumulative_vocal_seconds: number | ''; whole_interval_judged: boolean; note: string } | null;
  review_memo: string | null;
};
export type WalkPhaseV4 = { code: string; proximity_exception: 'none' | 'guardian_approach' | 'recheck' | 'unknown'; evidence: EvidenceV4[]; note: string | null };
export type LinkedMemoV4 = { code: '개59'; text: string; item_codes: string[]; evidence: EvidenceV4[] };
export type SheetReferenceV4 = { sheet_id: string; revision: number; ref: string; hash: string };
export type SheetSummaryV4 = { sheet_id: string; case_id: string; session_id: string; rater_id: string; rater_name: string; assigned_username: string; purpose: 'independent' | 'review' | 'consensus'; state: 'draft' | 'submitted'; revision: number; manifest_ref: string; manifest_hash: string; source_hash: string; active: boolean; own: boolean; rater_kind: 'human' | 'ai' };
export type SheetWindowV4 = { window_id: string; segment: SegmentId; reference_video_id: string; start_seconds: number | null; end_seconds: number | null; status: string; reasons: string[]; event_ids: string[]; source_intervals: { video_id: string; start_seconds: number; end_seconds: number; evidence_id: string | null }[] };
export type SheetDocumentV4 = {
  schema_version: '4.0'; revision: number; state: 'draft' | 'submitted'; assigned_username: string; rater_name: string;
  purpose: SheetSummaryV4['purpose']; origin: 'human_web' | 'ai_service' | 'historical_import'; active: boolean; actor: string; recorded_at: string; change_reason: string; source_hash: string;
  source: { input_revision: number; input: { manifest_ref: string; manifest_hash: string }; asset_hashes: Record<string, string>; session: Session & { recording_s1: RecordingV4 }; windows: SheetWindowV4[]; batch_id: string; preprocess: { ref: string; hash: string; batch_id: string } | null };
  sheet: { sheet_id: string; case_id: string; session_id: string; batch_id: string; rater_id: string; rater_kind: 'human' | 'ai'; ai_exposed: boolean; input_revision: number; input_sha256: string; observations: ObservationV4[]; walk_phases: WalkPhaseV4[]; linked_memos: LinkedMemoV4[] };
  previous: SheetReferenceV4[]; initial_submission: SheetReferenceV4 | null; exposures: SheetReferenceV4[]; ai_run_id: string | null;
};
export type SheetViewV4 = { summary: SheetSummaryV4; document: SheetDocumentV4; grants: SheetReferenceV4[]; outdated: boolean; missing_required_codes: string[]; policy_pending_codes: string[] };
