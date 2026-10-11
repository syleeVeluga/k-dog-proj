import type { Case, Progress, Role } from './types';

// 진행 단계 문구는 서버가 계산한 `progress`를 역할에 맞게 풀어 쓴다. 새 판정 규칙은 만들지 않는다.
export type StepState = 'done' | 'current' | 'todo';
export type Step = { key: string; label: string; state: StepState };

const staffSteps = ['recording', 'preprocess', 'scoring', 'final', 'report'] as const;
const stepLabels: Record<string, string> = { recording: '촬영 확정', preprocess: '전처리', scoring: '채점', final: '최종 결과', report: '리포트' };

export const isStaff = (role: Role) => role === 'operator' || role === 'admin';

export function stepsOf(progress: Progress, role: Role): Step[] {
  const keys = isStaff(role) ? [...staffSteps] : ['recording', 'preprocess', 'scoring', 'report'];
  const done: Record<string, boolean> = {
    recording: progress.recording, preprocess: progress.preprocess === 'done' || progress.preprocess === 'outdated',
    scoring: progress.scoring === 'done', final: !!progress.final, report: progress.report,
  };
  let currentTaken = false;
  return keys.map(key => {
    const state: StepState = done[key] ? 'done' : !currentTaken ? 'current' : 'todo';
    if (state === 'current') currentTaken = true;
    return { key, label: key === 'scoring' && !isStaff(role) ? '내 채점' : stepLabels[key], state };
  });
}

export const stageNames: Record<string, string> = {
  recording: '촬영 확정 전', preprocess: '전처리 전', scoring: '채점 중', final: '최종 결과 전', report: '리포트 전', complete: '완료',
};

export function nextAction(item: Case, role: Role): string {
  const progress = item.progress;
  if (!progress) return '확인 중';
  if (isStaff(role)) {
    switch (progress.stage) {
      case 'recording': return progress.videos_total ? '촬영 기록을 확정하세요' : '영상을 연결하고 촬영 기록을 확정하세요';
      case 'preprocess': return progress.preprocess === 'running' ? '전처리 실행 중' : progress.preprocess === 'failed' ? '전처리를 다시 실행하세요' : '전처리를 실행하세요';
      case 'scoring': return !progress.sheets_total ? '평가자를 배정하세요' : `평가자 제출을 기다리는 중 (${progress.sheets_submitted}/${progress.sheets_total})`;
      case 'final': return '최종 결과를 만드세요';
      case 'report': return '리포트를 발급하세요';
      default: return progress.preprocess === 'outdated' ? '입력이 바뀌어 전처리를 다시 할 수 있습니다' : '모든 단계 완료';
    }
  }
  if (progress.stage === 'recording' || progress.stage === 'preprocess') return '운영자가 준비하고 있습니다';
  if (progress.my_sheet === 'none') return '배정된 채점 시트가 없습니다';
  if (progress.my_sheet === 'draft') return '채점을 이어서 하세요';
  return progress.report ? '제출 완료 · 리포트를 조회할 수 있습니다' : '제출 완료';
}

export function ownerText(item: Case, role: Role): string {
  const progress = item.progress;
  if (!progress) return '—';
  if (isStaff(role)) return progress.assigned.length ? progress.assigned.join(', ') : '미배정';
  return progress.my_sheet === 'none' ? '배정 없음' : progress.my_sheet === 'draft' ? '내 시트 작성 중' : '내 시트 제출함';
}

// 「내가 할 일만」: 교수/검토자는 나에게 배정되어 아직 제출하지 않은 시트, 운영자·관리자는 아직 끝나지 않은 참가자.
export function isMine(item: Case, role: Role): boolean {
  const progress = item.progress;
  if (!progress) return false;
  return isStaff(role) ? progress.stage !== 'complete' : progress.my_sheet === 'draft';
}

export function videoCounts(item: Case, sessionIndex?: number): string {
  const session = sessionIndex === undefined ? item.manifest.sessions.find(value => value.session_id === item.selected_session_id) : item.manifest.sessions[sessionIndex];
  const total = session?.videos.length ?? 0;
  const progress = item.progress;
  if (!progress || (session && session.session_id !== item.selected_session_id)) return `${total}개`;
  const kept = total - progress.videos_total;
  return `${total}개 · 사용 가능 ${progress.videos_usable} · 확인 대기 ${progress.videos_total - progress.videos_usable}${kept ? ` · 보관 전용 ${kept}` : ''}`;
}
