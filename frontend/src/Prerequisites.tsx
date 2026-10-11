import type { Route } from './navigation';
import { isStaff } from './progressText';
import type { Case, User } from './types';

type Kind = 'preprocess' | 'scoring' | 'report';
type Need = { label: string; ok: boolean; staffHint: string; reviewerHint: string; go?: { route: Route; label: string } };

// 다음 단계를 시작하려면 무엇이 되어 있어야 하는지 체크리스트로 보여 준다. 새 판정 규칙은 만들지 않고 서버가 계산한 progress와 동의 상태를 그대로 쓴다.
export function Prerequisites({ item, kind, user, goTo }: { item: Case; kind: Kind; user: User; goTo: (route: Route) => void }) {
  const progress = item.progress;
  if (!progress) return null;
  const staff = isStaff(user.role);
  const needs: Need[] = [
    { label: '촬영 기록 확정', ok: progress.recording, staffHint: '촬영 기록 화면에서 확정합니다.', reviewerHint: '운영자가 촬영 기록을 확정해야 합니다.', go: { route: 'recording/record', label: '촬영 기록으로 이동' } },
  ];
  if (kind === 'scoring' || kind === 'report') needs.push({ label: '전처리 완료', ok: progress.preprocess === 'done' || progress.preprocess === 'outdated',
    staffHint: progress.preprocess === 'running' ? '전처리가 실행 중입니다.' : '전처리 화면에서 실행합니다.', reviewerHint: '운영자가 전처리를 실행해야 합니다.', go: { route: 'preprocess', label: '전처리로 이동' } });
  if (kind === 'scoring') needs.push(staff
    ? { label: '평가자 배정 완료', ok: !!progress.sheets_total, staffHint: '아래 「평가자 배정」에서 배정합니다.', reviewerHint: '' }
    : { label: '내 채점 시트 배정', ok: progress.my_sheet !== 'none', staffHint: '', reviewerHint: '운영자가 평가자로 배정해야 합니다.' });
  if (kind === 'report') {
    needs.push({ label: '분석·피드백 동의 확인', ok: item.consents.analysis_feedback === 'confirmed', staffHint: '접수 상세에서 동의를 확인합니다.', reviewerHint: '동의가 확인된 참가자만 리포트를 열 수 있습니다.' });
    if (staff) needs.push({ label: '최종 결과 확정', ok: !!progress.final, staffHint: '독립 채점 화면에서 최종 결과를 만듭니다.', reviewerHint: '', go: { route: 'scoring', label: '독립 채점으로 이동' } });
  }
  if (needs.every(need => need.ok)) return null;
  const title = kind === 'scoring' ? '채점을 시작하려면' : kind === 'preprocess' ? '전처리를 실행하려면' : '리포트를 발급하려면';
  return <section className="panel prerequisites" aria-label="선행 조건"><h2>{staff ? title : `${title} · 운영자에게 요청할 일`}</h2>
    <ul>{needs.map(need => <li key={need.label} className={need.ok ? 'ok' : 'missing'}><span aria-hidden="true">{need.ok ? '✓' : '✗'}</span> <strong>{need.label}</strong>
      <span className="sr-only">{need.ok ? ' 완료' : ' 필요'}</span>
      {!need.ok && <span className="fine"> → {staff ? need.staffHint : need.reviewerHint}</span>}
      {!need.ok && staff && need.go && <> <button onClick={() => goTo(need.go!.route)}>{need.go.label}</button></>}</li>)}</ul></section>;
}
