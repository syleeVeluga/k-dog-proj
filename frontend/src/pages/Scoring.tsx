import { useEffect, useRef, useState } from 'react';
import { accessLost, api } from '../api';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { mayLeave, useEditBase } from '../Editing';
import { Notification } from '../Notification';
import { formFields, sessionOf } from '../types';
import type { Case, User } from '../types';
import type { BehaviorCatalog, BehaviorItem, Evidence, Observation, SheetDocument, SheetSummary, SheetView } from '../ScoringTypes';

const statusNames = { observed: '관찰한 원값', unobserved: '미관찰/판독 불가', no_opportunity: '기회 없음', not_performed: '미실시' };
const purposeNames: Record<string, string> = { independent: '독립 원자료', review: '공개 후 검수', consensus: '합의 기록' };
const blank = (code: string): Observation => ({ code, value: null, status: 'unobserved', reason: '', opportunity: 'unknown', validity: 'unknown', welfare_stopped: false, evidence: [], latency_not_occurred: false, actual_latency_seconds: null });
function windowParts(doc: SheetDocument, window: SheetDocument['source']['windows'][number]) {
  return ['entry_leash', 'exit_leash'].includes(window.window_id)
    ? doc.source.windows.filter(part => [window.window_id + '_before', window.window_id + '_after'].includes(part.window_id) && ['available', 'partial'].includes(part.status) && part.clip_names.some(name => window.clip_names.includes(name)))
    : [window];
}

export function Scoring({ cases, selected, select, filters, user }: { cases: Case[]; selected: Case | null; select: (item: Case) => void; filters: CaseFilterProps; user: User }) {
  return <section><h1>독립 채점</h1><p>배정된 평가자가 같은 촬영 입력과 실제 관찰창을 기준으로 기록합니다. 다른 평가 결과는 독립 제출 뒤 운영자가 명시적으로 공개한 완료본만 열 수 있습니다.</p>
    {selected ? sessionOf(selected).protocol_version === 'protocol-20260929-v3' ? <ScoringWorkspace key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} user={user} /> : <p role="status">구판/절차 미확인 회차입니다. 신판 독립 채점은 확정한 신판 촬영에 배정하세요.</p> : <>
      <CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>행사 / 참가자</th><th>반려견</th><th>작업</th></tr></thead><tbody>
        {cases.filter(c => matchesCase(c, filters.search, filters.eventFilter)).map(c => <tr key={c.case_id}><td>{c.event_id} / {c.participant_id}</td><td>{c.dog_name}</td><td><button onClick={() => select(c)} aria-label={`${c.participant_id} 독립 채점 열기`}>열기</button></td></tr>)}
      </tbody></table></div></>}
  </section>;
}

function ScoringWorkspace({ item, user }: { item: Case; user: User }) {
  const manager = user.role === 'operator' || user.role === 'admin';
  const [rows, setRows] = useState<SheetSummary[]>([]);
  const [accounts, setAccounts] = useState<User[]>([]);
  const [catalog, setCatalog] = useState<BehaviorCatalog | null>(null);
  const [sheetId, setSheetId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}/sheets`;
  async function reload() { setRows(await api<SheetSummary[]>(path)); }
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const result = await api<SheetSummary[]>(path); if (active) setRows(result); }
      catch (e) { if (active) setError(e instanceof Error ? e.message : '배정 조회 실패'); }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll();
    api<BehaviorCatalog>('/catalog/behavior-v3').then(value => { if (active) setCatalog(value); }).catch(e => { if (active) setError(String(e)); });
    if (manager) api<User[]>('/scoring/accounts').then(value => { if (active) setAccounts(value); }).catch(e => { if (active) setError(String(e)); });
    return () => { active = false; clearTimeout(timer); };
  }, [path, manager]);
  async function work(action: () => Promise<unknown>) {
    setBusy(true); setError(''); setNotice('');
    try { await action(); await reload(); setNotice('작업을 저장했습니다.'); }
    catch (e) { setError(e instanceof Error ? e.message : '채점 작업 실패'); }
    finally { setBusy(false); }
  }
  return <div className="panel" aria-label="평가 배정">
    <Notification message={error} kind="error" onClose={() => setError('')} /><Notification message={notice} onClose={() => setNotice('')} />
    <p className="fine">Q07 배정/공개 정책 확인 대기 · 평가 계정과 평가자 ID를 명시합니다. 임의 이름의 대리 입력과 제출 직후 자동 공개는 허용하지 않습니다.</p>
    {manager && <details><summary>평가자 배정</summary><form onSubmit={event => {
      event.preventDefault(); const values = formFields(event.currentTarget); const form = event.currentTarget;
      void work(async () => { await api(path, 'POST', { ...values, expected_revision: item.input_revision, source_sheet_id: values.source_sheet_id || null }); form.reset(); });
    }}><fieldset disabled={busy}><label>입력 계정<select aria-label="입력 계정" name="assigned_username" required><option value="">활성 계정 선택</option>{accounts.map(account => <option key={account.username} value={account.username}>{account.username}</option>)}</select></label>
      <label>평가자 ID<input name="rater_id" pattern="[A-Za-z0-9_-]+" required /></label><label>평가자 표시 이름<input name="rater_name" required /></label>
      <label>기록 목적<select name="purpose"><option value="independent">독립 원자료</option><option value="review">검수 기록</option><option value="consensus">합의 기록</option></select></label>
      <label>촬영 입력 선택<select name="source_sheet_id"><option value="">현재 확정 촬영 입력</option>{rows.map(row => <option key={row.sheet_id} value={row.sheet_id}>{row.rater_name}과 동일한 고정 입력</option>)}</select></label>
      <p className="fine">두 평가자의 비교에는 동일한 고정 입력을 선택하세요. 촬영 수정 뒤에도 이미 배정한 입력은 바뀌지 않습니다.</p><button type="submit">시트 배정</button></fieldset></form></details>}
    {rows.length === 0 && <p role="status">배정된 시트가 없습니다. 운영자에게 확정 촬영의 배정을 요청하세요.</p>}
    <ul>{rows.map(row => <li key={row.sheet_id}><strong>{row.rater_name}</strong> · {purposeNames[row.purpose]} · {row.state === 'submitted' ? '제출·잠금' : '작성 중'} · r{row.revision} · {row.active ? '배정 활성' : '배정 취소'}
      {row.own && row.active && <button onClick={() => { if (mayLeave()) setSheetId(row.sheet_id); }}>내 시트 열기</button>}
      {manager && <ManagerActions row={row} rows={rows} busy={busy} work={work} />}
      <details><summary>입력/평가 연결 정보</summary><p>입력 {row.source_hash} · 평가자 {row.rater_id} · 입력 계정 {row.assigned_username}</p><p>시트 {row.sheet_id} · revision {row.revision} · hash {row.manifest_hash}</p></details>
    </li>)}</ul>
    {sheetId && catalog && <SheetEditor key={sheetId} sheetId={sheetId} catalog={catalog} done={reload} />}
  </div>;
}

function ManagerActions({ row, rows, busy, work }: { row: SheetSummary; rows: SheetSummary[]; busy: boolean; work: (action: () => Promise<unknown>) => Promise<void> }) {
  const [reason, setReason] = useState('');
  const [target, setTarget] = useState('');
  const path = `/sheets/${row.sheet_id}`;
  return <details><summary>{row.rater_name} 배정/공개 관리</summary><label>작업 사유<input value={reason} onChange={event => setReason(event.target.value)} /></label>
    <div className="toolbar">
      {row.state === 'submitted' && <button disabled={busy || !reason.trim() || !row.active} onClick={() => void work(() => api(path + '/reopen', 'POST', { expected_revision: row.revision, reason }))}>이 시트 재개방</button>}
      <button disabled={busy || !reason.trim()} onClick={() => void work(() => api(path + '/assignment', 'PATCH', { expected_revision: row.revision, reason, active: !row.active }))}>{row.active ? '배정 취소' : '배정 재활성'}</button>
    </div>
    <label>명시 공개할 다른 완료본<select value={target} onChange={event => setTarget(event.target.value)}><option value="">완료 시트 선택</option>{rows.filter(other => other.sheet_id !== row.sheet_id && other.state === 'submitted' && other.active && other.source_hash === row.source_hash).map(other => <option key={other.sheet_id} value={other.sheet_id}>{other.rater_name} r{other.revision}</option>)}</select></label>
    <button disabled={busy || !reason.trim() || !target || row.state !== 'submitted' || !row.active} onClick={() => void work(() => api(path + '/grants', 'POST', { expected_revision: row.revision, reason, target_sheet_id: target, target_revision: rows.find(other => other.sheet_id === target)?.revision }))}>선택한 완료본 공개 허용</button>
    <p className="fine">허용만으로 값을 자동 표시하지 않습니다. 평가자의 실제 열람 때 노출 이력을 남기며 기존 독립 제출본은 보존합니다.</p>
  </details>;
}

function SheetEditor({ sheetId, catalog, done }: { sheetId: string; catalog: BehaviorCatalog; done: () => Promise<void> }) {
  const [latest, setLatest] = useState<SheetView | null>(null);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [segment, setSegment] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revealed, setRevealed] = useState<SheetDocument | null>(null);
  const [historical, setHistorical] = useState<SheetDocument | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const edit = useEditBase(latest);
  const clean = useRef(true);
  clean.current = !edit.dirty;
  const path = `/sheets/${sheetId}`;
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const value = await api<SheetView>(path); if (active) { setLatest(value); setUnavailable(false); if (clean.current) setObservations(value.document.sheet.observations); } }
      catch (e) { if (active) { setError(e instanceof Error ? e.message : '시트 조회 실패'); if (accessLost(e)) setUnavailable(true); } }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [path]);
  const view = edit.view;
  if (!view || unavailable) return <p role="status">{error || '내 시트 조회 중…'}</p>;
  const doc = historical ?? view.document;
  const writable = !historical && doc.sheet.rater_kind === 'human' && doc.state === 'draft' && doc.active && latest?.summary.active;
  const items = catalog.items.filter(item => item.usage === 'direct');
  const shown = items.filter(item => (!segment || item.segment_label === segment) && (!search || `${item.code} ${item.text}`.includes(search)));
  const entries = historical ? historical.sheet.observations : observations;
  function change(value: Observation) {
    edit.change(); setObservations(previous => [...previous.filter(item => item.code !== value.code), value]);
  }
  async function work(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); const saved = await api<SheetView>(path); setLatest(saved); setObservations(saved.document.sheet.observations); edit.reset(); await done(); }
    catch (e) { setError(e instanceof Error ? e.message : '채점 작업 실패'); }
    finally { setBusy(false); }
  }
  return <section className="scoring-editor" aria-label="내 채점 시트"><h2>{doc.rater_name} · {purposeNames[doc.purpose]}</h2>
    <Notification message={error} kind="error" onClose={() => setError('')} />
    <p role="status">{doc.state === 'submitted' ? '제출본 잠금 · 원본은 보존됩니다.' : '초안 · 저장과 제출을 구분합니다.'} {doc.sheet.ai_exposed ? 'AI 결과 노출됨' : 'AI 결과 미노출'} · 다른 완료본 노출 {doc.exposures.length}개</p>
    {view.outdated && <p role="status">현재 접수/촬영 입력이 변경되었습니다. 이 시트는 배정 당시 고정한 영상·창을 사용합니다.</p>}
    {edit.dirty && latest && latest.summary.revision !== view.summary.revision && <p role="status">다른 변경이 저장되었습니다. 미저장 입력을 유지합니다. 저장 충돌 시 최신 결과를 확인하세요.</p>}
    <p>입력 {doc.source.input_revision} · 직접 입력109행 중 {entries.length}행 기록.0은 빈칸과 다릅니다. 자동4행/미사용4행은 입력하지 않습니다.</p>
    <label>보존본 조회<select aria-label="보존본 조회" disabled={busy || edit.dirty} value={historical?.revision ?? ''} onChange={event => {
      const number = event.target.value; if (!number) { setHistorical(null); return; }
      void work(async () => setHistorical(await api<SheetDocument>(path + `/revisions/${number}`)));
    }}><option value="">현재 작업본 r{view.summary.revision}</option>{view.document.previous.map(ref => <option key={ref.ref} value={ref.revision}>보존본 r{ref.revision}</option>)}</select></label>
    {historical && <p role="status">보존본 읽기 전용 · 현재 작업본의 원값을 덮지 않습니다.</p>}
    <div className="toolbar"><label>구간/주제 필터<select value={segment} onChange={event => setSegment(event.target.value)}><option value="">전체</option>{[...new Set(items.map(item => item.segment_label))].map(label => <option key={label}>{label}</option>)}</select></label><label>원코드/항목 검색<input value={search} onChange={event => setSearch(event.target.value)} /></label></div>
    <fieldset disabled={busy || !writable}>{shown.map(item => <ObservationEditor key={`${item.code}:${edit.key}:${doc.revision}`} item={item} value={entries.find(entry => entry.code === item.code) ?? blank(item.code)} doc={doc} change={change} />)}</fieldset>
    {writable && <div className="toolbar"><button disabled={busy || !edit.dirty} onClick={() => void work(() => api(path, 'PUT', { expected_revision: view.summary.revision, observations }))}>채점 초안 저장</button>
      <button disabled={busy || edit.dirty} onClick={() => void work(() => api(path + '/submit', 'POST', { expected_revision: view.summary.revision, reason: `평가자 ${purposeNames[doc.purpose]} 제출` }))}>{purposeNames[doc.purpose]} 제출·잠금</button>
      <button disabled={busy || !edit.dirty} onClick={() => { if (edit.discard() && latest) setObservations(latest.document.sheet.observations); }}>미저장 입력 버리고 최신 조회</button></div>}
    {!historical && view.grants.length > 0 && <details><summary>명시 공개된 완료본</summary><p>열면 현재 시트에 노출 이력을 기록합니다. 이미 제출한 독립 원본은 보존되며 이후 수정은 검수 기록입니다.</p>{view.grants.map(grant => <button key={grant.ref} disabled={busy || edit.dirty || doc.state !== 'submitted'} onClick={() => void work(async () => { const result = await api<{ target: SheetDocument }>(path + '/reveal', 'POST', { expected_revision: view.summary.revision, ref: grant.ref }); setRevealed(result.target); })}>공개 완료본 r{grant.revision} 열고 노출 기록</button>)}</details>}
    {!historical && revealed && <details open><summary>{revealed.rater_name} 공개 완료본 r{revealed.revision}</summary><ul>{revealed.sheet.observations.map(value => <li key={value.code}>{value.code} · {value.value ?? value.reason} · {statusNames[value.status]}</li>)}</ul></details>}
    <details><summary>고정 입력·revision/hash·노출 인계 정보</summary><pre>{JSON.stringify({ sheet_id: sheetId, revision: doc.revision, ref: historical ? view.document.previous.find(ref => ref.revision === doc.revision)?.ref : view.summary.manifest_ref, hash: historical ? view.document.previous.find(ref => ref.revision === doc.revision)?.hash : view.summary.manifest_hash, source_hash: doc.source_hash, input: doc.source.input, initial_submission: doc.initial_submission, exposures: doc.exposures }, null, 2)}</pre></details>
  </section>;
}

function ObservationEditor({ item, value, doc, change }: { item: BehaviorItem; value: Observation; doc: SheetDocument; change: (value: Observation) => void }) {
  const windows = doc.source.windows.filter(window => item.windows.includes(window.window_id));
  function update(patch: Partial<Observation>) { change({ ...value, ...patch }); }
  return <article className="scoring-item" aria-label={`${item.code} 원관찰`}><h3>{item.code} · {item.text}</h3>
    <p className="fine">{item.representative_rule}</p>{item.instruction && <p className="fine">{item.instruction}</p>}
    <label>기록 상태<select aria-label={`${item.code} 기록 상태`} value={value.status} onChange={event => {
      const status = event.target.value as Observation['status']; update({ status, value: null, reason: status === 'observed' ? null : value.reason ?? '', opportunity: status === 'no_opportunity' ? 'absent' : 'unknown', latency_not_occurred: false, actual_latency_seconds: null });
    }}>{Object.entries(statusNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
    {value.status === 'observed' ? <label>{item.code} 원값{item.value_type === 'category' ? <select aria-label={`${item.code} 원값`} value={value.value ?? ''} onChange={event => update({ value: event.target.value === '' ? null : Number(event.target.value) })}><option value="">값 선택 (빈칸)</option>{item.labels.map(label => <option key={label.value} value={label.value}>{label.value} · {label.text}</option>)}</select>
      : item.value_type === 'memo' ? <textarea aria-label={`${item.code} 원값`} value={value.value ?? ''} onChange={event => update({ value: event.target.value })} />
      : <input aria-label={`${item.code} 원값`} type="number" step={item.value_type === 'count' ? '1' : 'any'} min={item.input_range?.minimum ?? 0} max={item.input_range?.maximum ?? undefined} value={value.value ?? ''} onChange={event => { const number = event.target.value === '' ? null : Number(event.target.value); update({ value: number, ...(item.code === '개32' ? { latency_not_occurred: number === 99, actual_latency_seconds: number === 99 ? null : number } : {}) }); }} />}</label>
      : <label>빈칸 사유<input aria-label={`${item.code} 빈칸 사유`} value={value.reason ?? ''} onChange={event => update({ reason: event.target.value })} /></label>}
    {item.code === '개32' && <p className="fine">99는 미발생 코드입니다. 실제99초 지연으로 해석하지 않습니다. 실제 초는 반올림하지 않습니다.</p>}
    <div className="row"><label>관찰 기회<select value={value.opportunity} onChange={event => update({ opportunity: event.target.value as Observation['opportunity'] })}><option value="unknown">미확인</option><option value="present">있음</option><option value="absent">없음</option></select></label>
      <label>시행 유효 상태<select value={value.validity} onChange={event => update({ validity: event.target.value as Observation['validity'] })}><option value="unknown">미확인</option><option value="valid">유효</option><option value="caution">주의</option><option value="invalid">유효하지 않음</option></select></label></div>
    <label className="check"><input type="checkbox" checked={value.welfare_stopped} onChange={event => update({ welfare_stopped: event.target.checked })} />복지 중단 영향 (이미 관찰한 원값은 보존)</label>
    <details><summary>{item.code} 실제 관찰창·영상 근거</summary><ul>{windows.map(window => <li key={window.window_id}>{window.window_id} · {windowParts(doc, window).map(part => `${part.start_sec ?? part.source_point_sec ?? '미확인'}~${part.end_sec ?? part.source_point_sec ?? '미확인'}초`).join(' / ')} · {window.status} · {window.reason}</li>)}</ul>
      {value.evidence.map((entry, index) => <EvidenceEditor key={index} item={item} doc={doc} value={entry} change={next => update({ evidence: value.evidence.map((old, position) => position === index ? next : old) })} remove={() => update({ evidence: value.evidence.filter((_, position) => position !== index) })} />)}
      <button type="button" onClick={() => { const source = doc.source.session.videos.find(video => video.video_id === doc.source.session.recording.video_id)!; update({ evidence: [...value.evidence, { video_id: source.video_id, video_sha256: source.sha256, window_id: '', start_seconds: '', end_seconds: '', observed_seconds: '', note: '' }] }); }}>이 항목 영상 근거 추가</button>
      <p className="fine">창 선택만으로 실제 확인 시간을 채우지 않습니다. 제출한 관찰값에는 영상/hash·실제 범위·확인량과 근거가 필요합니다. 여러 실제 창의 근거를 각각 추가할 수 있습니다.</p>
    </details>
  </article>;
}

function EvidenceEditor({ item, doc, value, change, remove }: { item: BehaviorItem; doc: SheetDocument; value: Evidence; change: (value: Evidence) => void; remove: () => void }) {
  const player = useRef<HTMLVideoElement>(null);
  const windows = doc.source.windows.filter(window => item.windows.includes(window.window_id));
  const window = windows.find(window => window.window_id === value.window_id);
  const parts = window ? windowParts(doc, window) : [];
  function update(patch: Partial<Evidence>) { change({ ...value, ...patch }); }
  return <div className="evidence-editor">
    <label>근거 관찰창<select aria-label="근거 관찰창" value={value.window_id} onChange={event => update({ window_id: event.target.value })}><option value="">실제 창 선택</option>{windows.filter(window => ['available', 'partial'].includes(window.status)).map(window => <option key={window.window_id} value={window.window_id}>{window.window_id}</option>)}</select></label>
    <label>원본 영상<select value={value.video_id} onChange={event => { const source = doc.source.session.videos.find(video => video.video_id === event.target.value)!; update({ video_id: source.video_id, video_sha256: source.sha256 }); }}>{doc.source.session.videos.filter(video => video.video_id === doc.source.session.recording.video_id || doc.source.session.recording.video_offsets.some(offset => offset.video_id === video.video_id && offset.confirmed)).map(video => <option key={video.video_id} value={video.video_id}>{video.original_name}</option>)}</select></label>
    {window && <><video ref={player} controls preload="none" src={`/api/cases/${doc.sheet.case_id}/videos/${value.video_id}`} />{parts.map(part => <button key={part.window_id} type="button" onClick={() => { const shift = doc.source.session.recording.video_offsets.find(offset => offset.video_id === value.video_id)?.offset_seconds ?? 0; if (player.current) player.current.currentTime = (part.start_sec ?? part.source_point_sec ?? 0) + shift; }}>{parts.length > 1 ? `${part.start_sec}~${part.end_sec}초 범위 시작으로 이동` : '선택 창 시작으로 이동'}</button>)}</>}
    <div className="row"><label>원본 근거 시작 초<input type="number" step="any" min="0" value={value.start_seconds} onChange={event => update({ start_seconds: event.target.value === '' ? '' : Number(event.target.value) })} /></label><label>원본 근거 끝 초<input type="number" step="any" min="0" value={value.end_seconds} onChange={event => update({ end_seconds: event.target.value === '' ? '' : Number(event.target.value) })} /></label><label>실제 확인 초<input type="number" step="any" min="0" value={value.observed_seconds} onChange={event => update({ observed_seconds: event.target.value === '' ? '' : Number(event.target.value) })} /></label></div>
    <label>영상/조건 근거<input value={value.note} onChange={event => update({ note: event.target.value })} /></label>
    <button type="button" onClick={remove}>이 영상 근거 제거</button>
  </div>;
}
