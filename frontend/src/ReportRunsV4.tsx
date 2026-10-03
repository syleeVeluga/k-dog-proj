import { useEffect, useRef, useState } from 'react';
import { accessLost, api, ApiError } from './api';
import type { Case, User } from './types';
import type { FinalSummaryV4 } from './finalTypesV4';
import type { SheetSummaryV4 } from './ScoringTypesV4';
import type { ReportPublicationV4, ReportRunV4 } from './reportTypesV4';
import type { CohortSummaryV4 } from './comparisonTypesV4';

const active = new Set(['queued', 'running', 'retry_wait']);
const states: Record<string, string> = { queued: '대기', running: '생성 중', retry_wait: '재시도 대기', succeeded: '발급 완료', failed: '실패·검토 필요', stopped: '중지', available: '관찰됨', partial: '일부 관찰', insufficient: '관찰 부족', held: '판단 보류' };
const stages: Record<string, string> = { content_v4: '내용 작성', validate_content_v4: '내용 검증', render_v4: 'HTML·PDF 생성', validate_output_v4: '출력 검증', publish_report_v4: '게시' };
const message = (value: unknown) => value instanceof Error ? value.message : '리포트 요청에 실패했습니다.';

export function ReportRunsV4({ item, user, comparisonRevision = 0 }: { item: Case; user: User; comparisonRevision?: number }) {
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const [rows, setRows] = useState<ReportRunV4[]>([]), [finals, setFinals] = useState<FinalSummaryV4[]>([]), [sheets, setSheets] = useState<SheetSummaryV4[]>([]);
  const [viewer, setViewer] = useState(''), [finalId, setFinalId] = useState(''), [reuse, setReuse] = useState(''), [reason, setReason] = useState('');
  const [cohorts, setCohorts] = useState<CohortSummaryV4[]>([]), [cohortId, setCohortId] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [opened, setOpened] = useState<ReportPublicationV4 | null>(null);
  const alive = useRef(true), sequence = useRef(0), working = useRef(false), timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const request = useRef<{ fingerprint: string; request_id: string } | null>(null), openedId = useRef(''), frame = useRef<HTMLIFrameElement>(null);
  const context = useRef(''); context.current = `${path}:${viewer}`;
  const query = viewer ? `?viewer_sheet_id=${encodeURIComponent(viewer)}` : '';
  const manager = ['operator', 'admin'].includes(user.role);
  const selected = finals.find(value => value.reference.final_id === finalId);
  const cohort = cohorts.find(value => value.reference.snapshot_id === cohortId);
  const own = sheets.filter(value => value.own && value.active && value.rater_kind === 'human' && value.state === 'submitted');
  const viewerRow = own.find(value => value.sheet_id === viewer);
  function clearOutput() { openedId.current = ''; setOpened(null); }
  function filePath(runId: string, format: string, inline = false) { return path + `/report-runs-s1/${runId}/files/${format}` + query + (inline ? `${query ? '&' : '?'}inline=true` : ''); }
  async function reload(clearError = false) {
    if (timer.current) clearTimeout(timer.current);
    const current = ++sequence.current, scope = context.current; setLoading(true);
    try {
      const [runs, list, assigned, comparisons] = await Promise.all([api<ReportRunV4[]>(path + '/report-runs-s1'), api<FinalSummaryV4[]>(path + '/final-results-s1' + query), api<SheetSummaryV4[]>(path + '/sheets-s1'), api<CohortSummaryV4[]>('/comparisons-s1/cohorts')]);
      if (!alive.current || current !== sequence.current || scope !== context.current) return;
      setRows(runs); setFinals(list); setSheets(assigned); setCohorts(comparisons); if (clearError) setError('');
      if (openedId.current) {
        const id = openedId.current;
        const output = await api<ReportPublicationV4>(filePath(id, 'manifest'));
        if (alive.current && current === sequence.current && scope === context.current && openedId.current === id) setOpened(output);
      }
      if (runs.some(value => active.has(value.status))) timer.current = setTimeout(() => { void reload(); }, 2000);
    } catch (value) {
      if (alive.current && current === sequence.current && scope === context.current) { setError(message(value)); clearOutput(); if (accessLost(value)) { setRows([]); setFinals([]); setSheets([]); setCohorts([]); } }
    } finally { if (alive.current && current === sequence.current && scope === context.current) setLoading(false); }
  }
  useEffect(() => {
    alive.current = true; clearOutput(); void reload();
    const visible = () => { if (document.visibilityState === 'visible' && !working.current) void reload(); };
    document.addEventListener('visibilitychange', visible);
    return () => { alive.current = false; sequence.current++; if (timer.current) clearTimeout(timer.current); document.removeEventListener('visibilitychange', visible); };
  }, [path, viewer, item.input_revision, comparisonRevision]);
  async function work(operation: () => Promise<void>) {
    if (working.current) return;
    working.current = true; setBusy(true); setError(''); const scope = context.current;
    try { await operation(); if (alive.current && scope === context.current) await reload(true); }
    catch (value) { if (alive.current && scope === context.current) { setError(message(value)); if (accessLost(value)) clearOutput(); } }
    finally { working.current = false; if (alive.current && scope === context.current) setBusy(false); }
  }
  async function start() {
    if (!selected || selected.requires_reveal || item.consents.analysis_feedback !== 'confirmed' || cohortId && !cohort) return;
    const fields = { expected_revision: item.input_revision, final: selected.reference, viewer_sheet_id: viewer || null, reuse_run_id: reuse || null, comparison: cohort?.reference ?? null };
    const fingerprint = JSON.stringify(fields);
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, request_id: crypto.randomUUID() };
    await api(path + '/report-runs-s1', 'POST', { ...fields, request_id: request.current.request_id }); request.current = null;
  }
  async function reveal() {
    if (!selected || !viewerRow || !reason.trim()) return;
    await api(path + `/final-results-s1/${selected.reference.final_id}/reveal`, 'POST', { viewer_sheet_id: viewerRow.sheet_id, expected_viewer_revision: viewerRow.revision, reason: reason.trim(), target: { kind: 'final', document_id: selected.reference.final_id, revision: null, ref: selected.reference.ref, hash: selected.reference.hash } });
  }
  async function openOutput(row: ReportRunV4) {
    clearOutput(); const scope = context.current;
    const value = await api<ReportPublicationV4>(filePath(row.run_id, 'manifest'));
    if (alive.current && scope === context.current) { openedId.current = row.run_id; setOpened(value); }
  }
  async function print() {
    const id = openedId.current, scope = context.current; if (!id) return;
    await api<ReportPublicationV4>(filePath(id, 'manifest'));
    if (alive.current && scope === context.current && openedId.current === id) { frame.current?.contentWindow?.focus(); frame.current?.contentWindow?.print(); }
  }
  async function download(format: 'html' | 'pdf' | 'manifest') {
    const id = openedId.current, scope = context.current; if (!id) return;
    const response = await fetch('/api' + filePath(id, format), { credentials: 'same-origin', headers: { 'X-KDOG-Request': '1' } });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: '리포트 파일을 저장하지 못했습니다.' }));
      if (response.status === 401) window.dispatchEvent(new Event('kdog-session-expired'));
      throw new ApiError(typeof error.detail === 'string' ? error.detail : '리포트 파일을 저장하지 못했습니다.', response.status);
    }
    const blob = await response.blob();
    if (!alive.current || scope !== context.current || openedId.current !== id) return;
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = `kdog-s1-${id}.${format === 'manifest' ? 'json' : format}`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  if (!manager) return <p role="status">리포트 운영 권한이 필요합니다.</p>;
  return <section aria-label="S1 리포트 실행" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h3>고정 최종본으로 리포트 생성</h3>
    <p>확인된 프로그램 근거로 정상 발급합니다. 일부 관찰 부족은 사유를 표시하며, 문장은행 G02와 실제 AI 문장 측정 S16은 별도 확인 대기입니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <button disabled={busy || loading} onClick={() => void reload(true)}>리포트 상태 새로고침</button>
    <fieldset disabled={busy || loading}><legend>원본 선택과 명시 실행</legend>
      <label>리포트 공개 맥락의 본인 제출 시트<select aria-label="리포트 공개 맥락의 본인 제출 시트" value={viewer} onChange={event => { clearOutput(); setViewer(event.target.value); setReuse(''); }}><option value="">본인 원자료·해석만 사용</option>{own.map(value => <option key={value.sheet_id} value={value.sheet_id}>{value.rater_name} · r{value.revision} · {value.purpose === 'independent' ? '독립' : '공개 후 검수'}</option>)}</select></label>
      <label>리포트에 고정할 최종본<select aria-label="리포트에 고정할 최종본" value={finalId} onChange={event => { setFinalId(event.target.value); setReuse(''); }}><option value="">최종본을 선택하세요</option>{finals.map(value => <option key={value.reference.final_id} value={value.reference.final_id}>{new Date(value.recorded_at).toLocaleString()} · {value.actor} · 기본 r{value.basic.revision}{value.requires_reveal ? ' · 해석 공개 필요' : ''}</option>)}</select></label>
      {selected && <p className="fine">최종본 {selected.reference.final_id}<br />SHA-256 {selected.reference.hash}</p>}
      <label>리포트 자체 비교집단<select aria-label="리포트 자체 비교집단" value={cohortId} onChange={event => { setCohortId(event.target.value); setReuse(''); }}><option value="">비교 없이 생성</option>{cohorts.map(value => <option key={value.reference.snapshot_id} value={value.reference.snapshot_id}>{value.title} · 선택 {value.selection_count}대상{value.outdated ? ' · 이전 응답 기준' : ''}</option>)}</select></label>
      {cohort && <p className="fine">명시한 자체 집단 {cohort.reference.snapshot_id} · {cohort.reference.hash}{cohort.outdated && ' · 일부 응답이 이후 변경됐으며 이 고정 집단의 당시 평균을 사용합니다.'}</p>}
      {!!cohortId && !cohort && <p role="status">선택한 집단을 현재 사용할 수 없습니다. 다른 집단 또는 비교 없음을 명시적으로 선택하세요.</p>}
      {!finals.length && <p>독립 채점 메뉴에서 고정 기본 결과를 선택하고 최종본을 먼저 만드세요.</p>}
      <label>공개·실행 제어 사유<input aria-label="공개·실행 제어 사유" value={reason} onChange={event => setReason(event.target.value)} maxLength={2000} /></label>
      {selected?.requires_reveal && <><p>다른 작성자의 해석은 명시 공개가 필요합니다. 먼저 독립 채점 메뉴에서 원자료를 공개하고 같은 입력의 본인 제출 시트를 선택하세요. 해석 열람 후 새 기록은 검수로 구분됩니다.</p><button disabled={!viewerRow || !reason.trim()} onClick={() => void work(reveal)}>선택한 최종 해석을 명시 공개</button></>}
      <label>검증된 내용 명시 재사용<select aria-label="검증된 내용 명시 재사용" value={reuse} onChange={event => setReuse(event.target.value)}><option value="">재사용 없이 새 생성</option>{rows.filter(value => value.final.hash === selected?.reference.hash && value.steps.some(step => step.stage === 'content_v4' && step.status === 'succeeded')).map(value => <option key={value.run_id} value={value.run_id}>{value.run_id.slice(0, 8)} · {states[value.status] ?? value.status}</option>)}</select></label>
      <p className="fine">재사용은 고정 최종본·설문·내용 규칙·템플릿 해시를 다시 검증하며, 발급 파일은 새 실행에 보존합니다.</p>
      <button disabled={!selected || selected.requires_reveal || item.consents.analysis_feedback !== 'confirmed' || !!cohortId && !cohort} onClick={() => void work(start)}>선택한 최종본으로 리포트 생성</button>
      {request.current && <p role="status">응답 확인이 필요한 요청입니다. 동일 입력의 재요청은 같은 요청 ID를 사용합니다.</p>}
    </fieldset>
    <p className="fine">생성 중 상태만 2초마다 갱신합니다. 이 실행은 프로그램 처리이며 공급자 호출·공급자 비용은 0입니다.</p>
    {!rows.length && <p>생성된 리포트 실행이 없습니다.</p>}
    {rows.map(row => <article className="panel" key={row.run_id} aria-label={`리포트 실행 ${row.run_id}`}><h3>{states[row.status] ?? row.status}{row.is_latest_issued ? ' · 최신 발급본' : row.publication_state === 'issued' ? ' · 이전 발급본' : ''}{row.outdated && ' · 이전 입력·기준'}</h3>
      <p>{row.run_id} · 입력 {row.input_revision}판 · {new Date(row.updated_at).toLocaleString()}</p>
      <p className="fine">고정 최종본 {row.final.final_id} · {row.final.hash}</p>
      {row.failure_code && <p role="status">실행 사유: {row.failure_code}</p>}
      {row.pending_reasons.includes('G02') && <p className="fine">문장은행 G02 확인 대기. 검증된 프로그램 설명의 정상 발급을 막지 않습니다.</p>}
      <div className="toolbar">{active.has(row.status) && <button disabled={busy || !reason.trim()} onClick={() => void work(async () => { await api(`/report-runs-s1/${row.run_id}/stop`, 'POST', { expected_updated_at: row.updated_at, reason: reason.trim() }); })}>이 리포트 실행 중지</button>}
        {['failed', 'stopped'].includes(row.status) && <button disabled={busy || !reason.trim()} onClick={() => void work(async () => { await api(`/report-runs-s1/${row.run_id}/retry`, 'POST', { expected_updated_at: row.updated_at, reason: reason.trim() }); })}>고정 입력으로 리포트 재시도</button>}
        {row.normal_publish_available && <button disabled={busy} onClick={() => void work(() => openOutput(row))}>발급 요약·HTML·PDF 열기</button>}</div>
      <details><summary>단계·시도·시간·재사용</summary><div className="table-wrap"><table><thead><tr><th>단계</th><th>시도·상태</th><th>시간·호출</th></tr></thead><tbody>{row.steps.map((step, index) => <tr key={index}><td>{stages[step.stage] ?? step.stage}</td><td>{step.attempt}차 · {states[step.status] ?? step.status}{step.reused && <p>명시 재사용</p>}{step.code && <p>{step.code}</p>}</td><td>{Object.entries(step.timing).map(([name, value]) => <p key={name}>{name}: {value.toFixed(2)}초</p>)}{!Object.keys(step.timing).length && '시간 미측정'}<p>공급자 호출 {step.provider_calls}회</p></td></tr>)}</tbody></table></div></details>
    </article>)}
    {opened && <section className="panel" aria-label="권한 확인된 리포트 발급본"><div className="section-title"><h3>{opened.header.dog_name} · 발급 결과</h3><button onClick={clearOutput}>발급본 닫기</button></div>
      <p>{new Date(opened.created_at).toLocaleString()} · 입력 {opened.input_revision}판 · {rows.find(value => value.run_id === opened.run_id)?.outdated ? '이전 입력·기준' : '고정 입력'} · {opened.run_id}</p>
      <div className="form-grid" aria-label="리포트 네 결과 요약">{opened.profile.cards.map(card => <article className="panel" key={card.key}><h4>{card.title}</h4><p>{card.label ?? states[card.status]}</p>{card.claims.map(claim => <p key={claim.claim_id}>{claim.text}</p>)}</article>)}</div>
      {opened.cohort && <section aria-label="발급 당시 자체 집단"><h4>{opened.cohort.title} · 선택 {opened.cohort.selection_count}대상</h4><p>{opened.cohort.interpretation_note}</p><p>{opened.cohort.selection_note}</p><div className="table-wrap"><table><thead><tr><th>영역·원척도</th><th>평균·유효 n</th><th>제외</th></tr></thead><tbody>{opened.cohort.domains.map(domain => <tr key={domain.domain}><td>{domain.domain} · {domain.scale_minimum}~{domain.scale_maximum}</td><td>{domain.mean === null ? '평균 없음' : domain.mean.toLocaleString(undefined, { maximumFractionDigits: 3 })} · n={domain.n}</td><td>{domain.excluded_count}개{Object.entries(domain.exclusion_reasons).map(([why, count]) => <p key={why}>{why}: {count}</p>)}</td></tr>)}</tbody></table></div><p className="fine">비교 출처 {opened.cohort.reference.hash}</p></section>}
      {Object.entries(opened.output.image_issues).map(([scene, note]) => <p key={scene}>장면 {scene}: {note}</p>)}
      <div className="toolbar"><button disabled={busy} onClick={() => void work(() => download('html'))}>HTML 저장</button><button disabled={busy} onClick={() => void work(() => download('pdf'))}>PDF 저장</button><button disabled={busy} onClick={() => void work(() => download('manifest'))}>출처 manifest 저장</button><a href={'/api' + filePath(opened.run_id, 'html', true)} target="_blank" rel="noopener noreferrer">HTML 새 창</a><button disabled={busy} onClick={() => void work(print)}>열린 리포트 인쇄</button></div>
      <p className="fine">다운로드·인쇄 시 동의와 공개 권한을 다시 확인합니다. 외부로 자동 발송하지 않습니다.</p>
      <iframe ref={frame} title="S1 관찰 리포트 미리보기" src={'/api' + filePath(opened.run_id, 'html', true)} sandbox="allow-same-origin allow-modals" style={{ width: '100%', height: 'min(80vh, 950px)', border: '1px solid #ccd8d2' }} />
      <details><summary>불변 출력 출처</summary><p>입력 {opened.input_hash}</p><p>설정 {opened.config_hash}</p><p>최종본 {opened.final.hash}</p><p>HTML {opened.output.html.hash}</p><p>PDF {opened.output.pdf.hash}</p></details>
    </section>}
  </section>;
}
