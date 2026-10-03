import { useEffect, useRef, useState } from 'react';
import { api, accessLost } from './api';
import type { Case } from './types';
import type { PreprocessStatusV4 } from './preprocessTypesV4';
import type { AiBasicResultV4, AiReadinessV4, AiRunV4 } from './aiTypesV4';

const states: Record<string, string> = { queued: '대기', running: '실행 중', retry_wait: '재시도 대기', succeeded: '성공', partial: '부분 완료', failed: '실패', stopped: '중지', settings_required: '설정 확인 필요', complete: '완료', held: '판정보류', draft: '초안', calculated: '계산됨', missing: '근거 부족', policy_pending: '규칙 확인 대기', invalid: '조건 무효', condition_unknown: '조건 확인 필요' };
const stages: Record<string, string> = { score_v4: '관찰 원자료', calculate_v4: '앱 계산', publish_v4: '게시' };
const timers: Record<string, string> = { upload_seconds: '업로드', processing_seconds: '공급자 처리 대기', inference_seconds: '추론', repair_seconds: '스키마 수리', cleanup_seconds: '원격 파일 정리', calculation_seconds: '계산', publish_seconds: '게시', stage_seconds: '전체 단계' };
const active = new Set(['queued', 'running', 'retry_wait']);
const number = (value: number | null) => value === null ? '미확인' : Number(value.toFixed(3)).toLocaleString();
const valueText = (value: number | string | null) => value === null ? '—' : typeof value === 'number' ? number(value) : value;

export function AiRunsV4({ item, manager }: { item: Case; manager: boolean }) {
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const [runs, setRuns] = useState<AiRunV4[]>([]), [ready, setReady] = useState<AiReadinessV4 | null>(null);
  const [preprocess, setPreprocess] = useState<PreprocessStatusV4 | null>(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [reuse, setReuse] = useState(''), [reason, setReason] = useState('');
  const alive = useRef(true), sequence = useRef(0), timer = useRef<ReturnType<typeof setTimeout> | null>(null), working = useRef(false);
  const request = useRef<{ fingerprint: string; request_id: string } | null>(null);
  async function reload(clearError = false) {
    if (timer.current) clearTimeout(timer.current);
    const current = ++sequence.current; setLoading(true);
    try {
      const [list, config, media] = await Promise.all([api<AiRunV4[]>(path + '/runs-s1'), api<AiReadinessV4>('/scoring-ai-s1/readiness'), api<PreprocessStatusV4>(path + '/preprocess-s1')]);
      if (alive.current && current === sequence.current) {
        setRuns(list); setReady(config); setPreprocess(media); if (clearError) setError('');
        if (list.some(run => active.has(run.status))) timer.current = setTimeout(() => { void reload(); }, 2000);
      }
    } catch (value) {
      if (alive.current && current === sequence.current) { setReady(null); setPreprocess(null); if (accessLost(value)) setRuns([]); setError(value instanceof Error ? value.message : 'S1 실행 상태 조회에 실패했습니다.'); }
    } finally { if (alive.current && current === sequence.current) setLoading(false); }
  }
  useEffect(() => {
    alive.current = true; void reload();
    return () => { alive.current = false; sequence.current++; if (timer.current) clearTimeout(timer.current); };
  }, [path, item.input_revision]);
  async function work(operation: () => Promise<unknown>) {
    if (working.current) return;
    working.current = true; setBusy(true); setError('');
    try { await operation(); if (alive.current) await reload(true); }
    catch (value) { if (alive.current) { setError(value instanceof Error ? value.message : 'S1 실행 요청에 실패했습니다.'); if (accessLost(value)) { setRuns([]); setReady(null); setPreprocess(null); } } }
    finally { working.current = false; if (alive.current) setBusy(false); }
  }
  const allowed = ready?.enabled && preprocess?.result_pointer && ['complete', 'partial'].includes(preprocess.status) && !preprocess.outdated
    && preprocess.input_revision === item.input_revision && item.consents.analysis_feedback === 'confirmed';
  async function start() {
    if (!allowed || !preprocess?.result_pointer || !ready) return;
    const fields = { expected_revision: item.input_revision, preprocess_ref: preprocess.result_pointer.ref, preprocess_hash: preprocess.result_pointer.hash,
      settings_version: ready.active_version, reuse_run_id: reuse || null };
    const fingerprint = JSON.stringify(fields);
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, request_id: crypto.randomUUID() };
    await api(path + '/runs-s1', 'POST', { ...fields, request_id: request.current.request_id });
    request.current = null;
  }
  return <section className="panel" aria-label="S1 AI 실행" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>S1 AI 관찰 원자료 실행</h2>
    <p>입력 {item.input_revision}판 · 활성 설정 {ready?.active_version === 'inactive' ? '없음' : ready?.active_version ?? '확인 중'} · 기본 예정 공급자 호출 {ready?.planned_provider_calls ?? '—'}회</p>
    <p>숫자 83개·관찰 메모 3개의 원자료를 요청하고 자동 4개는 앱이 계산합니다. D04 상세 유형 해석은 보류합니다.</p>
    <p className="fine">실제 공급자 정확도·시간·가격은 S16 측정 대기입니다. 메뉴 조회는 실행을 만들지 않으며, 실행 중 상태만 2초마다 갱신합니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <button disabled={busy || loading} onClick={() => { void reload(true); }}>S1 실행 상태 새로고침</button>
    {!ready?.enabled && <p role="status">개발자가 관찰 원자료 범위를 확인한 S1 설정을 활성화해야 합니다.</p>}
    {item.consents.analysis_feedback !== 'confirmed' && <p role="status">분석·피드백 동의를 확인해야 실행할 수 있습니다.</p>}
    {(!preprocess?.result_pointer || preprocess.outdated) && <p role="status">현재 입력 기준의 전처리 결과가 필요합니다.</p>}
    {preprocess?.status === 'partial' && <p>전처리가 일부만 완성되었습니다. 없는 카메라·클립의 항목은 관찰 부족 사유를 유지합니다.</p>}
    {manager && <fieldset disabled={busy || loading}><legend>명시 실행과 재사용</legend>
      <label>성공 항목군 재사용<select aria-label="성공 항목군 재사용" value={reuse} onChange={event => setReuse(event.target.value)}><option value="">재사용 없이 새 실행</option>{runs.filter(run => !run.outdated && run.steps.some(step => step.stage === 'score_v4' && step.status === 'succeeded')).map(run => <option key={run.run_id} value={run.run_id}>{run.run_id.slice(0, 8)} · {states[run.status] ?? run.status} · 성공 항목군 {run.steps.filter(step => step.stage === 'score_v4' && step.status === 'succeeded').length}개</option>)}</select></label>
      <p className="fine">재사용은 같은 원본·창·카메라·오프셋·모델·설정 해시를 다시 검증합니다. 부분 완료의 재생성도 새 실행으로 기록합니다.</p>
      <button disabled={!allowed} onClick={() => void work(start)}>현재 입력으로 S1 AI 실행 생성</button>
      {request.current && <p role="status">응답 확인이 필요한 요청입니다. 같은 입력으로 다시 누르면 동일 요청 ID를 사용합니다.</p>}
      <label>실행 제어 사유<input value={reason} onChange={event => setReason(event.target.value)} maxLength={2000} placeholder="중지 또는 재시도 이유" /></label>
    </fieldset>}
    {!runs.length && <p>생성된 S1 AI 실행이 없습니다.</p>}
    {runs.map(run => <article className="panel" key={run.run_id} aria-label={`S1 실행 ${run.run_id}`}>
      <h3>{states[run.status] ?? run.status}{run.outdated ? ' · 이전 입력 기준' : ''}</h3>
      <p>{run.run_id} · 입력 {run.input_revision}판 · {new Date(run.updated_at).toLocaleString()}</p>
      <p>기본 계획 {run.planned_provider_calls}회 · 예약 {run.reserved_calls}회 / 상한 {run.max_ai_calls}회 · D04 상세 해석 보류</p>
      {run.failure_code && <p role="status">실행 사유: {run.failure_code}</p>}
      {run.steps.some(step => step.billing_uncertain) && <p className="warning">응답 또는 정산이 확인되지 않은 예약 호출이 있습니다. 과금 여부 미확인 상태를 유지합니다.</p>}
      {run.result_available && <p>원자료와 기본 계산이 게시되었습니다. 독립 제출 뒤 명시 공개된 시트를 열 때 AI 열람 이력이 기록됩니다. 실행 상태에는 점수·판정을 표시하지 않습니다.</p>}
      {manager && <div className="toolbar">{active.has(run.status) && <button disabled={busy || !reason.trim()} onClick={() => void work(() => api(`/runs-s1/${run.run_id}/stop`, 'POST', { expected_updated_at: run.updated_at, reason: reason.trim() }))}>이 S1 실행 중지</button>}
        {['failed', 'stopped', 'settings_required'].includes(run.status) && <button disabled={busy || !reason.trim() || run.outdated} onClick={() => void work(() => api(`/runs-s1/${run.run_id}/retry`, 'POST', { expected_updated_at: run.updated_at, reason: reason.trim() }))}>고정 입력으로 S1 재시도</button>}</div>}
      <details><summary>단계별 시간·호출·부분 실패</summary><p className="fine">시간은 기록된 단계 값입니다. 수리와 전체 단계는 다른 시간 항목과 겹칠 수 있으므로 합산하지 않습니다. 빈 계량은 0으로 추정하지 않습니다.</p>
        <div className="table-wrap"><table><thead><tr><th>단계·항목군</th><th>시도·상태</th><th>시간</th><th>호출·계량</th></tr></thead><tbody>{run.steps.map((step, index) => <tr key={`${step.stage}:${step.key}:${step.attempt}:${index}`}>
          <td>{stages[step.stage] ?? step.stage}<br />{step.key}</td><td>{step.attempt}차 · {states[step.status] ?? step.status}{step.code && <p>{step.code}</p>}{step.reused && <p>명시 재사용</p>}</td>
          <td>{Object.keys(step.timing).length ? Object.entries(step.timing).map(([key, value]) => <p key={key}>{timers[key] ?? key}: {number(value)}초</p>) : '시간 미측정'}</td>
          <td>{step.call_reserved ? '호출 예약 있음' : '호출 예약 없음'}{step.billing_uncertain && <p>과금 여부 미확인</p>}{step.remote_cleanup_pending && <p>공급자 임시 파일 정리 미완료</p>}<p>입력 {number(step.input_tokens)} / 출력 {number(step.output_tokens)} / 합계 {number(step.total_tokens)} 토큰</p><p>비용 {step.cost_usd === null ? '미확인' : `$${step.cost_usd}`}</p>{Object.entries(step.token_meters).map(([key, value]) => <p key={key}>{key}: {value.toLocaleString()}</p>)}</td>
        </tr>)}</tbody></table></div>
      </details>
    </article>)}
  </section>;
}

export function AiRevealedResultsV4({ results }: { results: AiBasicResultV4[] }) {
  return <section className="panel" aria-label="공개한 S1 AI 기본 결과" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h3>명시 공개한 AI 기본 결과 · 읽기 전용</h3><p>AI 열람 이력이 기록된 결과입니다. 독립 사람 원자료와 자동 계산은 보존되며, D04 상세 유형 해석은 계속 보류합니다.</p>
    {!results.length && <p>공개한 원자료와 일치하는 기본 결과가 없습니다.</p>}
    {results.map(result => <article key={result.result_id}>
      <h4>AI 결과 {result.revision}판 · 원자료 {result.input.revision}판</h4><p>계산 판본 {result.rule_version} · 작성 {new Date(result.recorded_at).toLocaleString()}</p>
      {result.decisions.map(decision => { const automatic = result.automatic_decisions.find(value => value.key === decision.key); return <section key={decision.key}>
        <h4>{decision.key === 'owner_type' ? '보호자 교육태도' : '반려견·보호자 관계'} · {decision.label ?? '판정보류'}</h4><p>{states[decision.status] ?? decision.status} · {decision.reason}</p>
        <p>자동 판정: {automatic?.label ?? '판정보류'} · {automatic?.reason}</p><p>사용 항목: {decision.evidence_codes.join(', ') || '없음'} · 반대 근거 항목: {decision.counter_codes.join(', ') || '없음'}</p>
        {[['지지 근거', decision.evidence], ['반대 근거', decision.counter_evidence]].map(([name, values]) => <div key={String(name)}><h5>{String(name)}</h5>{(values as typeof decision.evidence).map((evidence, index) => <p key={index}>{evidence.camera_id} · {evidence.window_id} · {evidence.start_seconds}~{evidence.end_seconds}초 · 실제 확인 {evidence.observed_seconds}초 · {evidence.note}</p>)}</div>)}
        {decision.counter_note && <p>반대 근거 검토: {decision.counter_note}</p>}
      </section>; })}
      <h4>고정 원자료의 계산</h4>{result.calculations.metrics.map(metric => <details key={metric.key}><summary>{metric.key}: {valueText(metric.value)} · {states[metric.status] ?? metric.status}{metric.caution ? ' · 주의' : ''}{metric.internal_only ? ' · 내부 보조값' : ''}</summary>
        <p>{metric.reason}</p><p>분자 {valueText(metric.numerator)} / 분모 {valueText(metric.denominator)} · 사용 항목 {metric.used_codes.join(', ') || '없음'}</p>
        {metric.inputs.map(value => <p key={value.code}>{value.code}: {valueText(value.value)} · {value.status}{metric.excluded[value.code] && ` · 제외: ${metric.excluded[value.code]}`}</p>)}</details>)}
      <details><summary>고정 입력과 규칙 해시</summary><p>{result.input.ref}<br />SHA-256: {result.input.hash}<br />계산 규칙 SHA-256: {result.rule_hash}</p></details>
    </article>)}
  </section>;
}
