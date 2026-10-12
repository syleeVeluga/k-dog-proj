import { useEffect, useState } from 'react';
import type { CaseFilterProps } from '../CaseFilters';
import { CaseFilters, matchesCase } from '../CaseFilters';
import { PreprocessExecutionsV4 } from '../PreprocessExecutionsV4';
import type { PreprocessExecutionV4 } from '../preprocessTypesV4';
import { Prerequisites } from '../Prerequisites';
import { PreprocessingPanelV4 } from '../PreprocessingPanelV4';
import type { Route } from '../navigation';
import type { Case, Run, User } from '../types';

export function Preprocessing({ cases, selected, select, filters, user, writable, run, refresh, goTo }: { cases: Case[]; selected: Case | null; select: (item: Pick<Case, 'case_id' | 'selected_session_id'> & { pinSession?: boolean }) => void; filters: CaseFilterProps; user: User; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; goTo: (route: Route) => void }) {
  const [picker, setPicker] = useState(false), [execution, setExecution] = useState<PreprocessExecutionV4 | null>(null);
  useEffect(() => { if (!selected || execution && (execution.case_id !== selected.case_id || execution.session_id !== selected.selected_session_id)) setExecution(null); }, [selected?.case_id, selected?.selected_session_id]);
  const view = selected && execution ? { ...selected, selected_session_id: execution.session_id } : selected;
  return <section><div className="section-head"><h1>전처리</h1><button onClick={() => { setExecution(null); setPicker(true); }}>전처리 실행</button></div><p>기준 영상을 구간별로 잘라 분석용 파일을 만듭니다. 원본과 오디오는 보존됩니다. 실행·재시도는 실행 버튼을 눌러 시작합니다.</p>
    {picker ? <section aria-label="전처리 실행 대상"><h2>전처리 실행 대상 선택</h2><CaseFilters cases={cases} {...filters} />
      <div className="table-wrap"><table><thead><tr><th>참가자 / 반려견</th><th>준비 상태</th><th>작업</th></tr></thead><tbody>{cases.filter(item => matchesCase(item, filters.search, filters.eventFilter)).map(item => <tr key={item.case_id}><td>{item.participant_id} · {item.dog_name}</td><td>{item.manifest.sessions.find(value => value.session_id === item.selected_session_id)?.recording_s1?.confirmed ? '촬영 기록 확인됨' : '촬영 기록 확인 필요'}</td><td><button aria-label={`${item.participant_id} 전처리 열기`} onClick={() => { select(item); setPicker(false); }}>선택</button></td></tr>)}</tbody></table></div>
      {!cases.length && <p>실행할 참가자가 없습니다. 접수 화면에서 참가자를 등록하세요.</p>}<button onClick={() => setPicker(false)}>대상 선택 닫기</button></section>
      : view ? <>{!execution && <Prerequisites item={view} kind="preprocess" user={user} goTo={goTo} />}
        {execution && <p>{execution.participant_id} · 보존된 {cases.find(value => value.case_id === execution.case_id)?.manifest.sessions.findIndex(value => value.session_id === execution.session_id)! + 1}회차 실행 · {execution.requested_by}</p>}
        {execution && <button onClick={() => { setExecution(null); setPicker(true); }}>현재 입력으로 재실행</button>}
        <PreprocessingPanelV4 key={`${user.username}:${view.case_id}:${view.selected_session_id}:${execution?.execution_id ?? 'current'}`} item={view} username={user.username} executionId={execution?.execution_id} writable={writable && !execution} run={run} refresh={refresh} /></>
        : <PreprocessExecutionsV4 cases={cases} user={user} filters={filters} create={() => setPicker(true)} open={item => { setExecution(item); select({ case_id: item.case_id, selected_session_id: item.session_id, pinSession: true }); }} />}
  </section>;
}
