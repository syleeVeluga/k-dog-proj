import type { Route } from './navigation';
import { currentProgress } from './progressText';
import type { Case, User } from './types';

type Kind = 'preprocess' | 'scoring' | 'report';
type Need = { label: string; ok: boolean; hint: string; go?: { route: Route; label: string } };

// 서버가 계산한 공통 자료 준비 상태를 표시한다.
export function Prerequisites({ item, kind, goTo }: { item: Case; kind: Kind; user: User; goTo: (route: Route) => void }) {
  const progress = currentProgress(item);
  if (!progress) return null;
  const needs: Need[] = [
    { label: '촬영 기록 확정', ok: progress.recording,
      hint: kind === 'preprocess' ? '위의 촬영 기록 탭에서 확정합니다.' : '촬영 기록 화면에서 확정합니다.',
      go: kind === 'preprocess' ? undefined : { route: 'recording/record', label: '촬영 기록으로 이동' } },
  ];
  if (kind === 'scoring' || kind === 'report') needs.push({ label: '전처리 완료', ok: progress.preprocess === 'done' || progress.preprocess === 'outdated',
    hint: progress.preprocess === 'running' ? '전처리가 실행 중입니다.' : '전처리 화면에서 실행합니다.', go: { route: 'preprocess', label: '전처리로 이동' } });
  if (kind === 'scoring') needs.push({ label: '채점 시트', ok: !!progress.sheets_total, hint: '아래 「채점 시트 만들기」에서 시작합니다.' });
  if (kind === 'report') {
    needs.push({ label: '최종 결과 확정', ok: !!progress.final, hint: '독립 채점 화면에서 최종 결과를 만듭니다.', go: { route: 'scoring', label: '독립 채점으로 이동' } });
  }
  const previousInput = progress.preprocess === 'outdated';
  if (needs.every(need => need.ok) && !previousInput) return null;
  const title = kind === 'scoring' ? '채점을 시작하려면' : kind === 'preprocess' ? '전처리를 실행하려면' : '리포트를 발급하려면';
  return <section className="panel prerequisites" aria-label="선행 조건"><h2>{title}</h2>
    {previousInput && <p role="status">입력이 변경되어 이전 입력의 전처리 결과를 표시합니다. 기존 채점 시트는 보존된 입력으로 작업할 수 있습니다. 새 입력으로 전처리를 다시 실행할 수 있습니다.</p>}
    <ul>{needs.map(need => <li key={need.label} className={need.ok ? 'ok' : 'missing'}><span aria-hidden="true">{need.ok ? '✓' : '✗'}</span> <strong>{need.label}</strong>
      <span className="sr-only">{need.ok ? ' 완료' : ' 필요'}</span>
      {!need.ok && <span className="fine"> → {need.hint}</span>}
      {!need.ok && need.go && <> <button onClick={() => goTo(need.go!.route)}>{need.go.label}</button></>}</li>)}</ul></section>;
}
