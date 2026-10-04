import { useState } from 'react';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { ReportRunsV4 } from '../ReportRunsV4';
import { ComparisonSettings } from '../ComparisonSettings';
import type { Case, Run, User } from '../types';

export function Report({ cases, selected, select, filters, user, run, refresh }: { cases: Case[]; selected: Case | null; select: (item: Case | null) => void; filters: CaseFilterProps; user: User; run: Run; refresh: (message?: string) => Promise<void> }) {
  const [comparisonRevision, setComparisonRevision] = useState(0);
  if (!['operator', 'admin'].includes(user.role)) return <p role="status">리포트 운영 권한이 필요합니다.</p>;
  return <section><h1>리포트</h1><p>고정한 최종 결과로 관찰 리포트를 만들고, 발급 당시의 HTML·PDF를 확인합니다. 메뉴 조회만으로 생성하지 않습니다.</p>
    <details><summary>자체 집단과 외부 비교 조건</summary><ComparisonSettings user={user} onSaved={() => setComparisonRevision(value => value + 1)} /></details>
    {selected ? selected.manifest.schema_version === 'intake-4.0' ? <ReportCase key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} user={user} comparisonRevision={comparisonRevision} refresh={() => run(async () => { await refresh(); })} close={() => select(null)} /> : <p role="status">S1 입력의 리포트만 지원합니다.</p> : <>
      <CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>행사 / 참가자</th><th>반려견</th><th>작업</th></tr></thead><tbody>{cases.filter(item => matchesCase(item, filters.search, filters.eventFilter)).map(item => <tr key={item.case_id}><td>{item.event_id} / {item.participant_id}</td><td>{item.dog_name}</td><td><button aria-label={`${item.participant_id} 리포트 열기`} onClick={() => select(item)}>열기</button></td></tr>)}</tbody></table></div>
    </>}
  </section>;
}

function ReportCase({ item, user, comparisonRevision, refresh, close }: { item: Case; user: User; comparisonRevision: number; refresh: () => Promise<void>; close: () => void }) {
  const [session, setSession] = useState(item.selected_session_id);
  return <section className="panel" style={{ minWidth: 0, overflowWrap: 'anywhere' }}><div className="section-title"><h2>{item.dog_name} · 리포트 발급 이력</h2><button onClick={close}>닫기</button></div>
    <p>{item.event_id} / {item.participant_id} · 접수 입력 {item.input_revision}판</p>
    <label>리포트 회차<select aria-label="리포트 회차" value={session} onChange={event => setSession(event.target.value)}>{item.manifest.sessions.map((value, index) => <option key={value.session_id} value={value.session_id}>{index + 1}회차 · {value.note || value.session_id.slice(0, 8)}{value.session_id === item.selected_session_id ? ' · 현재 선택' : ''}</option>)}</select></label>
    <button onClick={() => void refresh()}>현재 접수 입력 새로고침</button>
    <ReportRunsV4 key={`${item.case_id}:${session}`} item={{ ...item, selected_session_id: session }} user={user} comparisonRevision={comparisonRevision} />
  </section>;
}
