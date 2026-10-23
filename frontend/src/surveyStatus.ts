import type { Session } from './types';
import { SURVEY_TOTAL } from './types';

// 수치 응답, 해당 없음, 사유를 기록한 빈칸을 중복 없이 구분한다. 완료 판정은 하지 않는다.
export function surveyStatus(session: Session) {
  const answered = Object.values(session.survey).filter(value => value !== null).length;
  const notApplicable = new Set(session.survey_not_applicable);
  const withReason = Object.entries(session.survey_blank_reasons ?? {}).filter(([id, reason]) =>
    session.survey[id] == null && !notApplicable.has(id) && reason.trim()).length;
  return { answered, notApplicable: notApplicable.size, withReason,
    unexplained: Math.max(0, SURVEY_TOTAL - answered - notApplicable.size - withReason) };
}
