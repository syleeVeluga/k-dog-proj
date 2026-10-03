import type { RecordingV4, RecordingWindowV4 } from './recordingTypesV4';

export type FileV4 = { schema_version: '4.0'; ref: string; hash: string };
export type TimeRangeV4 = { start_seconds: number; end_seconds: number };
export type PreprocessRequestV4 = {
  request_id: string; expected_revision: number; camera_priority: string[]; audio_video_id: string | null;
  ai_frames_per_second: 1; reuse: FileV4 | null;
};
export type ClipFileV4 = FileV4 & {
  size_bytes: number; duration_seconds: number; source_time_offset_seconds: number;
  frame_times_seconds: number[]; source_frame_times_seconds: number[]; audio_ranges: TimeRangeV4[];
  fps_policy: 'source_frames' | 'one_actual_frame_per_second';
};
export type PhysicalClipV4 = {
  clip_id: string; video_id: string; camera_id: string; source_start_seconds: number; source_end_seconds: number;
  offset_seconds: number; window_ids: string[]; status: 'complete' | 'partial' | 'failed' | 'no_frames';
  reason: string | null; original: ClipFileV4 | null; ai: ClipFileV4 | null;
};
export type ViewWindowV4 = {
  video_id: string; camera_id: string | null; offset_seconds: number | null; source_start_seconds: number | null;
  source_end_seconds: number | null; clip_ids: string[];
  availability: 'available' | 'partial' | 'missing' | 'offset_unconfirmed' | 'camera_unassigned' | 'conversion_required' | 'failed' | 'no_frames';
  visual_state: 'unobserved' | 'whole_observed' | 'partial_observed' | 'occluded' | 'body_unobserved';
  visual_ranges: TimeRangeV4[]; audio_ranges: TimeRangeV4[]; reasons: string[]; quality_event_ids: string[];
};
export type WindowV4 = {
  window: RecordingWindowV4 & { reference_video_id: string; source_intervals: (TimeRangeV4 & { video_id: string; evidence_id: string | null })[] };
  item_codes: string[]; views: ViewWindowV4[]; media_available_seconds: number;
  representative_audio_video_id: string | null; audio_selection_reason: string; audio_available_seconds: number;
  audio_loss_ranges: TimeRangeV4[]; audio_listened_seconds: null; vocal_seconds: null;
};
export type BatchV4 = {
  schema_version: '4.0'; artifact_kind: 'preprocess-batch'; batch_id: string; claim_token: string;
  case_id: string; session_id: string; input_revision: number; input: FileV4; created_at: string;
  status: 'complete' | 'partial'; request: PreprocessRequestV4; compatibility_hash: string; asset_hashes: Record<string, string>;
  cut_settings: Record<string, unknown>; encoder_version: string; source_files: FileV4[];
  source_metadata: { video_id: string; original_name: string; camera_id?: string; sha256: string; storage_ref: string; source_kind?: string }[];
  recording: RecordingV4; clips: PhysicalClipV4[]; windows: WindowV4[]; reuse_manifest: FileV4 | null;
  camera_layout_status: 'provisional_D01';
};
export type PreprocessStatusV4 = {
  case_id: string; session_id: string; input_revision: number; ready: boolean;
  status: 'not_ready' | 'ready' | 'running' | 'interrupted' | 'failed' | 'complete' | 'partial';
  message: string; outdated: boolean; result_pointer: FileV4 | null; result: BatchV4 | null;
};
