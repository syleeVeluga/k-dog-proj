import { useEffect, useRef, useState } from 'react';
import { accessLost, api } from './api';
import { useUnsaved } from './Editing';
import type { User } from './types';
import type { CohortCandidateV4 } from './comparisonTypesV4';
import type { ReferenceBindingV4, ReferenceCellV4, ReferenceRowV4, ReferenceSelectionV4, ValidationPreviewV4, ValidationHistoryV4, ValidationViewV4, WorkbookViewV4 } from './researchTypesV4';

const confirmations = { unconfirmed: '미확정', human_confirmed: '사람 확정으로 전달됨', recheck_required: '재확인 필요', ai_provisional: 'AI 잠정값', example: '예시', legacy_semantics: '구판 의미', unobserved: '미관찰' };
const exposures = { unknown: '노출 여부 미확인', independent_claimed: '독립 평가로 전달됨 (미검증)', ai_exposed: 'AI 노출 후', human_exposed: '다른 사람 평가 노출 후' };
const text = (value: unknown): string => value === null || value === undefined ? '없음 (null)' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const message = (error: unknown) => error instanceof Error ? error.message : '검수 자료 작업에 실패했습니다.';
const blank = (): ReferenceSelectionV4 => ({ source_subject: '', sheet: '', cell: '', code: '', window_id: null, source_edition: 'unknown', evaluator: null, evaluator_status: 'unknown', confirmation: 'unconfirmed', exposure: 'unknown', reason: '' });

export function ValidationData({ user }: { user: User }) {
  const [candidates, setCandidates] = useState<CohortCandidateV4[]>([]), [records, setRecords] = useState<ValidationHistoryV4[]>([]), [opened, setOpened] = useState<ValidationViewV4 | null>(null);
  const [file, setFile] = useState<{ name: string; base64: string } | null>(null), [book, setBook] = useState<WorkbookViewV4 | null>(null);
  const [selection, setSelection] = useState(blank), [rows, setRows] = useState<ReferenceSelectionV4[]>([]), [bindings, setBindings] = useState<ReferenceBindingV4[]>([]), [reason, setReason] = useState('');
  const [preview, setPreview] = useState<ValidationPreviewV4 | null>(null), [previewKey, setPreviewKey] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState(''), [unavailable, setUnavailable] = useState(false);
  const alive = useRef(true), pending = useRef(false), sequence = useRef(0), request = useRef({ key: '', id: '' });
  useUnsaved(!!file);
  const config = { filename: file?.name ?? '', expected_sha256: book?.source_sha256 ?? '', bindings, selections: rows, reason: reason.trim() };
  const configKey = JSON.stringify(config);
  const raw = book?.cells.find(cell => cell.sheet === selection.sheet && cell.cell === selection.cell);
  const subjects = [...new Set(rows.map(row => row.source_subject))];
  async function reload(checkOpened = true) {
    const seq = ++sequence.current;
    const [next, list] = await Promise.all([api<CohortCandidateV4[]>('/validation-data-s1/candidates'), api<ValidationHistoryV4[]>('/validation-data-s1')]);
    if (!alive.current || seq !== sequence.current) return;
    setCandidates(next); setRecords(list); setUnavailable(false);
    if (opened && checkOpened) {
      if (!list.some(row => 'reference' in row && row.reference.validation_id === opened.reference.validation_id)) { setOpened(null); setError('열어 둔 참고 자료는 현재 제공할 수 없습니다. 다른 자료는 계속 확인할 수 있습니다.'); return; }
      try { const value = await api<ValidationViewV4>(`/validation-data-s1/${opened.reference.validation_id}`); if (alive.current && seq === sequence.current) setOpened(value); }
      catch (e) { if (alive.current && seq === sequence.current) { setOpened(null); throw e; } }
    }
  }
  useEffect(() => { alive.current = true; void reload().catch(e => { if (alive.current) { setError(message(e)); setUnavailable(accessLost(e)); } }); return () => { alive.current = false; sequence.current++; }; }, [user.username]);
  async function work(action: () => Promise<void>) {
    if (pending.current) return; pending.current = true; setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { if (alive.current) { setError(message(e)); if (accessLost(e)) { setOpened(null); setPreview(null); setRecords([]); setUnavailable(true); } } }
    finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  async function inspect(value: File) {
    if (!value.name.toLowerCase().endsWith('.xlsx')) throw new Error('XLSX 파일을 선택하세요.');
    if (value.size > 20 * 1024 * 1024) throw new Error('검수 파일은 20 MiB 이하로 선택하세요.');
    const bytes = new Uint8Array(await value.arrayBuffer()); let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
    const base64 = btoa(binary), next = await api<WorkbookViewV4>('/validation-data-s1/workbook', 'POST', { file_base64: base64 });
    if (!alive.current) return;
    setFile({ name: value.name, base64 }); setBook(next); setRows([]); setBindings([]); setReason(''); setPreview(null); setPreviewKey(''); setSelection({ ...blank(), sheet: next.sheets[0] ?? '' });
  }
  function addRow() {
    if (!selection.source_subject.trim() || !selection.code.trim() || !selection.reason.trim() || !selection.source_edition.trim() || !/^[A-Z]{1,3}[1-9][0-9]{0,6}$/.test(selection.cell)) { setError('원본 대상 표기·항목 코드·셀 주소·판본·선택 사유를 확인하세요.'); return; }
    if (selection.evaluator_status === 'identified' && !selection.evaluator?.trim()) { setError('확인한 평가자를 직접 입력하세요.'); return; }
    const next = { ...selection, source_subject: selection.source_subject.trim(), code: selection.code.trim(), evaluator: selection.evaluator?.trim() || null, window_id: selection.window_id?.trim() || null, source_edition: selection.source_edition.trim(), reason: selection.reason.trim() };
    if (rows.some(row => row.source_subject === next.source_subject && row.sheet === next.sheet && row.cell === next.cell)) { setError('이 원본 대상의 같은 셀을 이미 선택했습니다.'); return; }
    setRows([...rows, next]); setError(''); setSelection({ ...selection, cell: '', code: '', window_id: null });
  }
  function bind(subject: string, caseId: string) {
    const candidate = candidates.find(item => item.case_id === caseId), other = bindings.filter(row => row.source_subject !== subject);
    setBindings(candidate ? [...other, { source_subject: subject, case_id: caseId, session_id: candidate.sessions.length === 1 ? candidate.sessions[0].session_id : '', expected_revision: candidate.input_revision, match_basis: 'operator_verified', reason: '', participation: 'unknown' }] : other);
  }
  function updateBinding(subject: string, patch: Partial<ReferenceBindingV4>) { setBindings(bindings.map(row => row.source_subject === subject ? { ...row, ...patch } : row)); }
  async function submit(save: boolean) {
    if (!file || !book || !rows.length || !reason.trim() || bindings.some(row => !row.session_id || !row.reason.trim())) throw new Error('선택 행, 등록 사유와 대상 대응표를 완성하세요.');
    if (save && (!preview || previewKey !== configKey)) throw new Error('현재 선택을 먼저 미리보기 하세요.');
    if (request.current.key !== configKey) request.current = { key: configKey, id: crypto.randomUUID() };
    const body = { config: { ...config, request_id: request.current.id }, file_base64: file.base64 };
    if (!save) { const value = await api<ValidationPreviewV4>('/validation-data-s1/preview', 'POST', body); if (alive.current) { setPreview(value); setPreviewKey(configKey); } }
    else {
      const value = await api<ValidationViewV4>('/validation-data-s1', 'POST', body);
      if (!alive.current) return; setOpened(value); setFile(null); setBook(null); setRows([]); setBindings([]); setPreview(null); setReason(''); setSelection(blank()); setNotice('검수 참고 자료를 등록했습니다. 현재 점수와 독립 정답에는 반영하지 않습니다.'); await reload(false);
    }
  }
  if (unavailable) return <section className="panel"><h1>검수 자료</h1><p role="alert">{error}</p></section>;
  return <section className="panel" aria-label="검수 참고 자료" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h1>검수 자료</h1><p>원본 셀과 전달된 상태를 보존하는 참고 등록입니다. 현재 S1 채점 시트에 복사하지 않으며, 독립 사람 정답 여부는 G03 확인 대기입니다. S1 빈 입력 양식의 G01·G04 승인과도 별개입니다.</p>
    <p className="fine">수식은 실행하지 않습니다. 파일에 저장된 캐시는 실제 Excel 재계산이나 앱 실측 결과가 아닙니다. 보호자 이름을 평가자로 자동 지정하지 않습니다.</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy}><legend>참고 파일과 셀 선택</legend><label>검수 XLSX 파일<input type="file" accept=".xlsx" onChange={event => { const value = event.target.files?.[0]; event.target.value = ''; if (value && (!file || window.confirm('현재 파일의 미등록 선택을 버리고 새 파일을 검사할까요?'))) void work(() => inspect(value)); }} /></label>
      {file && book && <><p>{file.name} · SHA-256: {book.source_sha256}</p><label>원본 시트<select aria-label="원본 시트" value={selection.sheet} onChange={event => setSelection({ ...selection, sheet: event.target.value, cell: '' })}>{book.sheets.map(sheet => <option key={sheet}>{sheet}</option>)}</select></label>
        <label>원본 셀 주소<input placeholder="B2" value={selection.cell} maxLength={10} onChange={event => setSelection({ ...selection, cell: event.target.value.toUpperCase() })} /></label>
        <p className="fine">현재 시트의 기록된 셀: {book.cells.filter(cell => cell.sheet === selection.sheet).slice(0, 80).map(cell => cell.cell).join(', ')}{book.cells.filter(cell => cell.sheet === selection.sheet).length > 80 ? ' … (주소를 직접 입력하면 검사합니다)' : ''}</p>
        {raw ? <Cell value={raw} /> : selection.cell && <p>이 주소에 저장된 셀 값이 없습니다. 선택하면 결측(null)로 보존합니다.</p>}
        <div className="form-grid"><label>원본 대상 표기<input value={selection.source_subject} maxLength={500} onChange={event => setSelection({ ...selection, source_subject: event.target.value })} /></label><label>원본 항목 코드<input placeholder="개8" value={selection.code} maxLength={100} onChange={event => setSelection({ ...selection, code: event.target.value })} /></label><label>관찰창 (알 때만)<input value={selection.window_id ?? ''} onChange={event => setSelection({ ...selection, window_id: event.target.value || null })} /></label><label>전달된 판본<input value={selection.source_edition} onChange={event => setSelection({ ...selection, source_edition: event.target.value })} /></label><label>평가자 확인<select aria-label="평가자 확인" value={selection.evaluator_status} onChange={event => setSelection({ ...selection, evaluator_status: event.target.value as ReferenceSelectionV4['evaluator_status'], evaluator: event.target.value === 'unknown' ? null : '' })}><option value="unknown">미확인</option><option value="identified">명시 확인</option></select></label><label>확인한 평가자<input disabled={selection.evaluator_status === 'unknown'} value={selection.evaluator ?? ''} onChange={event => setSelection({ ...selection, evaluator: event.target.value })} /></label><label>전달된 확정 상태<select aria-label="전달된 확정 상태" value={selection.confirmation} onChange={event => setSelection({ ...selection, confirmation: event.target.value as ReferenceSelectionV4['confirmation'] })}>{Object.entries(confirmations).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label>평가 독립·노출 상태<select aria-label="평가 독립·노출 상태" value={selection.exposure} onChange={event => setSelection({ ...selection, exposure: event.target.value as ReferenceSelectionV4['exposure'] })}>{Object.entries(exposures).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label></div>
        <label>셀 선택·상태 판단 사유<input value={selection.reason} maxLength={4000} onChange={event => setSelection({ ...selection, reason: event.target.value })} /></label><button onClick={addRow}>참고 행 선택에 추가</button>
        {rows.length > 0 && <><h2>선택한 {rows.length}개 참고 행</h2>{rows.map((row, index) => <p key={`${row.source_subject}:${row.sheet}:${row.cell}`}>{row.source_subject} · {row.sheet}!{row.cell} · {row.code} · {confirmations[row.confirmation]} · {row.evaluator ?? '평가자 미확인'} <button onClick={() => { const next = rows.filter((_, i) => i !== index); setRows(next); setBindings(bindings.filter(binding => next.some(item => item.source_subject === binding.source_subject))); }}>행 {index + 1} 선택 해제</button></p>)}
          <h2>명시 대상·회차 대응표</h2><p>동명이인이나 표기 차이를 이름만으로 연결하지 않습니다. 미연결·참여 중단·미확인은 독립 정답 분모에서 제외됩니다.</p>
          {subjects.map(subject => { const binding = bindings.find(row => row.source_subject === subject), candidate = candidates.find(row => row.case_id === binding?.case_id); return <fieldset key={subject}><legend>{subject} 대응</legend><label>대응 대상<select aria-label={`${subject} 대응 대상`} value={binding?.case_id ?? ''} onChange={event => bind(subject, event.target.value)}><option value="">대상 미연결</option>{candidates.map(item => <option key={item.case_id} value={item.case_id}>{item.event_id} / {item.participant_id} · {item.dog_name}</option>)}</select></label>{binding && <><label>대응 회차<select aria-label={`${subject} 대응 회차`} value={binding.session_id} onChange={event => updateBinding(subject, { session_id: event.target.value })}><option value="">회차 선택</option>{candidate?.sessions.map(session => <option key={session.session_id} value={session.session_id}>{session.note || session.session_id}</option>)}</select></label><p>선택한 입력 r{binding.expected_revision}{candidate?.input_revision !== binding.expected_revision && ' · 현재 판본과 다름: 대상을 다시 선택해 명시 교체하세요.'}</p><label>대응 근거<select aria-label="대응 근거" value={binding.match_basis} onChange={event => updateBinding(subject, { match_basis: event.target.value as ReferenceBindingV4['match_basis'] })}><option value="operator_verified">운영자 직접 확인</option><option value="stable_id">안정 식별번호</option><option value="explicit_alias">표기 차이 직접 확인</option></select></label><label>원본 참여 상태<select aria-label="원본 참여 상태" value={binding.participation} onChange={event => updateBinding(subject, { participation: event.target.value as ReferenceBindingV4['participation'] })}><option value="unknown">미확인</option><option value="active">참여</option><option value="withdrawn">참여 중단</option></select></label><label>대응 확인 사유<input value={binding.reason} maxLength={4000} onChange={event => updateBinding(subject, { reason: event.target.value })} /></label></>}</fieldset>; })}
          <label>참고 등록 사유<textarea value={reason} maxLength={4000} onChange={event => setReason(event.target.value)} /></label><button disabled={!reason.trim()} onClick={() => void work(() => submit(false))}>선택 자료 미리보기</button><button disabled={!preview || previewKey !== configKey} onClick={() => void work(() => submit(true))}>참고 자료로 등록</button>
        </>}
        {preview && previewKey === configKey && <section aria-label="검수 참고 미리보기"><h2>등록 전 분류 확인</h2><p>원본 식별: {preview.source_inventory_id ?? '전달 원본 목록과 일치 미확인'} · 독립 정답 제외 · 현재 점수 반영 안 함</p><Rows rows={preview.rows} /></section>}
        <button onClick={() => { if (window.confirm('미등록 파일과 선택 내용을 비울까요?')) { setFile(null); setBook(null); setRows([]); setBindings([]); setPreview(null); setReason(''); } }}>미등록 선택 비우기</button>
      </>}
    </fieldset>
    <section aria-label="등록한 검수 참고 자료"><h2>내가 등록한 참고 자료</h2><button disabled={busy} onClick={() => void work(reload)}>참고 자료 목록 새로고침</button>{records.length === 0 && <p>등록한 자료가 없습니다.</p>}{records.map(row => 'reference' in row ? <p key={row.reference.validation_id}>{row.filename} · {row.row_count}행 · 연결 대상 {row.mapped_subject_count}개 <button disabled={busy} onClick={() => void work(async () => { const value = await api<ValidationViewV4>(`/validation-data-s1/${row.reference.validation_id}`); if (alive.current) setOpened(value); })}>참고 기록 열기 {row.reference.validation_id.slice(0, 8)}</button></p> : <p key={row.validation_id}>참고 자료 {row.validation_id.slice(0, 8)} · 제공 차단: {row.reason}</p>)}</section>
    {opened && <section aria-label="보존한 검수 참고 기록"><h2>{opened.filename} · 참고 기록</h2><p>원본 SHA-256: {opened.document.source.hash}</p><p>등록 {opened.document.recorded_at} · 수식 재계산 안 함 · G03 정답 미확정</p>{opened.document.bindings.map(binding => <p key={binding.source_subject}>{binding.source_subject} → {binding.case_id} / {binding.session_id} · 입력 r{binding.expected_revision} · {binding.participation} · {binding.reason}</p>)}<Rows rows={opened.document.rows} /></section>}
  </section>;
}

function Cell({ value }: { value: ReferenceCellV4 }) { return <div className="notice" aria-label="원본 셀 검사"><p>{value.sheet}!{value.cell} · 원본 형식 {value.raw_type}</p><p>원값: {text(value.value)} · XML 원문 값: {text(value.raw_xml_value)}</p><p>수식: {value.formula ?? '없음'} · 저장 캐시: {value.cache_present ? text(value.cached_value) : '없음'}</p>{Object.keys(value.formula_attributes).length > 0 && <p>수식 속성: {text(value.formula_attributes)}</p>}</div>; }
function Rows({ rows }: { rows: ReferenceRowV4[] }) { return <div>{rows.map((row, index) => <details key={index} open={rows.length < 5}><summary>{row.selection.source_subject} · {row.selection.sheet}!{row.selection.cell} · {row.selection.code} · {confirmations[row.effective_status as keyof typeof confirmations] ?? row.effective_status}</summary><Cell value={row.source} /><p>평가자: {row.selection.evaluator ?? '미확인'} · {exposures[row.selection.exposure]} · 판본 {row.selection.source_edition}</p><p>사유: {row.selection.reason}</p><p>독립 정답 제외 사유: {row.exclusion_reasons.join(' · ')}</p></details>)}</div>; }
