import { useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, api } from '../api';
import { forgetEdits, mayLeave, useUnsaved } from '../Editing';
import { focusFirstError, focusSoon, useFieldErrors, validateForm } from '../FieldErrors';
import { ParticipantFields, participantValue } from '../ParticipantFields';
import { CaseDetail } from './CaseDetail';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import type { Route } from '../navigation';
import { videoCounts } from '../progressText';
import { SURVEY_TOTAL, segmentState, sessionOf, surveyHandled } from '../types';
import type { Case, Run, User } from '../types';

type Props = {
  user: User; cases: Case[]; selected: Case | null; writable: boolean; busy: boolean; run: Run;
  reload: (id?: string) => Promise<void>; select: (item: Case | null) => void; status: string; notify: (message: string) => void;
  filters: CaseFilterProps; goTo: (route: Route) => void;
};

// 접수 메뉴: 참가자 단건 등록과 원입력 상세. 저장 후에도 폼에 머물러 다음 참가자를 이어서 받는다.
// 파일 일괄 등록은 「일괄 등록」 메뉴에서 한다.
export function Intake({ user, cases, selected, writable, busy, run, reload, select, status, notify, filters, goTo }: Props) {
  const [filter, setFilter] = useState('all');
  const [dirty, setDirty] = useState(false);
  const [formOpen, setFormOpen] = useState<boolean | null>(null);
  const [eventId, setEventId] = useState('');
  const [formKey, setFormKey] = useState(0);
  const [typedSequence, setTypedSequence] = useState<string | null>(null);
  const [last, setLast] = useState<Case | null>(null);
  const fields = useFieldErrors();
  // 다음 빈 순번 제안: 그 행사에 순번이 있는 참가자가 있으면 가장 큰 순번 다음 값. 직접 입력하면 그 값을 쓴다.
  const suggested = useMemo(() => {
    const used = cases.filter(c => c.event_id === eventId.trim() && c.sequence_no !== null).map(c => c.sequence_no as number);
    return used.length ? String(Math.max(...used) + 1) : '';
  }, [cases, eventId]);
  const form = useRef<HTMLFormElement>(null);
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

  function open(item: Case) {
    if (busy || window.getSelection()?.toString()) return;  // 저장 중이거나 글자를 드래그해 복사하는 중에는 열지 않는다.
    if (mayLeave()) { forgetEdits(); setDirty(false); void run(async () => select(await api<Case>(`/cases/${item.case_id}`))); }
  }
  function openRegistered(next: Route | null) {
    if (!last || !mayLeave()) return;
    forgetEdits(); setDirty(false); select(last);
    if (next) goTo(next);
  }

  function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = event.currentTarget;
    const intent = (event.nativeEvent as SubmitEvent).submitter?.getAttribute('value') ?? 'next';
    const problems = validateForm(target);
    if (Object.keys(problems).length) { fields.set(problems); focusFirstError(target, problems); return; }
    const data = new FormData(target);
    void run(async () => {
      let created: Case;
      try { created = await api<Case>('/cases', 'POST', { event_id: String(data.get('event_id')).trim(), ...participantValue(data) }); }
      catch (error) {
        // 중복 ID·순번은 해당 칸 아래에 알리고 그 칸으로 돌아간다. 다른 오류는 전역 알림으로 넘긴다.
        if (error instanceof ApiError && (error.field === 'participant_id' || error.field === 'sequence_no')) {
          const problem = { [error.field]: error.message }; fields.setServer(problem); focusSoon(target, problem); return;
        }
        throw error;
      }
      setDirty(false); fields.clear(); setLast(created); setFormOpen(true);
      setTypedSequence(null); setFormKey(key => key + 1);
      if (intent === 'detail') { await reload(created.case_id); notify('참가자를 등록했습니다.'); return; }
      await reload(); notify('참가자를 등록했습니다.');
      window.setTimeout(() => form.current?.querySelector<HTMLElement>('[name="participant_id"]')?.focus(), 60);
    });
  }

  return <>
    <section className="page-heading"><div><p className="eyebrow">INTAKE</p><h1>접수</h1><p className="muted">{user.role === 'reviewer' ? '접수된 참가자와 자료 상태를 확인하세요.' : '참가자·반려견 정보를 등록하고 동의와 순번을 확인하세요. 명단·설문 파일은 「일괄 등록」으로 올립니다.'}</p></div>
      <div className="count"><strong>{cases.length.toString().padStart(2, '0')}</strong><span>등록된 참가자</span></div></section>
    <CaseFilters cases={cases} {...filters} /><div className="toolbar">
      <label>자료 상태<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">전체</option><option value="ready">설문·영상 등록됨</option><option value="missing">설문·영상 보완 필요</option><option value="consent_missing">동의 미확인</option><option value="survey_missing">설문 미등록</option><option value="video_missing">영상 없음</option></select></label>
      <button onClick={() => void run(() => reload())}>새로고침</button></div>
    <p className="fine" role="status">{status} · 표시 {visible.length}명</p>
    <div className="table-wrap"><table><thead><tr><th>순번</th><th>참가자 / 행사</th><th>반려견 / 보호자</th><th>동의</th><th>설문</th><th>영상</th><th>구간</th><th>자료</th></tr></thead>
      <tbody>{visible.map(c => { const s = sessionOf(c); const count = surveyHandled(s);
        return <tr key={c.case_id} className="clickable" onClick={() => open(c)}><td data-label="순번"><strong className="mono">{c.sequence_no ?? '—'}</strong></td>
          <td data-label="참가자 / 행사"><strong className="mono">{c.participant_id}</strong><small>{c.event_id}</small></td>
          <td data-label="반려견 / 보호자">{c.dog_name}<small>{c.guardian_name ? `${c.guardian_name} 님` : '보호자명 없음'}{c.dog.breed ? ` · ${c.dog.breed}` : ''}</small></td>
          <td data-label="동의"><span className={c.consent_confirmed ? 'tag green' : 'tag'}>{c.consent_confirmed ? '확인' : '미확인'}</span></td>
          <td data-label="설문"><span className={count === SURVEY_TOTAL ? 'tag green' : 'tag'}>{count}/{SURVEY_TOTAL}</span>{s.survey_version === 'survey-20260929-v3' && <small>빈칸 사유 {Object.keys(s.survey_blank_reasons ?? {}).length}개 · 완료 기준 미확정</small>}</td><td data-label="영상">{videoCounts(c)}</td>
          <td data-label="구간">{({ none: '없음', draft: '초안', confirmed: '확정' })[segmentState(s)]}{c.scoring_status === 'reanalysis_required' && <small>채점 전</small>}</td>
          <td data-label="자료"><button aria-label={`${c.participant_id} 상세 열기`} onClick={e => { e.stopPropagation(); open(c); }}>열기</button></td></tr>;
      })}</tbody></table>{!visible.length && <div className="empty"><h2>{cases.length ? '조건에 맞는 참가자가 없습니다.' : '첫 참가자를 등록하세요.'}</h2><p>행사와 참가자 ID를 먼저 확인한 뒤 자료를 연결합니다.</p></div>}</div>
    {writable && <div className="panel toolbar"><p>CSV·Excel 파일로 참가자와 설문을 한꺼번에 등록할 수 있습니다.</p><button onClick={() => goTo('intake/upload')}>일괄 등록으로 이동</button></div>}
    {writable && <details className="panel" open={formOpen ?? !cases.length}><summary onClick={e => { e.preventDefault(); setFormOpen(!(formOpen ?? !cases.length)); }}>참가자 등록</summary>
      {last && <p role="status" className="registered"><strong>{last.participant_id} {last.dog_name} 등록됨</strong> · <button className="plain" onClick={() => openRegistered(null)}>상세 보기</button> · <button className="plain" onClick={() => openRegistered('recording/record')}>촬영으로</button></p>}
      <form ref={form} noValidate onSubmit={register} onChange={() => setDirty(true)} {...fields.bind}>
        {fields.summary && <p className="error" role="alert">{fields.summary}</p>}
        <div className="form-grid"><label>행사 ID<input aria-label="행사 ID" name="event_id" placeholder="KDOG-2026" required value={eventId}
          aria-invalid={fields.errors.event_id ? true : undefined} aria-describedby={fields.errors.event_id ? 'participant-event_id-error' : undefined} onChange={e => setEventId(e.target.value)} />
          <small>필수 · 같은 행사에는 같은 ID. 예: KDOG-2026. 영문·숫자·밑줄·하이픈.</small>
          {fields.errors.event_id && <small className="field-error" id="participant-event_id-error" role="alert">{fields.errors.event_id}</small>}</label>
          <ParticipantFields key={formKey} errors={fields.errors} sequence={typedSequence ?? suggested} onSequence={setTypedSequence} /></div>
        <p className="fine">이름이 같아도 참가자 ID는 각각 등록합니다. ID 앞자리 0은 그대로 보존됩니다. 순번은 행사 안에서 하나씩입니다. 연락처는 받지 않습니다.</p>
        <div className="toolbar"><button className="primary" name="intent" value="next">참가자 저장</button>
          <button name="intent" value="detail">저장하고 상세 열기</button>
          <span className="fine">저장하면 이 화면에 머물러 다음 참가자를 이어서 등록합니다.</span></div></form></details>}
  </>;
}
