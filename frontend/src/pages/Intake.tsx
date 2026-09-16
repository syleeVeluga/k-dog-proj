import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { mayLeave, useUnsaved } from '../Editing';
import { ParticipantFields, participantValue } from '../ParticipantFields';
import { CaseDetail } from './CaseDetail';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { SURVEY_TOTAL, segmentState, sessionOf, surveyHandled } from '../types';
import type { Case, Run, User } from '../types';

type Props = {
  user: User; cases: Case[]; selected: Case | null; writable: boolean; run: Run;
  reload: (id?: string) => Promise<void>; select: (item: Case | null) => void; status: string; notify: (message: string) => void;
  filters: CaseFilterProps;
};

// 접수 메뉴: 참가자 목록·등록·상세. 설문은 자료 가져오기, 영상·구간은 촬영 메뉴(PR-8)가 맡는다.
export function Intake({ user, cases, selected, writable, run, reload, select, status, notify, filters }: Props) {
  const [filter, setFilter] = useState('all');
  const [dirty, setDirty] = useState(false);
  useUnsaved(dirty);
  const visible = cases.filter(c => {
    const session = sessionOf(c);
    const ready = session.videos.length > 0 && surveyHandled(session) === SURVEY_TOTAL;
    const matches = filter === 'all' || (filter === 'ready' && ready) || (filter === 'missing' && !ready)
      || (filter === 'consent_missing' && !c.consent_confirmed) || (filter === 'survey_missing' && surveyHandled(session) < SURVEY_TOTAL)
      || (filter === 'video_missing' && session.videos.length === 0);
    return matchesCase(c, filters.search, filters.eventFilter) && matches;
  }).sort((a, b) => (a.sequence_no ?? 1e9) - (b.sequence_no ?? 1e9) || a.participant_id.localeCompare(b.participant_id));

  if (selected) return <CaseDetail key={selected.case_id} item={selected} writable={writable} run={run}
    back={() => { if (mayLeave()) void run(async () => { select(null); await reload(); }); }}
    refresh={async message => { await reload(selected.case_id); if (message) notify(message); }} />;

  function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(async () => {
      const created = await api<Case>('/cases', 'POST', { event_id: form.get('event_id'), ...participantValue(form) });
      setDirty(false);
      await reload(created.case_id); notify('참가자를 등록했습니다.');
    });
  }

  return <>
    <section className="page-heading"><div><p className="eyebrow">INTAKE</p><h1>접수</h1><p className="muted">{user.role === 'reviewer' ? '접수된 참가자와 자료 상태를 확인하세요.' : '참가자·반려견 정보를 등록하고 동의와 순번을 확인하세요. 설문은 「자료 가져오기」로 등록합니다.'}</p></div>
      <div className="count"><strong>{cases.length.toString().padStart(2, '0')}</strong><span>등록된 참가자</span></div></section>
    <CaseFilters cases={cases} {...filters} /><div className="toolbar">
      <label>자료 상태<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">전체</option><option value="ready">설문·영상 등록됨</option><option value="missing">설문·영상 보완 필요</option><option value="consent_missing">동의 미확인</option><option value="survey_missing">설문 미등록</option><option value="video_missing">영상 없음</option></select></label>
      <button onClick={() => void run(() => reload())}>새로고침</button></div>
    <p className="fine" role="status">{status} · 표시 {visible.length}명</p>
    <div className="table-wrap"><table><thead><tr><th>순번</th><th>참가자 / 행사</th><th>반려견 / 보호자</th><th>동의</th><th>설문</th><th>영상</th><th>구간</th><th>자료</th></tr></thead>
      <tbody>{visible.map(c => { const s = sessionOf(c); const count = surveyHandled(s);
        return <tr key={c.case_id}><td data-label="순번"><strong className="mono">{c.sequence_no ?? '—'}</strong></td>
          <td data-label="참가자 / 행사"><strong className="mono">{c.participant_id}</strong><small>{c.event_id}</small></td>
          <td data-label="반려견 / 보호자">{c.dog_name}<small>{c.guardian_name ? `${c.guardian_name} 님` : '보호자명 없음'}{c.dog.breed ? ` · ${c.dog.breed}` : ''}</small></td>
          <td data-label="동의"><span className={c.consent_confirmed ? 'tag green' : 'tag'}>{c.consent_confirmed ? '확인' : '미확인'}</span></td>
          <td data-label="설문"><span className={count === SURVEY_TOTAL ? 'tag green' : 'tag'}>{count}/{SURVEY_TOTAL}</span></td><td data-label="영상">{s.videos.length}개</td>
          <td data-label="구간">{({ none: '없음', draft: '초안', confirmed: '확정' })[segmentState(s)]}</td>
          <td data-label="자료"><button aria-label={`${c.participant_id} 상세 열기`} onClick={() => { if (mayLeave()) { setDirty(false); void run(async () => select(await api<Case>(`/cases/${c.case_id}`))); } }}>열기 ↗</button></td></tr>;
      })}</tbody></table>{!visible.length && <div className="empty"><h2>{cases.length ? '조건에 맞는 참가자가 없습니다.' : '첫 참가자를 등록하세요.'}</h2><p>행사와 참가자 ID를 먼저 확인한 뒤 자료를 연결합니다.</p></div>}</div>
    {writable && <details className="panel" open={!cases.length}><summary>참가자 등록</summary>
      <form onSubmit={register} onChange={() => setDirty(true)}>
        <div className="form-grid"><label>행사 ID<input aria-label="행사 ID" name="event_id" placeholder="KDOG-2026" pattern="[A-Za-z0-9_\-]+" required /><small>필수 · 같은 행사에는 같은 ID. 예: KDOG-2026. 영문·숫자·밑줄·하이픈.</small></label>
          <ParticipantFields /></div>
        <p className="fine">이름이 같아도 참가자 ID는 각각 등록합니다. ID 앞자리 0은 그대로 보존됩니다. 순번은 행사 안에서 하나씩입니다. 연락처는 받지 않습니다.</p>
        <button className="primary">참가자 저장</button></form></details>}
  </>;
}
