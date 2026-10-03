import { useEffect, useRef, useState } from 'react';
import { accessLost, api, ApiError } from './api';
import { useUnsaved } from './Editing';
import type { Case, User } from './types';
import type { SheetReferenceV4, SheetSummaryV4, SheetViewV4 } from './ScoringTypesV4';
import type { BasicReferenceV4, BasicSummaryV4, FinalReferenceV4, FinalSummaryV4, FinalViewV4 } from './finalTypesV4';
import type { CohortSummaryV4 } from './comparisonTypesV4';
import type { ReportRunV4 } from './reportTypesV4';
import type { ExportMemberSelectionV4, ExportViewV4, ValidationSummaryV4 } from './researchTypesV4';

type Source = { reference: SheetReferenceV4; viewer: string | null; label: string };
const message = (error: unknown) => error instanceof Error ? error.message : '연구 내보내기에 실패했습니다.';
const same = (a: SheetReferenceV4, b: SheetReferenceV4) => a.sheet_id === b.sheet_id && a.revision === b.revision && a.ref === b.ref && a.hash === b.hash;
const reference = (row: SheetSummaryV4): SheetReferenceV4 => ({ sheet_id: row.sheet_id, revision: row.revision, ref: row.manifest_ref, hash: row.manifest_hash });

export function ResearchExportsV4({ item, user }: { item: Case; user: User }) {
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const [sheets, setSheets] = useState<SheetSummaryV4[]>([]), [own, setOwn] = useState<SheetViewV4 | null>(null), [source, setSource] = useState<Source | null>(null);
  const [basics, setBasics] = useState<BasicSummaryV4[]>([]), [finals, setFinals] = useState<FinalSummaryV4[]>([]), [reports, setReports] = useState<ReportRunV4[]>([]);
  const [basic, setBasic] = useState<BasicReferenceV4 | null>(null), [final, setFinal] = useState<FinalReferenceV4 | null>(null), [report, setReport] = useState('');
  const [members, setMembers] = useState<{ value: ExportMemberSelectionV4; label: string }[]>([]), [format, setFormat] = useState<'csv_zip' | 'xlsx'>('csv_zip'), [reason, setReason] = useState(''), [redact, setRedact] = useState('');
  const [references, setReferences] = useState<ValidationSummaryV4[]>([]), [selectedReferences, setSelectedReferences] = useState<ValidationSummaryV4[]>([]), [cohorts, setCohorts] = useState<CohortSummaryV4[]>([]), [cohort, setCohort] = useState<CohortSummaryV4 | null>(null);
  const [history, setHistory] = useState<ExportViewV4[]>([]), [created, setCreated] = useState<ExportViewV4 | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false), [unavailable, setUnavailable] = useState(false);
  const alive = useRef(true), pending = useRef(false), sequence = useRef(0), request = useRef({ key: '', id: '' });
  const context = useRef(''); context.current = `${path}:${user.username}`;
  useUnsaved(members.length > 0);
  const currentSources: Source[] = own ? [
    { reference: reference(own.summary), viewer: null, label: `내 현재 시트 r${own.summary.revision} · ${own.effective_purpose === 'independent' ? '독립' : '공개 후 검수'}` },
    ...own.document.previous.map(pointer => ({ reference: pointer, viewer: null, label: `내 보존 시트 r${pointer.revision}` })),
    ...own.document.exposures.filter(pointer => own.grants.some(grant => same(grant, pointer))).map(pointer => ({ reference: pointer, viewer: own.summary.sheet_id, label: `실제 공개 원본 · ${sheets.find(row => row.sheet_id === pointer.sheet_id)?.rater_name ?? pointer.sheet_id.slice(0, 8)} · r${pointer.revision}` })),
  ] : [];
  async function reload() {
    const seq = ++sequence.current, scope = context.current;
    const [rows, refs, groups, list] = await Promise.all([api<SheetSummaryV4[]>(path + '/sheets-s1'), api<ValidationSummaryV4[]>('/validation-data-s1'), api<CohortSummaryV4[]>('/comparisons-s1/cohorts'), api<ExportViewV4[]>('/exports-s1')]);
    if (!alive.current || seq !== sequence.current || scope !== context.current) return;
    setSheets(rows); setReferences(refs); setCohorts(groups); setHistory(list); setUnavailable(false);
    if (own) {
      const value = await api<SheetViewV4>(`/score-sheets-s1/${own.summary.sheet_id}`);
      if (!alive.current || seq !== sequence.current || scope !== context.current) return;
      setOwn(value);
    }
  }
  useEffect(() => { alive.current = true; void reload().catch(e => { if (alive.current) { setError(message(e)); setUnavailable(accessLost(e)); } }); return () => { alive.current = false; sequence.current++; }; }, [path, user.username]);
  async function work(action: () => Promise<void>) {
    if (pending.current) return; pending.current = true; setBusy(true); setError(''); const scope = context.current;
    try { await action(); } catch (e) { if (alive.current && scope === context.current) { setError(message(e)); if (accessLost(e)) { setOwn(null); setSource(null); setBasic(null); setFinal(null); setCreated(null); setUnavailable(true); } } }
    finally { pending.current = false; if (alive.current && scope === context.current) setBusy(false); }
  }
  async function selectOwner(sheetId: string) {
    setOwn(null); setSource(null); setBasic(null); setFinal(null); setReport(''); setBasics([]); setFinals([]); setReports([]);
    if (!sheetId) return;
    const seq = ++sequence.current, scope = context.current;
    const [value, results, documents, runs] = await Promise.all([api<SheetViewV4>(`/score-sheets-s1/${sheetId}`), api<BasicSummaryV4[]>(path + `/final-results-s1/candidates?viewer_sheet_id=${sheetId}`), api<FinalSummaryV4[]>(path + `/final-results-s1?viewer_sheet_id=${sheetId}`), api<ReportRunV4[]>(path + '/report-runs-s1')]);
    if (!alive.current || seq !== sequence.current || scope !== context.current) return;
    setOwn(value); setBasics(results); setFinals(documents); setReports(runs);
  }
  async function selectFinal(id: string) {
    setFinal(null); setReport(''); if (!id || !source || !own) return;
    const seq = ++sequence.current, scope = context.current;
    const value = await api<FinalViewV4>(path + `/final-results-s1/${id}?viewer_sheet_id=${own.summary.sheet_id}`);
    if (!alive.current || seq !== sequence.current || scope !== context.current) return;
    if (!same(value.document.basic_document.input, source.reference)) throw new Error('이 최종본은 선택한 원자료 판본과 다릅니다. 원자료 선택을 확인하세요.');
    setFinal(value.reference); setBasic(value.document.basic);
  }
  function add() {
    if (!source || !own) return;
    if (members.some(row => same(row.value.sheet, source.reference))) { setError('이 원자료 판본을 이미 선택했습니다. 목록에서 제거한 뒤 다시 선택하세요.'); return; }
    setMembers([...members, { label: `${own.document.rater_name} · ${source.label}`, value: { case_id: item.case_id, session_id: item.selected_session_id, sheet: source.reference, viewer_sheet_id: source.viewer ?? (final ? own.summary.sheet_id : null), basic, final, report_run_id: report || null } }]);
    setSource(null); setBasic(null); setFinal(null); setReport(''); setError('');
  }
  async function create() {
    if (!members.length || !reason.trim()) throw new Error('내보낼 원자료와 생성 사유를 선택하세요.');
    const body = { format, members: members.map(row => row.value), references: selectedReferences.map(row => row.reference), comparison: cohort?.reference ?? null, redact_terms: redact.split('\n').map(value => value.trim()).filter(Boolean), reason: reason.trim() };
    const key = JSON.stringify(body); if (request.current.key !== key) request.current = { key, id: crypto.randomUUID() };
    const scope = context.current, value = await api<ExportViewV4>('/exports-s1', 'POST', { ...body, request_id: request.current.id });
    if (!alive.current || scope !== context.current) return;
    setCreated(value); setMembers([]); await reload();
  }
  async function download(row: ExportViewV4) {
    const scope = context.current;
    const response = await fetch(`/api/exports-s1/${row.export_id}/download`, { credentials: 'same-origin', headers: { 'X-KDOG-Request': '1' } });
    if (!response.ok) { if (response.status === 401) window.dispatchEvent(new Event('kdog-session-expired')); const detail = await response.json().catch(() => ({ detail: '다운로드에 실패했습니다.' })); throw new ApiError(typeof detail.detail === 'string' ? detail.detail : '다운로드에 실패했습니다.', response.status); }
    const blob = await response.blob(); if (!alive.current || scope !== context.current) return;
    const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = `kdog-s1-research-${row.export_id}.${row.format === 'xlsx' ? 'xlsx' : 'zip'}`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  const missingReference = selectedReferences.some(row => !references.some(current => current.reference.hash === row.reference.hash));
  const missingCohort = cohort && !cohorts.some(row => row.reference.hash === cohort.reference.hash);
  if (unavailable) return <section className="panel" aria-label="S1 연구 내보내기"><h2>연구 내보내기</h2><p role="alert">{error}</p></section>;
  return <section className="panel" aria-label="S1 연구 내보내기" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>S1 연구 내보내기</h2><p>대상·회차·평가자·항목/창의 원자료, 자동 계산, 판정, 완료 의견과 최종 출력은 별도 표로 저장합니다. 숫자 0·음수·횟수와 결측(null)을 구분합니다. 직접 식별정보와 키는 제외하며, 유효하지 않은 비교 쌍은 사유와 함께 제외합니다.</p>
    <p className="fine">같은 촬영의 여러 카메라는 표본 수를 늘리지 않습니다. 범주·횟수·유형을 하나의 정확도로 합치지 않습니다. 아래 선택은 새 S1 판본만 사용합니다. 접수의 동의 확인과 분석·피드백 동의를 모두 확인한 자료만 연구 파일에 포함됩니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <fieldset disabled={busy}><legend>원자료 판본 고정</legend><button onClick={() => void work(reload)}>내보내기 후보 새로고침</button>
      <label>기준 본인 시트<select aria-label="기준 본인 시트" value={own?.summary.sheet_id ?? ''} onChange={event => void work(() => selectOwner(event.target.value))}><option value="">내 시트를 선택하세요</option>{sheets.filter(row => row.own && row.active).map(row => <option key={row.sheet_id} value={row.sheet_id}>{row.rater_name} · {row.state === 'submitted' ? '제출' : '초안'} · r{row.revision}</option>)}</select></label>
      {own && <><label>내보낼 원자료 판본<select aria-label="내보낼 원자료 판본" value={source?.reference.ref ?? ''} onChange={event => { setSource(currentSources.find(row => row.reference.ref === event.target.value) ?? null); setBasic(null); setFinal(null); setReport(''); }}><option value="">정확한 원본을 선택하세요</option>{currentSources.map(row => <option key={row.reference.ref} value={row.reference.ref}>{row.label}</option>)}</select></label><p className="fine">타인·AI 시트는 독립 채점 화면에서 명시 공개한 뒤 선택합니다. 공개 배정만 받은 미열람 자료는 표시하지 않습니다.</p></>}
      {source && <><p>원자료 {source.reference.sheet_id} · r{source.reference.revision}<br />SHA-256: {source.reference.hash}</p>
        <label>같은 원자료의 기본 결과<select aria-label="같은 원자료의 기본 결과" value={basic ? `${basic.result_id}:${basic.revision}` : ''} onChange={event => { const row = basics.find(value => `${value.result_id}:${value.revision}` === event.target.value); setBasic(row ? { result_id: row.result_id, revision: row.revision, ref: row.manifest_ref, hash: row.manifest_hash } : null); setFinal(null); setReport(''); }}><option value="">기본 결과 포함 안 함</option>{basics.filter(row => same(row.input, source.reference)).map(row => <option key={`${row.result_id}:${row.revision}`} value={`${row.result_id}:${row.revision}`}>계산 r{row.revision} · {row.result_id.slice(0, 8)}</option>)}{basic && !basics.some(row => row.result_id === basic.result_id && row.revision === basic.revision) && <option value={`${basic.result_id}:${basic.revision}`}>최종본에 고정된 계산 r{basic.revision}</option>}</select></label>
        <label>최종 결과<select aria-label="최종 결과" value={final?.final_id ?? ''} onChange={event => void work(() => selectFinal(event.target.value))}><option value="">최종 결과 포함 안 함</option>{finals.map(row => <option key={row.reference.final_id} value={row.reference.final_id}>{row.recorded_at} · {row.actor} · {row.reference.final_id.slice(0, 8)}{row.requires_reveal ? ' · 명시 해석 공개 필요' : ''}</option>)}</select></label><p className="fine">다른 작성자의 최종본은 행사 의견 화면에서 명시 해석 공개를 먼저 기록하세요. 선택 시 원자료가 같은지 다시 확인합니다.</p>
        {final && <label>같은 최종본의 발급 리포트<select aria-label="같은 최종본의 발급 리포트" value={report} onChange={event => setReport(event.target.value)}><option value="">리포트 포함 안 함</option>{reports.filter(row => row.normal_publish_available && row.final.hash === final.hash && row.final.ref === final.ref).map(row => <option key={row.run_id} value={row.run_id}>{row.is_latest_issued ? '최근 발급' : '이전 발급'} · {row.run_id.slice(0, 8)}{row.outdated ? ' · 이전 입력' : ''}</option>)}</select></label>}
        <button onClick={add}>고정 선택 목록에 추가</button>
      </>}
    </fieldset>
    <fieldset disabled={busy}><legend>내보낼 고정 선택 {members.length}개</legend>{members.map((row, index) => <div key={row.value.sheet.ref}><p>{row.label}<br />원자료 r{row.value.sheet.revision} · {row.value.sheet.hash}<br />기본 결과 {row.value.basic ? `r${row.value.basic.revision} · ${row.value.basic.hash}` : '미포함'}<br />최종본 {row.value.final?.hash ?? '미포함'} · 리포트 {row.value.report_run_id ?? '미포함'}</p><button onClick={() => setMembers(members.filter((_, i) => i !== index))}>선택 {index + 1} 제거</button></div>)}
      <label>연구 파일 형식<select aria-label="연구 파일 형식" value={format} onChange={event => setFormat(event.target.value as 'csv_zip' | 'xlsx')}><option value="csv_zip">CSV 묶음 ZIP</option><option value="xlsx">XLSX</option></select></label><label>추가 식별정보 제거 문구 (한 줄에 하나)<textarea value={redact} maxLength={10000} onChange={event => setRedact(event.target.value)} /></label><p className="fine">대상·보호자 이름, 참가자·행사 식별자와 평가자 계정은 자동 제거합니다. 자유서술에 포함된 다른 식별정보도 추가하세요.</p>
      {references.length > 0 && <fieldset><legend>검수 참고 출처 (현재 점수와 별도)</legend>{references.map(row => <label key={row.reference.validation_id} className="check"><input type="checkbox" checked={selectedReferences.some(selected => selected.reference.hash === row.reference.hash)} onChange={event => setSelectedReferences(event.target.checked ? [...selectedReferences, row] : selectedReferences.filter(selected => selected.reference.hash !== row.reference.hash))} />{row.filename} · {row.row_count}행 · G03 미확정</label>)}</fieldset>}
      {missingReference && <p role="alert">접근할 수 없는 참고 판본이 선택되어 있습니다. <button onClick={() => setSelectedReferences([])}>참고 선택 비우기</button></p>}
      <label>자체 집단 비교 출처<select aria-label="자체 집단 비교 출처" value={cohort?.reference.snapshot_id ?? ''} onChange={event => setCohort(cohorts.find(row => row.reference.snapshot_id === event.target.value) ?? null)}><option value="">비교 출처 포함 안 함</option>{cohorts.map(row => <option key={row.reference.snapshot_id} value={row.reference.snapshot_id}>{row.title}{row.outdated ? ' · 이전 응답 기준' : ''}</option>)}{missingCohort && <option value={cohort!.reference.snapshot_id}>접근할 수 없는 선택 판본</option>}</select></label>
      <label>연구 내보내기 사유<textarea value={reason} maxLength={4000} onChange={event => setReason(event.target.value)} /></label><button disabled={!members.length || !reason.trim() || missingReference || !!missingCohort} onClick={() => void work(create)}>선택 판본으로 연구 파일 생성</button>
      <p className="fine">새로고침은 고정 선택을 최신 판본으로 바꾸지 않습니다. 응답 유실 후 같은 선택으로 다시 생성하면 같은 요청을 확인합니다. 생성·다운로드 시 권한, 동의, 삭제와 파일 hash를 다시 검사합니다.</p>
    </fieldset>
    {created && <p role="status">연구 파일 준비 완료 · 포함 {created.member_count}개 · 제외 {created.excluded_count}개</p>}
    <section aria-label="내가 생성한 연구 파일"><h3>내가 생성한 연구 파일</h3>{history.length === 0 && <p>생성한 연구 파일이 없습니다.</p>}{history.map(row => <details key={row.export_id} open={row.export_id === created?.export_id}><summary>{row.created_at} · {row.format === 'xlsx' ? 'XLSX' : 'CSV ZIP'} · 포함 {row.member_count}개 / 제외 {row.excluded_count}개</summary><p>고정 자료 SHA-256: {row.snapshot_sha256}<br />파일 SHA-256: {row.output_sha256}</p><button disabled={busy} onClick={() => void work(() => download(row))}>연구 파일 다운로드 {row.export_id.slice(0, 8)}</button></details>)}</section>
  </section>;
}
