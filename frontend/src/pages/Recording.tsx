import { mayLeave } from '../Editing';
import { RecordingPanelV4 } from '../RecordingPanelV4';
import { PreservedMediaRegistration } from '../PreservedMediaRegistration';
import { UploadInbox } from '../UploadInbox';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { segmentState, sessionOf } from '../types';
import type { Case, Run, User } from '../types';

type Props = { view: 'inbox' | 'record'; user: User; cases: Case[]; selected: Case | null; select: (item: Case | null) => void; filters: CaseFilterProps; writable: boolean; run: Run; reload: (id?: string) => Promise<void>; notify: (message: string) => void };

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

// 촬영 메뉴: 영상 수신·연결(inbox)과 실제 8구간·사건·관찰창 기록(record)을 하위 메뉴로 나눈다.
export function Recording({ view, user, cases, selected, select, filters, writable, run, reload, notify }: Props) {
  const sorted = cases.filter(c => matchesCase(c, filters.search, filters.eventFilter)).sort((a, b) => (a.sequence_no ?? 1e9) - (b.sequence_no ?? 1e9) || a.participant_id.localeCompare(b.participant_id));
  const confirmed = cases.filter(c => segmentState(sessionOf(c)) === 'confirmed').length;
  if (view === 'inbox') return <>
    <section className="page-heading"><div><p className="eyebrow">RECORDING</p><h1>영상 수신·연결</h1><p className="muted">현장 PC가 보낸 영상 파일을 참가자·회차·카메라에 연결합니다.</p></div></section>
    {writable && <UploadInbox cases={cases} selected={selected} user={user} run={run} refresh={async message => { await reload(); if (message) notify(message); }} />}
  </>;
  return <>
    <section className="page-heading"><div><p className="eyebrow">RECORDING</p><h1>촬영</h1><p className="muted">영상 파일을 등록하고 8구간의 시작·끝 시각을 기록합니다. 구간 경계는 마이크 음성과 진행자 신호로 잡습니다. 확정 전에는 채점을 시작하지 않습니다.</p></div>
      <div className="count"><strong>{confirmed.toString().padStart(2, '0')}</strong><span>구간 확정 / {cases.length}명</span></div></section>
    {!selected && <><CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>순번</th><th>참가자</th><th>반려견 / 보호자</th><th>영상</th><th>구간</th><th>작업</th></tr></thead>
      <tbody>{sorted.map(c => { const s = sessionOf(c); const state = segmentState(s);
        return <tr key={c.case_id}><td data-label="순번"><strong className="mono">{c.sequence_no ?? '—'}</strong></td>
          <td data-label="참가자"><strong className="mono">{c.participant_id}</strong><small>{c.event_id}</small></td>
          <td data-label="반려견 / 보호자">{c.dog_name}<small>{c.guardian_name ? `${c.guardian_name} 님` : '보호자명 없음'}</small></td>
          <td data-label="영상">{s.videos.length}개</td>
          <td data-label="구간"><span className={state === 'confirmed' ? 'tag green' : 'tag'}>{({ none: '없음', draft: '초안', confirmed: '확정' })[state]}</span></td>
          <td data-label="작업"><button aria-label={`${c.participant_id} 촬영 열기`} onClick={() => { if (mayLeave()) select(c); }}>열기 ↗</button></td></tr>;
      })}</tbody></table>{!sorted.length && <div className="empty"><h2>표시할 참가자가 없습니다.</h2><p>검색·행사 필터 또는 접수 등록을 확인하세요.</p></div>}</div></>}
    {selected && <RecordingPanelV4 key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} writable={writable} run={run}
      refresh={async message => { await reload(); if (message) notify(message); }} close={() => { if (mayLeave()) select(null); }} />}
    {selected && <PreservedMediaRegistration item={selected} writable={writable} run={run}
      refresh={async message => { await reload(); if (message) notify(message); }} />}

  </>;
}
