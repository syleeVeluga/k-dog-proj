import { useEffect, useState } from 'react';
import { PreprocessExecutionsV4 } from '../PreprocessExecutionsV4';
import type { PreprocessExecutionV4 } from '../preprocessTypesV4';
import { Prerequisites } from '../Prerequisites';
import { PreprocessingPanelV4 } from '../PreprocessingPanelV4';
import type { Route } from '../navigation';
import type { Case, Run, User } from '../types';

export function Preprocessing({ cases, selected, select, user, writable, run, refresh, goTo }: { cases: Case[]; selected: Case | null; select: (item: Pick<Case, 'case_id' | 'selected_session_id'> & { pinSession?: boolean }) => Promise<boolean>; user: User; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; goTo: (route: Route) => void }) {
  const [execution, setExecution] = useState<PreprocessExecutionV4 | null>(null);
  useEffect(() => { if (!selected || execution && (execution.case_id !== selected.case_id || execution.session_id !== selected.selected_session_id)) setExecution(null); }, [selected?.case_id, selected?.selected_session_id]);
  const view = selected && execution ? { ...selected, selected_session_id: execution.session_id } : selected;
  return <section><h1>전처리</h1>
    {view ? <><p>선택한 참가자의 촬영 기록으로 분석용 클립을 만듭니다. 설정을 확인한 뒤 「새 클립으로 전처리」를 누르세요.</p>
        {!execution && <Prerequisites item={view} kind="preprocess" user={user} goTo={goTo} />}
        {execution && <p>{execution.participant_id} · 보존된 {cases.find(value => value.case_id === execution.case_id)?.manifest.sessions.findIndex(value => value.session_id === execution.session_id)! + 1}회차 실행 · {execution.requested_by}</p>}
        {execution && <button onClick={() => { const current = cases.find(value => value.case_id === view.case_id); if (current) void select(current).then(opened => { if (opened) setExecution(null); }); }}>현재 입력으로 돌아가기</button>}
        <PreprocessingPanelV4 key={`${user.username}:${view.case_id}:${view.selected_session_id}:${execution?.execution_id ?? 'current'}`} item={view} username={user.username} executionId={execution?.execution_id} writable={writable && !execution} run={run} refresh={async message => { await refresh(message); window.dispatchEvent(new Event('kdog-preprocess-refresh')); }} />
        <PreprocessExecutionsV4 key={`${user.username}:${view.case_id}`} item={view} user={user} open={item => { void select({ case_id: item.case_id, selected_session_id: item.session_id, pinSession: true }).then(opened => { if (opened) setExecution(item); }); }} /></>
        : <p>참가자를 선택한 뒤 전처리 탭을 여세요. <button onClick={() => goTo('intake')}>참가자 접수로 이동</button></p>}
  </section>;
}
