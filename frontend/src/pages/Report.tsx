import { useState } from 'react';
import type { CaseFilterProps } from '../CaseFilters';
import { CaseProgressList } from '../CaseProgressList';
import { ComparisonSettings } from '../ComparisonSettings';
import { Prerequisites } from '../Prerequisites';
import { ReportRunsV4 } from '../ReportRunsV4';
import { ResearchExportsV4 } from '../ResearchExportsV4';
import { isStaff } from '../progressText';
import type { Route } from '../navigation';
import type { Case, Run, User } from '../types';

type Props = { view: 'issue' | 'comparison' | 'export'; cases: Case[]; selected: Case | null; select: (item: Case | null) => void; filters: CaseFilterProps; user: User; run: Run; refresh: (message?: string) => Promise<void>; goTo: (route: Route) => void };

export function Report({ view, cases, selected, select, filters, user, run, refresh, goTo }: Props) {
  const [comparisonRevision, setComparisonRevision] = useState(0);
  const staff = isStaff(user.role);
  if (!staff) return <p role="status">리포트 운영 권한이 필요합니다.</p>;
  if (view === 'comparison') return <section><h1>리포트 비교 조건</h1><p>자체 집단과 외부 비교 조건을 설정합니다. 설정은 이후 발급하는 리포트에 적용됩니다.</p>
    <ComparisonSettings user={user} onSaved={() => setComparisonRevision(value => value + 1)} /></section>;
  if (view === 'export') return <section><h1>연구 내보내기</h1><p>참가자를 고르면 그 참가자의 채점·판정·최종 결과·리포트 자료를 연구용 표로 내보냅니다. 참가자 선택이 필요합니다.</p>
    {selected ? <><div className="toolbar"><button onClick={() => select(null)}>← 참가자 목록</button></div>
      <details open><summary>연구 내보내기 · {selected.dog_name} ({selected.participant_id})</summary><ResearchExportsV4 key={`export:${selected.case_id}:${selected.selected_session_id}`} item={selected} user={user} /></details></>
      : <CaseProgressList cases={cases} user={user} filters={filters} open={select} openLabel={item => `${item.participant_id} 연구 내보내기 열기`} />}
  </section>;
  return <section><h1>리포트</h1>
    <p>고정한 최종 결과로 관찰 리포트를 만들고, 발급 당시의 HTML·PDF를 확인합니다. 메뉴 조회만으로 생성하지 않습니다.</p>
    {selected ? selected.manifest.schema_version === 'intake-4.0'
      ? <><Prerequisites item={selected} kind="report" user={user} goTo={goTo} />
        <ReportCase key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} user={user} comparisonRevision={comparisonRevision} refresh={() => run(async () => { await refresh(); })} close={() => select(null)} /></>
      : <p role="status">최신 접수 형식으로 전환된 참가자만 리포트를 지원합니다.</p>
      : <CaseProgressList cases={cases} user={user} filters={filters} open={select} openLabel={item => `${item.participant_id} 리포트 열기`} />}
  </section>;
}

function ReportCase({ item, user, comparisonRevision, refresh, close }: { item: Case; user: User; comparisonRevision: number; refresh: () => Promise<void>; close: () => void }) {
  const [session, setSession] = useState(item.selected_session_id);
  return <section className="panel" style={{ minWidth: 0, overflowWrap: 'anywhere' }}><div className="section-title"><h2>{item.dog_name} · 리포트 발급 이력</h2><button onClick={close}>닫기</button></div>
    <p>{item.event_id} / {item.participant_id} · 접수 입력 {item.input_revision}판</p>
    <label>리포트 회차<select aria-label="리포트 회차" value={session} onChange={event => setSession(event.target.value)}>{item.manifest.sessions.map((value, index) => <option key={value.session_id} value={value.session_id}>{index + 1}회차 · {value.note || `${index + 1}차 촬영`}{value.session_id === item.selected_session_id ? ' · 현재 선택' : ''}</option>)}</select></label>
    <button onClick={() => void refresh()}>현재 접수 입력 새로고침</button>
    <ReportRunsV4 key={`${item.case_id}:${session}`} item={{ ...item, selected_session_id: session }} user={user} comparisonRevision={comparisonRevision} />
  </section>;
}
