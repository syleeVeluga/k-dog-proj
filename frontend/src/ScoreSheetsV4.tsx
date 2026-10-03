import { useEffect, useRef, useState } from 'react';
import { accessLost, api } from './api';
import { BasicResultsV4 } from './BasicResultsV4';
import { mayLeave, useEditBase, useUnsaved } from './Editing';
import { formFields, type Case, type Run, type User } from './types';
import type { BehaviorCatalogV4, BehaviorItemV4, EvidenceV4, LinkedMemoV4, ObservationV4, SheetDocumentV4, SheetSummaryV4, SheetViewV4, WalkPhaseV4 } from './ScoringTypesV4';
import './ScoreSheetsV4.css';

const statuses = { observed: '관찰한 원값', unobserved: '미관찰', no_opportunity: '기회 없음 (NA)', not_performed: '미실시', invalid: '유효하지 않음', insufficient_observation: '관찰량 부족', policy_pending: '규칙 확인 대기' };
const purposes = { independent: '독립 원자료', review: '공개 후 검수', consensus: '합의 기록' };
const segments = [['entry', '입장'], ['baseline', '기준'], ['alone', '혼자'], ['reunion', '재회'], ['ignore', '무시'], ['walk', '걷기'], ['stranger', '낯선 사람'], ['exit', '퇴장']];
const vocalCodes = ['바6', '개11', '개47', '개48', '개49', '개50'];
const blank = (code: string): ObservationV4 => ({ code, value: null, status: 'unobserved', reason: '', opportunity: 'unknown', validity: 'unknown', whole_interval_observed: false, evidence: [], vocalization: null, review_memo: null });
const blankEvidence = (): EvidenceV4 => ({ video_id: '', video_sha256: '', camera_id: '', window_id: '', start_seconds: '', end_seconds: '', observed_seconds: '', note: '' });
const signed = (value: number) => value > 0 ? `+${value}` : String(value);
const errorText = (error: unknown) => error instanceof Error ? error.message : '채점 작업을 완료하지 못했습니다.';

export function ScoreSheetsV4({ item, user, run, refresh, close }: { item: Case; user: User; run: Run; refresh: (message?: string) => Promise<void>; close: () => void }) {
  const manager = user.role === 'operator' || user.role === 'admin';
  const [rows, setRows] = useState<SheetSummaryV4[]>([]);
  const [accounts, setAccounts] = useState<User[]>([]);
  const [catalog, setCatalog] = useState<BehaviorCatalogV4 | null>(null);
  const [sheetId, setSheetId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [assignmentDirty, setAssignmentDirty] = useState(false);
  const assignmentBase = useRef<number | null>(null);
  useUnsaved(assignmentDirty);
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}/sheets-s1`;
  async function reload() { setRows(await api<SheetSummaryV4[]>(path)); }
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const value = await api<SheetSummaryV4[]>(path); if (active) setRows(value); }
      catch (reason) { if (active) { setError(errorText(reason)); if (accessLost(reason)) { setRows([]); setSheetId(''); } } }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll();
    api<BehaviorCatalogV4>('/catalog/behavior-s1').then(value => { if (active) setCatalog(value); }).catch(reason => { if (active) setError(errorText(reason)); });
    if (manager) api<User[]>('/scoring/accounts').then(value => { if (active) setAccounts(value); }).catch(reason => { if (active) setError(errorText(reason)); });
    return () => { active = false; clearTimeout(timer); };
  }, [path, manager]);
  async function work(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    await run(async () => { try { await action(); await reload(); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); } });
  }
  return <section className="scoring-s1 panel" aria-label="S1 평가 배정">
    <div className="section-title"><h2>{item.dog_name} · S1 독립 채점</h2><button onClick={close}>닫기</button></div>
    <p>숫자 83개 · 메모 3개 · 자동 4개. 원값 0과 빈값을 구분하고 실제 관찰 근거를 기록합니다.</p>
    <p role="status">S1 Excel 가져오기 비활성 — 실제 빈양식·검증용 원본 G01/G04 수령 후 확인이 필요합니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {manager && <details><summary>평가자 배정</summary><form onChange={() => { assignmentBase.current ??= item.input_revision; setAssignmentDirty(true); }} onSubmit={event => {
      event.preventDefault(); const values = formFields(event.currentTarget); const form = event.currentTarget;
      void work(async () => { await api(path, 'POST', { ...values, expected_revision: assignmentBase.current ?? item.input_revision, source_sheet_id: values.source_sheet_id || null }); form.reset(); assignmentBase.current = null; setAssignmentDirty(false); });
    }}><fieldset disabled={busy} className="form-grid">
      <label>입력 계정<select aria-label="입력 계정" name="assigned_username" required><option value="">활성 계정 선택</option>{accounts.map(account => <option key={account.username} value={account.username}>{account.username}</option>)}</select></label>
      <label>평가자 ID<input name="rater_id" pattern="[A-Za-z0-9][A-Za-z0-9_-]*" required /></label><label>평가자 표시 이름<input name="rater_name" required /></label>
      <label>기록 목적<select aria-label="기록 목적" name="purpose"><option value="independent">독립 원자료</option><option value="review">검수 기록</option><option value="consensus">합의 기록</option></select></label>
      <label>촬영 입력 선택<select aria-label="촬영 입력 선택" name="source_sheet_id"><option value="">현재 확정 촬영 입력</option>{rows.map(row => <option key={row.sheet_id} value={row.sheet_id}>{row.rater_name}과 동일한 고정 입력</option>)}</select></label>
      <button type="submit">시트 배정</button>
      <button type="button" onClick={() => void refresh()}>현재 접수 버전 새로고침</button>
      {assignmentDirty && <button type="button" onClick={event => { if (window.confirm('배정 입력을 버리고 최신 접수 버전을 사용할까요?')) { event.currentTarget.form?.reset(); assignmentBase.current = null; setAssignmentDirty(false); } }}>배정 입력 버리고 다시 시작</button>}
    </fieldset><p className="fine">비교할 평가자는 동일한 고정 입력을 선택하세요. 새로운 batch나 재배정은 같은 촬영의 독립성을 초기화하지 않습니다.</p></form></details>}
    {!rows.length && <p role="status">배정된 시트가 없습니다. 실제 촬영 기록을 확정한 뒤 평가자를 배정하세요.</p>}
    <ul className="sheet-list">{rows.map(row => <li key={row.sheet_id}><strong>{row.rater_name}</strong> · {purposes[row.purpose]} · {row.state === 'submitted' ? '제출·잠금' : '초안'} · r{row.revision} · {row.active ? '배정 활성' : '배정 취소'}
      {row.own && row.active && <button onClick={() => { if (mayLeave()) setSheetId(row.sheet_id); }}>내 시트 열기</button>}
      {manager && <ManagerActions row={row} rows={rows} busy={busy} work={work} />}
      <details><summary>배정 출처</summary><p>평가자 {row.rater_id} · 계정 {row.assigned_username} · {row.rater_kind === 'ai' ? 'AI' : '사람'}</p><p>고정 입력 {row.source_hash}</p><p>시트 {row.sheet_id} · r{row.revision} · {row.manifest_hash}</p></details>
    </li>)}</ul>
    {sheetId && catalog && <SheetEditor key={sheetId} sheetId={sheetId} catalog={catalog} done={reload} />}
  </section>;
}

function ManagerActions({ row, rows, busy, work }: { row: SheetSummaryV4; rows: SheetSummaryV4[]; busy: boolean; work: (action: () => Promise<unknown>) => Promise<void> }) {
  const [reason, setReason] = useState(''); const [target, setTarget] = useState('');
  const path = `/score-sheets-s1/${row.sheet_id}`;
  return <details><summary>{row.rater_name} 배정/공개 관리</summary><label>작업 사유<input value={reason} onChange={event => setReason(event.target.value)} /></label>
    <div className="toolbar">
      {row.state === 'submitted' && row.rater_kind === 'human' && <button disabled={busy || !reason.trim() || !row.active} onClick={() => void work(() => api(path + '/reopen', 'POST', { expected_revision: row.revision, reason }))}>이 시트 재개방</button>}
      <button disabled={busy || !reason.trim()} onClick={() => void work(() => api(path + '/assignment', 'POST', { expected_revision: row.revision, reason, active: !row.active }))}>{row.active ? '배정 취소' : '배정 재활성'}</button>
    </div>
    <label>명시 공개할 다른 완료본<select aria-label="명시 공개할 다른 완료본" value={target} onChange={event => setTarget(event.target.value)}><option value="">완료 시트 선택</option>{rows.filter(other => other.sheet_id !== row.sheet_id && other.state === 'submitted' && other.active && other.source_hash === row.source_hash).map(other => <option key={other.sheet_id} value={other.sheet_id}>{other.rater_name} r{other.revision}</option>)}</select></label>
    <button disabled={busy || !reason.trim() || !target || row.state !== 'submitted' || !row.active} onClick={() => void work(() => api(path + '/grants', 'POST', { expected_revision: row.revision, reason, target_sheet_id: target, target_revision: rows.find(other => other.sheet_id === target)?.revision }))}>선택한 완료본 공개 허용</button>
    <p className="fine">공개 허용 후 실제 열람 때 노출을 기록합니다. 독립 제출 원본은 보존됩니다.</p>
  </details>;
}

function SheetEditor({ sheetId, catalog, done }: { sheetId: string; catalog: BehaviorCatalogV4; done: () => Promise<void> }) {
  const [latest, setLatest] = useState<SheetViewV4 | null>(null);
  const [observations, setObservations] = useState<ObservationV4[]>([]);
  const [phases, setPhases] = useState<WalkPhaseV4[]>([]);
  const [memos, setMemos] = useState<LinkedMemoV4[]>([]);
  const [segment, setSegment] = useState(''); const [search, setSearch] = useState('');
  const [reason, setReason] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [revealed, setRevealed] = useState<SheetDocumentV4 | null>(null); const [historical, setHistorical] = useState<SheetDocumentV4 | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const edit = useEditBase(latest); const clean = useRef(true); clean.current = !edit.dirty;
  const path = `/score-sheets-s1/${sheetId}`;
  function adopt(value: SheetViewV4) { setObservations(value.document.sheet.observations); setPhases(value.document.sheet.walk_phases); setMemos(value.document.sheet.linked_memos); }
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const value = await api<SheetViewV4>(path); if (active) { setLatest(value); setUnavailable(false); if (clean.current) adopt(value); } }
      catch (failure) { if (active) { setError(errorText(failure)); if (accessLost(failure)) { setUnavailable(true); setRevealed(null); setHistorical(null); } } }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [path]);
  const view = edit.view;
  if (!view || unavailable) return <p role="status">{error || '내 시트 조회 중…'}</p>;
  const doc = historical ?? view.document;
  const writable = !historical && doc.sheet.rater_kind === 'human' && doc.state === 'draft' && doc.active && latest?.summary.active && latest.summary.state === 'draft';
  const entries = historical ? doc.sheet.observations : observations;
  const walk = historical ? doc.sheet.walk_phases : phases;
  const linked = historical ? doc.sheet.linked_memos : memos;
  const shown = catalog.items.filter(item => (!segment || item.segment === segment) && (!search || `${item.code} ${item.text}`.includes(search)));
  function change(value: ObservationV4) { edit.change(); setObservations(previous => [...previous.filter(item => item.code !== value.code), value]); }
  async function work(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); const saved = await api<SheetViewV4>(path); setLatest(saved); adopt(saved); edit.reset(); setReason(''); await done(); }
    catch (failure) { setError(errorText(failure)); if (accessLost(failure)) { setUnavailable(true); setRevealed(null); } }
    finally { setBusy(false); }
  }
  function checkDraft() {
    for (const observation of observations) {
      if (observation.status === 'observed' ? observation.value === null || observation.value === '' : !observation.reason?.trim()) throw new Error(`${observation.code}: 원값 또는 명시한 빈값 사유를 기록하세요.`);
      for (const evidence of observation.evidence) if (!evidence.video_id || !evidence.window_id || !evidence.note.trim() || [evidence.start_seconds, evidence.end_seconds, evidence.observed_seconds].includes('')) throw new Error(`${observation.code}: 근거 영상·창·실제 범위·관찰 초·설명을 모두 기록하세요.`);
    }
    if (!reason.trim()) throw new Error('저장·정정 사유를 기록하세요.');
  }
  return <section className="scoring-editor" aria-label="내 S1 채점 시트"><h2>{doc.rater_name} · {purposes[doc.purpose]}</h2>
    {error && <p role="alert" className="error">{error}</p>}
    <p role="status">{doc.state === 'submitted' ? '제출본 잠금 · 원본은 보존됩니다.' : '초안 · 저장 후 제출합니다.'} · 다른 완료본 노출 {doc.exposures.length}개 · {doc.sheet.ai_exposed ? 'AI 결과 노출됨' : 'AI 결과 미노출'}</p>
    {view.outdated && <p role="status">접수·촬영 입력이 변경되었습니다. 배정 당시 고정한 영상과 실제 창을 사용합니다.</p>}
    {edit.dirty && latest && latest.summary.revision !== view.summary.revision && <p role="status">다른 변경이 저장되었습니다. 미저장 입력과 편집 시작 버전을 유지합니다.</p>}
    <p>직접 입력 86행 중 {entries.length}행 기록 · 필수 84행, 선택 바54·바55. 0은 관찰한 값이며 미기록·NA·관찰량 부족·규칙 대기와 다릅니다.</p>
    <p>저장본 필수 미기록 {view.missing_required_codes.length}개 · 규칙 대기 {view.policy_pending_codes.join(', ') || '없음'}</p>
    <label>보존본 조회<select aria-label="보존본 조회" disabled={busy || edit.dirty} value={historical?.revision ?? ''} onChange={event => {
      const value = event.target.value; if (!value) { setHistorical(null); return; }
      void work(async () => setHistorical(await api<SheetDocumentV4>(path + `/revisions/${value}`)));
    }}><option value="">현재 작업본 r{view.summary.revision}</option>{view.document.previous.map(ref => <option key={ref.ref} value={ref.revision}>보존본 r{ref.revision}</option>)}</select></label>
    {historical && <p role="status">보존본 읽기 전용</p>}
    <div className="toolbar"><label>8구간 필터<select aria-label="8구간 필터" value={segment} onChange={event => setSegment(event.target.value)}><option value="">전체</option>{segments.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><label>원코드/항목 검색<input value={search} onChange={event => setSearch(event.target.value)} /></label></div>
    <fieldset disabled={busy || !writable}>{shown.map(item => item.usage === 'automatic' ? <article key={item.code} aria-label={`${item.code} 자동 계산`}><h3>{item.code} · {item.text}</h3><p>자동 계산 · 읽기 전용</p><p>{item.automatic_formula}</p><p>값은 고정 원자료의 계산 결과에서 확인합니다.</p></article> : <ObservationEditor key={`${item.code}:${edit.key}`} item={item} value={entries.find(value => value.code === item.code)} doc={doc} change={change} remove={() => { edit.change(); setObservations(values => values.filter(value => value.code !== item.code)); }} phase={walk.find(value => value.code === item.code)} phaseChange={value => { edit.change(); setPhases(values => [...values.filter(old => old.code !== item.code), ...(value ? [value] : [])]); }} />)}
      <details><summary>개59 연결 메모 · 별도 보존</summary><p>항목의 숫자·기회·상태를 바꾸지 않는 연결 메모입니다.</p>
        {linked.map((memo, index) => <article key={index} aria-label="개59 연결 메모"><label>개59 메모<textarea value={memo.text} onChange={event => { edit.change(); setMemos(values => values.map((value, position) => position === index ? { ...value, text: event.target.value } : value)); }} /></label>
          <label>개59 연결 항목<select aria-label="개59 연결 항목" multiple value={memo.item_codes} onChange={event => { const codes = Array.from(event.target.selectedOptions).map(option => option.value); edit.change(); setMemos(values => values.map((value, position) => position === index ? { ...value, item_codes: codes } : value)); }}>{catalog.items.map(item => <option key={item.code} value={item.code}>{item.code} · {item.text}</option>)}</select></label>
          <EvidenceList doc={doc} windows={doc.source.windows.map(window => window.window_id)} values={memo.evidence} change={evidence => { edit.change(); setMemos(values => values.map((value, position) => position === index ? { ...value, evidence } : value)); }} />
          <button onClick={() => { edit.change(); setMemos(values => values.filter((_, position) => position !== index)); }}>이 연결 메모 제거</button></article>)}
        <button onClick={() => { edit.change(); setMemos(values => [...values, { code: '개59', text: '', item_codes: [], evidence: [] }]); }}>개59 연결 메모 추가</button>
      </details>
    </fieldset>
    {writable && <><label>저장·정정 사유<input value={reason} onChange={event => { edit.change(); setReason(event.target.value); }} /></label><div className="toolbar">
      <button disabled={busy || !edit.dirty} onClick={() => void work(() => { checkDraft(); return api(path, 'PUT', { expected_revision: view.summary.revision, observations, walk_phases: phases, linked_memos: memos, reason }); })}>채점 초안 저장</button>
      <button disabled={busy || edit.dirty || view.missing_required_codes.length > 0} onClick={() => void work(() => api(path + '/submit', 'POST', { expected_revision: view.summary.revision, reason: `평가자 ${purposes[doc.purpose]} 제출` }))}>{purposes[doc.purpose]} 제출·잠금</button>
    </div></>}
    {edit.dirty && <button disabled={busy} onClick={() => { if (edit.discard() && latest) { adopt(latest); setReason(''); setError(''); } }}>미저장 입력 버리고 최신 조회</button>}
    {!historical && view.grants.length > 0 && <details><summary>명시 공개된 완료본</summary><p>실제 열람하면 노출 이력을 기록하고 이후 입력은 검수 기록으로 구분합니다.</p>{view.grants.map(grant => <button key={grant.ref} disabled={busy || edit.dirty || doc.state !== 'submitted'} onClick={() => void work(async () => { const result = await api<{ target: SheetDocumentV4 }>(path + '/reveal', 'POST', { expected_revision: view.summary.revision, ref: grant.ref }); setRevealed(result.target); })}>공개 완료본 r{grant.revision} 열고 노출 기록</button>)}</details>}
    {!historical && revealed && <details open><summary>{revealed.rater_name} 공개 완료본 r{revealed.revision}</summary><ul>{revealed.sheet.observations.map(value => <li key={value.code}>{value.code} · {value.value ?? value.reason} · {statuses[value.status]}</li>)}</ul><details><summary>공개한 원관찰과 근거</summary><pre>{JSON.stringify(revealed.sheet, null, 2)}</pre></details></details>}
    <details><summary>고정 입력·revision/hash·노출 이력</summary><pre>{JSON.stringify({ sheet_id: sheetId, revision: doc.revision, source_hash: doc.source_hash, input: doc.source.input, batch: doc.source.batch_id, initial_submission: doc.initial_submission, exposures: doc.exposures, previous: doc.previous }, null, 2)}</pre></details>
    {!historical && <BasicResultsV4 sheetId={sheetId} input={{ sheet_id: sheetId, revision: view.summary.revision, ref: view.summary.manifest_ref, hash: view.summary.manifest_hash }} blocked={busy || edit.dirty || doc.state !== 'submitted'} />}
  </section>;
}

function ObservationEditor({ item, value, doc, change, remove, phase, phaseChange }: { item: BehaviorItemV4; value?: ObservationV4; doc: SheetDocumentV4; change: (value: ObservationV4) => void; remove: () => void; phase?: WalkPhaseV4; phaseChange: (value: WalkPhaseV4 | null) => void }) {
  const row = value ?? blank(item.code);
  const phaseNumber = /^개(38|39|40|41|42|43)$/.test(item.code) ? Number(item.code.slice(1)) - 37 : null;
  const windowIds = [...item.windows, ...(phaseNumber ? [`walk_phase_${phaseNumber}`] : [])];
  function update(patch: Partial<ObservationV4>) { change({ ...row, ...patch }); }
  return <article className="scoring-item" aria-label={`${item.code} 원관찰`}><h3>{item.code} · {item.text} {item.optional ? '(선택 관찰)' : ''}</h3>
    <p className="fine">{item.segment_label} · {item.axis_label} · {item.scale_text}</p>
    {item.display_order.length > 0 && <p>선택 순서: {item.display_order.map(signed).join(' → ')}</p>}
    {item.category_priority.length > 0 && <p>범주 판정 우선순위: {item.category_priority.map(signed).join(' → ')}</p>}
    {item.policy_pending.length > 0 && <p>규칙 확인 대기 {item.policy_pending.join(', ')} — 관찰 원근거를 보존하고 미확정 종합값을 추정하지 마세요.</p>}
    {['보5', '보6', '보9', '보14'].includes(item.code) && <p>입장·퇴장 근거를 각각 남기고 퇴장 종합값을 한 번 기록합니다.</p>}
    <label>기록 상태<select aria-label={`${item.code} 기록 상태`} value={value?.status ?? ''} onChange={event => {
      const status = event.target.value as ObservationV4['status']; if (!status) { remove(); return; }
      update({ status, value: null, reason: status === 'observed' ? null : row.reason ?? '', opportunity: status === 'no_opportunity' ? 'absent' : row.opportunity, validity: status === 'invalid' ? 'invalid' : row.validity });
    }}><option value="">미기록 (빈칸)</option>{Object.entries(statuses).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
    <fieldset disabled={!value}>
      {row.status === 'observed' ? <label>{item.code} 원값{item.value_type === 'category' ? <select aria-label={`${item.code} 원값`} value={row.value ?? ''} onChange={event => update({ value: event.target.value === '' ? null : Number(event.target.value) })}><option value="">값 선택 (빈칸)</option>{item.display_order.map(number => <option key={number} value={number}>{signed(number)} · {item.labels.find(label => label.value === number)?.text}</option>)}</select> : item.value_type === 'memo' ? <textarea value={row.value ?? ''} onChange={event => update({ value: event.target.value })} /> : <input aria-label={`${item.code} 원값`} type="number" min="0" step="1" value={row.value ?? ''} onChange={event => update({ value: event.target.value === '' ? null : Number(event.target.value) })} />}</label> : <label>빈값 사유<input aria-label={`${item.code} 빈값 사유`} value={row.reason ?? ''} onChange={event => update({ reason: event.target.value })} /></label>}
      <div className="form-grid"><label>관찰 기회<select aria-label="관찰 기회" value={row.opportunity} onChange={event => update({ opportunity: event.target.value as ObservationV4['opportunity'] })}><option value="unknown">미확인</option><option value="present">있음</option><option value="absent">없음</option></select></label>
        <label>시행 유효 상태<select aria-label="시행 유효 상태" value={row.validity} onChange={event => update({ validity: event.target.value as ObservationV4['validity'] })}><option value="unknown">미확인</option><option value="valid">유효</option><option value="caution">주의</option><option value="invalid">유효하지 않음</option></select></label></div>
      <label className="check"><input type="checkbox" checked={row.whole_interval_observed} onChange={event => update({ whole_interval_observed: event.target.checked })} />실제 전체 구간 관찰 완료</label>
      {item.whole_interval_required && <p>전체 관찰 필수입니다. 일부 관찰은 null과 실제 사건·부족 사유로 남깁니다.</p>}
      <details><summary>{item.code} F 관찰 근거·영상</summary><EvidenceList doc={doc} windows={windowIds} values={row.evidence} change={evidence => update({ evidence })} /></details>
      {vocalCodes.includes(item.code) && <details><summary>{item.code} 전체 청취·누적 발성량</summary><p>분모는 중복 없는 실제 전체 구간입니다. 0·1/3·2/3 경계를 원값 선택과 대조합니다.</p>
        {!row.vocalization ? <button onClick={() => update({ vocalization: { listened_seconds: '', cumulative_vocal_seconds: '', whole_interval_judged: false, note: '' } })}>청취 기록 추가</button> : <>
          <Seconds label="실제 청취 초" value={row.vocalization.listened_seconds} change={listened_seconds => update({ vocalization: { ...row.vocalization!, listened_seconds } })} />
          <Seconds label="누적 발성 초" value={row.vocalization.cumulative_vocal_seconds} change={cumulative_vocal_seconds => update({ vocalization: { ...row.vocalization!, cumulative_vocal_seconds } })} />
          <label className="check"><input type="checkbox" checked={row.vocalization.whole_interval_judged} onChange={event => update({ vocalization: { ...row.vocalization!, whole_interval_judged: event.target.checked } })} />전체 실제 구간 청취 판독 완료</label>
          <label>청취·발성량 근거<input value={row.vocalization.note} onChange={event => update({ vocalization: { ...row.vocalization!, note: event.target.value } })} /></label>
          <button onClick={() => update({ vocalization: null })}>청취 기록 제거</button></>}
      </details>}
      {phaseNumber && <details><summary>{item.code} 걷기 거리 예외</summary><p>촬영 기록 예외: {doc.source.session.recording_s1.walk_phases[phaseNumber - 1]?.proximity_exception ?? '미기록'}</p>
        <label>거리 예외<select aria-label="거리 예외" value={phase?.proximity_exception ?? ''} onChange={event => phaseChange(event.target.value ? { code: item.code, proximity_exception: event.target.value as WalkPhaseV4['proximity_exception'], evidence: phase?.evidence ?? [], note: phase?.note ?? null } : null)}><option value="">미기록</option><option value="none">예외 없음 확인</option><option value="guardian_approach">보호자가 다가옴</option><option value="recheck">안전·거리 재확인</option><option value="unknown">미확인</option></select></label>
        {phase && <><label>거리 예외 근거<input value={phase.note ?? ''} onChange={event => phaseChange({ ...phase, note: event.target.value || null })} /></label><EvidenceList doc={doc} windows={windowIds} values={phase.evidence} change={evidence => phaseChange({ ...phase, evidence })} /></>}
      </details>}
      <label>G 양식 검토메모<textarea aria-label={`${item.code} G 양식 검토메모`} value={row.review_memo ?? ''} onChange={event => update({ review_memo: event.target.value || null })} /></label><p className="fine">G는 양식 검토용으로 보존하며 분석과 보호자 문장의 입력에서 제외됩니다.</p>
    </fieldset>
  </article>;
}

function Seconds({ label, value, change }: { label: string; value: number | ''; change: (value: number | '') => void }) {
  return <label>{label}<input aria-label={label} type="number" min="0" step="any" value={value} onChange={event => change(event.target.value === '' ? '' : Number(event.target.value))} /></label>;
}

function EvidenceList({ doc, windows, values, change }: { doc: SheetDocumentV4; windows: string[]; values: EvidenceV4[]; change: (values: EvidenceV4[]) => void }) {
  const available = doc.source.windows.filter(window => windows.includes(window.window_id));
  return <><ul>{available.map(window => <li key={window.window_id}>{window.window_id} · {window.source_intervals.filter(part => part.evidence_id === null).map(part => `${part.start_seconds}~${part.end_seconds}초`).join(' / ') || '관찰 범위 미확인'} · {window.status} · {window.reasons.join(' / ')}</li>)}</ul>
    {values.map((value, index) => <EvidenceEditor key={index} doc={doc} windows={windows} value={value} change={next => change(values.map((old, position) => index === position ? next : old))} remove={() => change(values.filter((_, position) => position !== index))} />)}
    <button onClick={() => change([...values, blankEvidence()])}>영상 근거 추가</button><p className="fine">영상과 관찰창을 명시적으로 선택한 뒤 원본 시각·실제 확인량·F 근거를 입력하세요. 선택만으로 관찰량을 채우지 않습니다.</p></>;
}

function EvidenceEditor({ doc, windows, value, change, remove }: { doc: SheetDocumentV4; windows: string[]; value: EvidenceV4; change: (value: EvidenceV4) => void; remove: () => void }) {
  const player = useRef<HTMLVideoElement>(null);
  const capture = doc.source.session.recording_s1;
  const video = doc.source.session.videos.find(video => video.video_id === value.video_id);
  const offset = value.video_id === capture.video_id ? 0 : capture.video_offsets.find(offset => offset.video_id === value.video_id && offset.confirmed)?.offset_seconds;
  const window = doc.source.windows.find(window => window.window_id === value.window_id);
  const parts = window?.source_intervals.filter(part => part.evidence_id === null) ?? [];
  function update(patch: Partial<EvidenceV4>) { change({ ...value, ...patch }); }
  return <div className="evidence-editor">
    <label>근거 관찰창<select aria-label="근거 관찰창" value={value.window_id} onChange={event => update({ window_id: event.target.value })}><option value="">실제 창 선택</option>{doc.source.windows.filter(window => windows.includes(window.window_id) && ['confirmed', 'partial'].includes(window.status)).map(window => <option key={window.window_id} value={window.window_id}>{window.window_id}</option>)}</select></label>
    <label>근거 원본 영상<select aria-label="근거 원본 영상" value={value.video_id} onChange={event => { const selected = doc.source.session.videos.find(video => video.video_id === event.target.value); update({ video_id: selected?.video_id ?? '', video_sha256: selected?.sha256 ?? '', camera_id: selected?.camera_id ?? '' }); }}><option value="">확정 카메라 영상 선택</option>{doc.source.session.videos.filter(video => video.camera_id && video.media_status !== 'storage_only' && (video.video_id === capture.video_id || capture.video_offsets.some(offset => offset.video_id === video.video_id && offset.confirmed && offset.offset_seconds !== null))).map(video => <option key={video.video_id} value={video.video_id}>{video.camera_id} · {video.original_name}</option>)}</select></label>
    {video && <><p>카메라 {value.camera_id} · 원본 SHA-256 {value.video_sha256} · 확정 오프셋 {offset ?? '미확인'}초</p><video ref={player} controls preload="none" src={`/api/cases/${doc.sheet.case_id}/videos/${value.video_id}`} />
      {offset !== undefined && offset !== null && parts.map((part, index) => <button key={index} onClick={() => { if (player.current) player.current.currentTime = part.start_seconds + offset; }}>{part.start_seconds + offset}~{part.end_seconds + offset}초 원본 범위 시작으로 이동</button>)}</>}
    <div className="form-grid"><Seconds label="원본 근거 시작 초" value={value.start_seconds} change={start_seconds => update({ start_seconds })} /><Seconds label="원본 근거 끝 초" value={value.end_seconds} change={end_seconds => update({ end_seconds })} /><Seconds label="실제 확인 초" value={value.observed_seconds} change={observed_seconds => update({ observed_seconds })} /></div>
    <label>F 관찰 근거<input value={value.note} onChange={event => update({ note: event.target.value })} /></label>
    <button onClick={remove}>이 영상 근거 제거</button>
  </div>;
}
