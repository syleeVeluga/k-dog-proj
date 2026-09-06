export type Role = 'operator' | 'reviewer' | 'admin' | 'developer';
export type User = { username: string; role: Role; active: boolean };
export type Video = {
  video_id: string; camera_id: string; original_name: string;
  size_bytes: number; sha256: string; media_status: 'pending_probe';
};
export type Session = {
  session_id: string; capture_mode: string; route_note: string;
  survey_version: string; survey: Record<string, number | null>; videos: Video[];
};
export type Case = {
  analysis_status: string;
  case_id: string; event_id: string; participant_id: string; dog_name: string;
  reservation_at: string; input_revision: number; selected_session_id: string;
  deletion_requested: boolean;
  manifest: { sessions: Session[]; display_run_id: string | null };
};
export type Catalog = {
  version: string; response_instructions: string;
  items: { item_id: string; text: string; domain_label: string }[];
};
export type ImportRow = {
  row_number: number;
  event_id: string; participant_id: string;
  participant: { event_id: string; participant_id: string; dog_name: string } | null;
  case_id: string | null;
  survey: { expected_revision: number; answers: Record<string, number | null> } | null;
};
export type Preview = { rows: ImportRow[]; errors: string[] };
