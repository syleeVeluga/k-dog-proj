import type { RecordingV4 } from './recordingTypesV4';

export type Role = 'operator' | 'reviewer' | 'admin' | 'developer';
export type User = { username: string; role: Role; active: boolean };
export type Run = (work: () => Promise<void>) => Promise<void>;
export const roleNames: Record<Role, string> = { operator: '운영자', reviewer: '교수 / 검토자', admin: '운영 관리자', developer: '개발자' };
export const formFields = (form: HTMLFormElement) => Object.fromEntries(new FormData(form));
export type Video = {
  video_id: string; original_name: string;
  size_bytes: number; sha256: string; media_status: 'pending_probe' | 'storage_only';
  upload_id?: string; camera_id?: string; source_original_number?: string | null;
  source_kind?: 'original' | 'received_conversion' | 'app_derived';
};
export type SegmentId = 'entry' | 'baseline' | 'alone' | 'stranger' | 'reunion' | 'ignore' | 'walk' | 'exit';
// Procedure order and Korean labels (01 §2); the backend contract fixes the same order.
export const SEGMENTS: [SegmentId, string][] = [['entry', '입장'], ['baseline', '기준'], ['alone', '혼자'], ['stranger', '낯선 사람'], ['reunion', '재회'], ['ignore', '무시'], ['walk', '걷기'], ['exit', '퇴장']];
export type SegmentWindow = { segment: SegmentId; start_sec: number; end_sec: number };
export type SegmentTimes = { video_id: string; confirmed: boolean; windows: SegmentWindow[] };
export const STIMULI = [['entry', '낯선 바닥 첫 접촉'], ['alone', '보호자 퇴실 동작'], ['stranger', '낯선 사람 입장'], ['reunion', '재회 접촉']] as const;
export type StimulusMoments = Record<typeof STIMULI[number][0], number | null>;
export type StimulusTimes = { video_id: string; input_revision: number; source: 'operator_confirmed'; moments: StimulusMoments };
export type Session = {
  session_id: string; note: string;
  survey_version: string; survey: Record<string, number | null>; survey_not_applicable: string[]; videos: Video[];
  segments: SegmentTimes | null;
  stimuli: StimulusTimes | null;
  recording: RecordingV3 | null;
  recording_s1?: RecordingV4 | null;
  protocol_version: 'protocol-20261002-s1.1' | 'protocol-20260929-v3' | 'protocol-20260913-v2' | 'unconfirmed';
  scoring_catalog_version?: 'catalog-20261002-s1.1';
  recording_review_required?: boolean;
  protocol_source: 'new_session' | 'confirmed_v2_recording' | 'unconfirmed';
  survey_blank_reasons: Record<string, string>;
};
export const protocolName = (session: Session) => session.protocol_version === 'protocol-20261002-s1.1' ? 'S1.1 · 10월 2일' : session.protocol_version === 'protocol-20260929-v3' ? '9월 29일' : session.protocol_version === 'protocol-20260913-v2' ? '9월 13일' : '촬영 판본 미확인';
export type ConsentState = 'unknown' | 'declined' | 'confirmed';
export type Consents = { analysis_feedback: ConsentState; stranger_contact: ConsentState };
export const consentNames: Record<ConsentState, string> = { unknown: '미확인', declined: '거절', confirmed: '확인' };
export const segmentState = (session: Session): 'none' | 'draft' | 'confirmed' => session.scoring_catalog_version === 'catalog-20261002-s1.1' ? !session.recording_s1 ? 'none' : session.recording_s1.confirmed ? 'confirmed' : 'draft' : session.recording ? session.recording.confirmed ? 'confirmed' : 'draft' : !session.segments ? 'none' : session.segments.confirmed ? 'confirmed' : 'draft';
export type DogProfile = {
  breed: string; sex: '암' | '수' | '중성화' | '미기재'; age_years: number | null;
  size: '소형' | '중형' | '대형' | '미기재'; years_together: string; adoption_route: '분양' | '입양' | '기타' | '미기재';
};
export const sexOptions: DogProfile['sex'][] = ['미기재', '암', '수', '중성화'];
export const sizeOptions: DogProfile['size'][] = ['미기재', '소형', '중형', '대형'];
export const adoptionOptions: DogProfile['adoption_route'][] = ['미기재', '분양', '입양', '기타'];
export type Case = {
  case_id: string; event_id: string; participant_id: string; dog_name: string;
  reservation_at: string; sequence_no: number | null; consent_confirmed: boolean; guardian_name: string; dog: DogProfile;
  input_revision: number; selected_session_id: string;
  deletion_requested: boolean;
  consents: Consents;
  scoring_status?: 'reanalysis_required';
  manifest: { schema_version: string; sessions: Session[]; migration_note?: string | null };
};
export const sessionOf = (item: Case) => item.manifest.sessions.find(s => s.session_id === item.selected_session_id)!;
export type SurveyItem = { item_id: string; number: number; text: string; domain?: 'A' | 'B' | 'C' | 'D' | 'E'; print_section?: 'A' | 'B' | 'C' | 'D' | 'E'; report_domain?: string; labels?: { value: number; text: string }[]; allows_not_applicable: boolean };
export type Catalog = { version: string; response_scale?: string[]; items: SurveyItem[] };
export const surveyDomains: Record<string, string> = {
  A: '나의 교육 방식', B: '우리 아이의 사회성', C: '정서적 친밀감', D: '떨어져 있을 때 우리 아이는', E: '나의 감정 기복',
};
export const SURVEY_TOTAL = 28;
// Answered or marked 「해당 없음」 both count as handled; a blank is missing.
export const surveyHandled = (session: Session) =>
  Object.values(session.survey).filter(v => v !== null).length + session.survey_not_applicable.length;
export type ImportRow = {
  row_number: number; source_location: string; session_label: string; changed_questions: string[];
  event_id: string; participant_id: string;
  participant: { event_id: string; participant_id: string; dog_name: string } | null;
  case_id: string | null;
  survey: { expected_revision: number; survey_version: string; blank_reasons: Record<string, string>; answers: Record<string, number | null>; not_applicable: string[] } | null;
};
export type Preview = { rows: ImportRow[]; errors: string[] };
export type SurveyResult = {
  status: 'calculated' | 'partial' | 'unregistered';
  domains: { domain: 'A' | 'B' | 'C' | 'E'; answered_count: number; target_count: number; status: 'calculated' | 'partial' | 'missing' }[];
  separation: { label: string | null; status: 'calculated' | 'missing'; reason: string | null };
  items: { item_id: string; raw: number | null; not_applicable: boolean }[];
};

export type SurveyResultV3 = {
  survey_version: 'survey-20260929-v3'; status: 'calculated' | 'partial' | 'unregistered';
  answered_count: number; blank_reason_count: number; registration_complete: null;
  registration_status: 'unregistered' | 'partial' | 'all_answered' | 'answers_or_reasons_recorded';
  comparison_status: 'pending_policy' | 'insufficient_responses';
  domains: { domain: string; question_ids: string[]; answered_count: number; target_count: number; mean: number | null; denominator: number | null; status: 'calculated' | 'pending_partial' | 'insufficient_responses' | 'missing'; reason: string | null }[];
  standalone: { item_id: string; raw: number | null; blank_reason: string | null };
};

export type SurveyResultV4 = Omit<SurveyResultV3, 'comparison_status' | 'domains'> & {
  policy_version: 'survey-policy-20261002-s1.1' | 'survey-policy-20261007-rp01';
  calculation_status: 'complete' | 'partial' | 'unavailable';
  external_comparison_status: 'pending_approval'; external_comparison_reason: string;
  domains: { domain: string; question_ids: string[]; missing_question_ids: string[]; answered_count: number; target_count: number; mean: number | null; denominator: number | null; aggregation: 'mean' | 'reverse_mean' | 'single_raw'; status: 'calculated' | 'policy_pending' | 'insufficient_responses' | 'missing'; reason: string | null }[];
  items: { item_id: string; raw: number | null; converted: number | null; reverse_scored: boolean; blank_reason: string | null }[];
  pending_policies: string[];
};

export const SEGMENTS_V3: [SegmentId, string][] = [['entry', '입장'], ['baseline', '기준'], ['alone', '혼자'], ['reunion', '재회'], ['ignore', '무시'], ['walk', '걷기'], ['stranger', '낯선 사람'], ['exit', '퇴장']];
export type CaptureState = 'performed' | 'shortened' | 'not_performed' | 'welfare_stopped';
export type CaptureWindow = { segment: SegmentId; video_id: string; state: CaptureState; start_sec: number | null; end_sec: number | null; reason: string | null };
export type WalkPhase = Omit<CaptureWindow, 'segment'> & { phase: string };
export type ActualEvent = { event_id: string; kind: string; video_id: string; segment: SegmentId | null; status: 'observed' | 'not_occurred' | 'unobserved'; seconds: number | null; end_seconds: number | null; note: string; affected_codes: string[] };
export type RecordingV3 = { video_id: string; confirmed: boolean; segments: CaptureWindow[]; walk_phases: WalkPhase[]; events: ActualEvent[]; video_offsets: { video_id: string; offset_seconds: number; confirmed: boolean; note: string }[] };
