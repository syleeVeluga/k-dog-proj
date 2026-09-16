export type Role = 'operator' | 'reviewer' | 'admin' | 'developer';
export type User = { username: string; role: Role; active: boolean };
export type Run = (work: () => Promise<void>) => Promise<void>;
export const roleNames: Record<Role, string> = { operator: '운영자', reviewer: '교수 / 검토자', admin: '운영 관리자', developer: '개발자' };
export const formFields = (form: HTMLFormElement) => Object.fromEntries(new FormData(form));
export type Video = {
  video_id: string; original_name: string;
  size_bytes: number; sha256: string; media_status: 'pending_probe';
};
export type Session = {
  session_id: string; note: string;
  survey_version: string; survey: Record<string, number | null>; survey_not_applicable: string[]; videos: Video[];
};
export type DogProfile = {
  breed: string; sex: '암' | '수' | '중성화' | '미기재'; age_years: number | null;
  size: '소형' | '중형' | '대형' | '미기재'; years_together: string; adoption_route: '분양' | '입양' | '기타' | '미기재';
};
export const sexOptions: DogProfile['sex'][] = ['미기재', '암', '수', '중성화'];
export const sizeOptions: DogProfile['size'][] = ['미기재', '소형', '중형', '대형'];
export const adoptionOptions: DogProfile['adoption_route'][] = ['미기재', '분양', '입양', '기타'];
export type Case = {
  analysis_status: string;
  case_id: string; event_id: string; participant_id: string; dog_name: string;
  reservation_at: string; sequence_no: number | null; consent_confirmed: boolean; guardian_name: string; dog: DogProfile;
  input_revision: number; selected_session_id: string;
  deletion_requested: boolean;
  manifest: { sessions: Session[]; display_run_id: string | null; migration_note?: string | null };
};
export const sessionOf = (item: Case) => item.manifest.sessions.find(s => s.session_id === item.selected_session_id)!;
export type SurveyItem = { item_id: string; number: number; text: string; domain: 'A' | 'B' | 'C' | 'D' | 'E'; allows_not_applicable: boolean };
export type Catalog = { version: string; response_scale: string[]; items: SurveyItem[] };
export const surveyDomains: Record<SurveyItem['domain'], string> = {
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
  survey: { expected_revision: number; answers: Record<string, number | null>; not_applicable: string[] } | null;
};
export type Preview = { rows: ImportRow[]; errors: string[] };
