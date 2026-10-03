import type { ActualEvent, CaptureWindow, SegmentId, WalkPhase } from './types';

export type CoverageV4 = {
  evidence_id: string; window_id: string; video_id: string; start_seconds: number | null; end_seconds: number | null;
  observed_seconds: number | null; coverage: 'whole' | 'partial' | 'none'; modality: 'visual' | 'audio'; note: string;
};
export type TailV4 = {
  code: '바54' | '바55'; event_id: string; first_clear_confirmed: boolean; same_posture: boolean | null;
  same_movement: boolean | null; tail_visible_before: boolean | null; tail_visible_after: boolean | null; note: string;
};
export type MemoV4 = { code: '개59'; memo_id: string; text: string; item_codes: string[]; event_ids: string[] };
export type RecordingV4 = {
  schema_version?: '4.0'; protocol_version?: 'protocol-20261002-s1.1';
  procedure_edition: 's1_confirmed' | 'legacy' | 'unconfirmed'; procedure_note: string; video_id: string; confirmed: boolean;
  segments: CaptureWindow[];
  walk_phases: (WalkPhase & { proximity_exception: 'none' | 'guardian_approach' | 'recheck' | 'unknown'; proximity_note: string | null })[];
  events: ActualEvent[];
  video_offsets: { video_id: string; offset_seconds: number | null; confirmed: boolean; note: string }[];
  coverage: CoverageV4[]; tail_selections: TailV4[]; linked_memos: MemoV4[];
  safe_base_sequence: { approach_event_id: string | null; contact_event_id: string | null; exploration_event_id: string | null; note: string } | null;
};
export type RecordingWindowV4 = {
  window_id: string; segment: SegmentId; start_seconds: number | null; end_seconds: number | null; status: string;
  reasons: string[]; whole_visual_observed: boolean; whole_audio_observed: boolean; event_ids: string[];
};
export type RecordingViewV4 = {
  recording: RecordingV4 | null; windows: RecordingWindowV4[];
  gates: { code: string; window_ids: string[]; status: string; reasons: string[] }[];
};
export const WINDOW_NAMES: Record<string, string> = {
  entry_whole: '입장 전체', baseline_whole: '기준 전체', alone_whole: '혼자 전체', reunion_whole: '재회 전체',
  ignore_whole: '무시 전체', walk_whole: '걷기 전체', stranger_whole: '낯선 사람 전체', exit_whole: '퇴장 전체',
  alone_initial: '혼자 처음 10초', alone_later: '혼자 10초 이후', reunion_approach: '재회 처음 15초', reunion_later: '재회 15초 이후',
  stranger_gate: '요원 문 밖 대기', stranger_approach: '요원 실제 접근', stranger_call: '요원 실제 부름 뒤',
  entry_free: '입장 자유 이동', entry_object: '입장 물건 통과', exit_free: '퇴장 자유 이동', exit_object: '퇴장 물건 통과',
  reunion_contact: '재회 실제 접촉', reunion_tail_event: '재회 꼬리 변화', stranger_contact: '요원 실제 접촉',
  stranger_tail_event: '요원 꼬리 변화', stranger_exit: '요원 실제 퇴장', separation_departure: '보호자 나가기 준비',
  walk_phase_1: '걷기 이동1', walk_phase_2: '걷기 정지1', walk_phase_3: '걷기 이동2',
  walk_phase_4: '걷기 정지2', walk_phase_5: '걷기 이동3', walk_phase_6: '걷기 정지3',
};
export const EVENT_CHOICES: [string, string, SegmentId | null][] = [
  ['floor_contact', '바닥 첫 접촉', 'entry'], ['object_near', '물건 가까이 진입', 'entry'], ['object_stop', '물건 앞 실제 정지', 'entry'],
  ['object_passage', '물건 통과 구간', 'entry'], ['object_contact', '물건 접촉', 'entry'], ['object_removed', '물건 제거', null],
  ['free_movement', '자유 이동 구간', 'entry'], ['guardian_speech', '보호자 말', null], ['guardian_gesture', '보호자 손짓', null],
  ['guardian_departure_preparation', '보호자 나가기 준비', null], ['guardian_fully_outside', '보호자가 완전히 문 밖으로 나감', null],
  ['staff_signal', '직원 신호', null], ['staff_stop', '직원 중단 신호', null], ['food', '먹이 제공', null], ['route_deviation', '경로 이탈', null],
  ['occlusion', '영상 가림', null], ['body_not_visible', '신체 미관찰', null], ['audio_loss', '오디오 손상·소실', null],
  ['external_stimulus', '외부 자극', null], ['welfare_stop', '복지 중단', null], ['welfare_action', '중단 뒤 조치', null],
  ['reunion_name', '재회 실제 부름', 'reunion'], ['reunion_contact_start', '재회 실제 접촉 시작', 'reunion'], ['reunion_contact_end', '재회 실제 접촉 끝', 'reunion'],
  ['reunion_head_turn', '재회 첫 명확한 고개 전환', 'reunion'], ['reunion_check', '재회 보호자 확인', 'reunion'],
  ['stranger_gate_wait', '요원 안전문 밖 대기', 'stranger'], ['stranger_enter', '요원 입실', 'stranger'], ['stranger_approach', '요원 실제 접근', 'stranger'],
  ['stranger_name', '요원 실제 부름', 'stranger'], ['stranger_contact_start', '요원 실제 접촉 시작', 'stranger'], ['stranger_contact_end', '요원 실제 접촉 끝', 'stranger'],
  ['stranger_wait', '요원 실제 대기', 'stranger'], ['stranger_exit', '요원 실제 퇴장', 'stranger'], ['stranger_head_turn', '요원 첫 명확한 고개 전환', 'stranger'],
  ['walk_name', '걷기 전 이름', null], ['walk_to_s_start', 'S로 이동 시작', null], ['walk_to_s_end', 'S로 이동 끝', null],
  ['walk_seated', '걷기 뒤 착석', null], ['transition_wait_start', '전환 대기 시작', null], ['transition_wait_end', '전환 대기 끝', null],
  ['leash_attach', '목줄 채우기', null], ['body_scratch', '몸 긁기', null], ['body_shake', '몸 털기', null],
  ['guardian_approach', '안전기지: 보호자 접근', null], ['guardian_contact', '안전기지: 보호자 접촉', null], ['exploration_resumed', '안전기지: 탐색 재개', null],
];
