import { api } from '../api';
import { forgetEdits, mayLeave } from '../Editing';
import { RecordingPanelV4 } from '../RecordingPanelV4';
import { PreservedMediaRegistration } from '../PreservedMediaRegistration';
import { UploadInbox } from '../UploadInbox';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { videoCounts } from '../progressText';
import { segmentState, sessionOf } from '../types';
import type { Case, Run, User } from '../types';
import type { Route } from '../navigation';

type Props = { view: 'inbox' | 'record' | 'shared'; user: User; cases: Case[]; selected: Case | null; select: (item: Case | null) => void; filters: CaseFilterProps; writable: boolean; run: Run; reload: (id?: string) => Promise<void>; notify: (message: string) => void; goTo: (route: Route) => void; back: () => void };

export function toClock(seconds: number) {
  const rounded = Math.round(seconds * 10) / 10;  // round first so 59.96 becomes 1:00.0, never 0:60.0
  const minutes = Math.floor(rounded / 60);
  return `${minutes}:${(rounded - minutes * 60).toFixed(1).padStart(4, '0')}`;
}
export function fromClock(text: string): number | null {
  const match = /^(\d+):([0-5]?\d(?:\.\d+)?)$/.exec(text.trim());
  const value = match ? Number(match[1]) * 60 + Number(match[2]) : /^\d+(\.\d+)?$/.test(text.trim()) ? Number(text) : NaN;
  return Number.isFinite(value) ? value : null;
}

// 참가자별 영상·촬영 기록과 등록 전 공용 수신 경로.
export function Recording({ view, user, cases, selected, select, filters, writable, run, reload, notify, goTo, back }: Props) {
  const sharedInbox = view === 'shared';
  const sorted = cases.filter(c => matchesCase(c, filters.search, filters.eventFilter)).sort((a, b) => (a.sequence_no ?? 1e9) - (b.sequence_no ?? 1e9) || a.participant_id.localeCompare(b.participant_id));
  const confirmed = cases.filter(c => segmentState(sessionOf(c)) === 'confirmed').length;
  if (view !== 'record') return <>
    <section className="page-heading"><div><p className="eyebrow">RECORDING</p><h1>{sharedInbox ? '공용 업로드 보관함' : '영상 파일 업로드'}</h1><p className="muted">{sharedInbox ? '참가자 등록 전에 도착한 파일을 보관합니다. 업로드 후 참가자와 촬영 회차를 지정해 연결하세요.' : '참가자를 선택한 뒤 영상을 등록하세요. 파일마다 촬영 카메라 번호를 확인하고 영상 정보를 저장합니다.'}</p></div></section>
    {!selected && !sharedInbox && <section aria-label="영상 등록 대상"><h2>영상을 등록할 참가자 선택</h2><CaseFilters cases={cases} {...filters} />
      <div className="table-wrap"><table><thead><tr><th>참가자 / 반려견</th><th>촬영 회차</th><th>등록 영상</th><th>작업</th></tr></thead><tbody>{sorted.map(item => <tr key={item.case_id}>
        <td data-label="참가자 / 반려견">{item.participant_id} · {item.dog_name}<small>{item.event_id}</small></td><td data-label="촬영 회차">{item.manifest.sessions.findIndex(s => s.session_id === item.selected_session_id) + 1}차 촬영</td><td data-label="등록 영상">{videoCounts(item)}</td>
        <td data-label="작업"><button aria-label={`${item.participant_id} 영상 등록 대상 선택`} onClick={() => select(item)}>영상 등록</button></td></tr>)}</tbody></table></div>
      {!sorted.length && <p>조건에 맞는 참가자가 없습니다. 검색 조건을 바꾸거나 참가자를 등록하세요.</p>}
      <div className="panel registration-callout"><p>참가자 등록 전에 도착한 파일은 공용 보관함에 올린 뒤 연결할 수 있습니다.</p><button onClick={() => goTo('recording/shared')}>공용 업로드 보관함 열기</button></div>
    </section>}
    {(selected || sharedInbox) && <>
      <div className="participant-actions"><button onClick={() => { if (mayLeave()) { forgetEdits(); select(null); goTo('recording/inbox'); } }}>참가자 다시 선택</button></div>
      {!selected && <p role="status">공용 보관함입니다. 업로드한 각 파일에 참가자와 촬영 회차를 지정하세요.</p>}
      {writable && <UploadInbox key={`${selected?.case_id ?? 'shared'}:${selected?.selected_session_id ?? ''}`} cases={cases} selected={selected} user={user} run={run} refresh={async message => { await reload(); if (message) notify(message); }} />}
    {selected && <PreservedMediaRegistration item={selected} writable={writable} run={run}
      refresh={async message => { await reload(); if (message) notify(message); }} />}
      {selected && writable && <details className="panel"><summary>새로 촬영한 영상을 등록할 때</summary><p>다른 날 다시 촬영한 영상은 새 회차로 등록합니다. 예: 1차 평가 후 2차 재촬영. 기존 영상·기록은 남고 새 회차는 비어 있습니다. 같은 촬영의 파일을 추가하거나 다시 분석할 때는 만들지 않습니다.</p>
        <button onClick={() => { if (!mayLeave()) return; void run(async () => { const saved = await api<Case>(`/cases/${selected.case_id}/sessions`, 'POST', { expected_revision: selected.input_revision }); forgetEdits(); await select(saved); await reload(); notify('새 촬영 회차를 시작했습니다.'); }); }}>새 촬영 회차 만들기</button></details>}
    </>}
  </>;
  return <>
    <section className="page-heading"><div><p className="eyebrow">RECORDING</p><h1>촬영</h1><p className="muted">구간 CSV를 먼저 등록하고 촬영 영상의 카메라 번호를 연결하세요. 실제 시각을 확인한 뒤 기록을 확정합니다. 음성 청취나 대표 영상 선정은 CSV 등록의 필수 조건이 아닙니다.</p></div>
      <div className="count"><strong>{confirmed.toString().padStart(2, '0')}</strong><span>구간 확정 / {cases.length}명</span></div></section>
    {!selected && <><CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>순번</th><th>참가자</th><th>반려견 / 보호자</th><th>영상</th><th>구간</th><th>작업</th></tr></thead>
      <tbody>{sorted.map(c => { const s = sessionOf(c); const state = segmentState(s);
        return <tr key={c.case_id}><td data-label="순번"><strong className="mono">{c.sequence_no ?? '—'}</strong></td>
          <td data-label="참가자"><strong className="mono">{c.participant_id}</strong><small>{c.event_id}</small></td>
          <td data-label="반려견 / 보호자">{c.dog_name}<small>{c.guardian_name ? `${c.guardian_name} 님` : '보호자명 없음'}</small></td>
          <td data-label="영상">{videoCounts(c)}</td>
          <td data-label="구간"><span className={state === 'confirmed' ? 'tag green' : 'tag'}>{({ none: '없음', draft: '초안', confirmed: '확정' })[state]}</span></td>
          <td data-label="작업"><button aria-label={`${c.participant_id} 촬영 열기`} onClick={() => { if (mayLeave()) select(c); }}>열기 ↗</button></td></tr>;
      })}</tbody></table>{!sorted.length && <div className="empty"><h2>표시할 참가자가 없습니다.</h2><p>검색·행사 필터 또는 접수 등록을 확인하세요.</p></div>}</div></>}
    {selected && <RecordingPanelV4 key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} username={user.username} writable={writable} run={run}
      refresh={async message => { await reload(); if (message) notify(message); }} onConfirmed={() => goTo('preprocess')} close={back} />}

  </>;
}
