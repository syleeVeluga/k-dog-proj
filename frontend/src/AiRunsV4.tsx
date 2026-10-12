import { useEffect, useRef, useState } from 'react';
import { api, ApiError, accessLost } from './api';
import type { Case, User } from './types';
import type { PreprocessStatusV4 } from './preprocessTypesV4';
import type { AiBasicResultV4, AiReadinessV4, AiRunV4, AiStartV4 } from './aiTypesV4';

const states: Record<string, string> = { queued: '대기', running: '실행 중', retry_wait: '재시도 대기', succeeded: '성공', partial: '부분 완료', partial_failed: '부분 완료 · 실패 있음', failed: '실패', stopped: '중지', settings_required: '설정 확인 필요', complete: '완료', held: '판정보류', draft: '초안', calculated: '계산됨', missing: '근거 부족', policy_pending: '규칙 확인 대기', invalid: '조건 무효', condition_unknown: '조건 확인 필요' };
const stages: Record<string, string> = { score_v4: '항목군 관찰', calculate_v4: '기본 계산', attachment_v4: '애착 판단', publish_v4: '결과 게시' };
const timers: Record<string, string> = { upload_seconds: '업로드', processing_seconds: '공급자 처리 대기', inference_seconds: '추론', repair_seconds: '스키마 수리', cleanup_seconds: '원격 파일 정리', calculation_seconds: '계산', publish_seconds: '게시', stage_seconds: '전체 단계' };
const active = new Set(['queued', 'running', 'retry_wait']);
const number = (value: number | null) => value === null ? '미확인' : Number(value.toFixed(3)).toLocaleString();
const valueText = (value: number | string | null) => value === null ? '—' : typeof value === 'number' ? number(value) : value;

export function AiRunsV4({ item, user }: { item: Case; user: User }) {
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const storageKey = `kdog-ai:${user.username}:${item.case_id}:${item.selected_session_id}`;
  const saved = useRef<{ runId?: string; pending?: AiStartV4 }>({});
  const initialized = useRef(false);
  if (!initialized.current) { initialized.current = true; try { saved.current = JSON.parse(sessionStorage.getItem(storageKey) ?? '{}'); } catch { saved.current = {}; } }
  const [runs, setRuns] = useState<AiRunV4[]>([]), [ready, setReady] = useState<AiReadinessV4 | null>(null);
  const [preprocess, setPreprocess] = useState<PreprocessStatusV4 | null>(null), [error, setError] = useState('');
  const [requestError, setRequestError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState(saved.current.runId ?? ''), [pending, setPending] = useState<AiStartV4 | null>(saved.current.pending ?? null);
  const [verified, setVerified] = useState(false), [checked, setChecked] = useState(''), [control, setControl] = useState('');
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [reuse, setReuse] = useState(''), [reason, setReason] = useState('');
  const alive = useRef(true), sequence = useRef(0), generation = useRef(0), timer = useRef<ReturnType<typeof setTimeout> | null>(null), working = useRef(false), inFlight = useRef(false);
  const pendingRef = useRef(pending), selectedRef = useRef(selectedId);
  pendingRef.current = pending; selectedRef.current = selectedId;
  function preserve(request: AiStartV4 | null, id: string) { sessionStorage.setItem(storageKey, JSON.stringify({ pending: request ?? undefined, runId: id || undefined })); }
  function select(id: string) { selectedRef.current = id; setSelectedId(id); preserve(pendingRef.current, id); }
  function accepted(value: AiRunV4) {
    sequence.current++; inFlight.current = false;
    setRuns(list => [value, ...list.filter(run => run.run_id !== value.run_id)]);
    pendingRef.current = null; setPending(null); select(value.run_id); preserve(null, value.run_id);
  }
  async function reload(background = false) {
    if (!alive.current || background && inFlight.current) return;
    if (timer.current) clearTimeout(timer.current);
    const current = ++sequence.current; inFlight.current = true; if (!background) setLoading(true);
    let again = false;
    try {
      if (pendingRef.current) {
        const found = await api<{ found: boolean; run: AiRunV4 | null }>(`${path}/runs-s1/by-request/${pendingRef.current.request_id}`);
        if (!alive.current || current !== sequence.current) return;
        if (found.found && found.run) {
          setRequestError('');
          select(found.run.run_id); pendingRef.current = null; setPending(null); preserve(null, found.run.run_id);
          setRuns(list => [found.run!, ...list.filter(run => run.run_id !== found.run!.run_id)]);
        }
      }
      const [list, config, media] = await Promise.allSettled([api<AiRunV4[]>(path + '/runs-s1'), api<AiReadinessV4>('/scoring-ai-s1/readiness'), api<PreprocessStatusV4>(path + '/preprocess-s1')]);
      if (alive.current && current === sequence.current) {
        const failed = [list, config, media].find(value => value.status === 'rejected');
        if (failed?.status === 'rejected' && accessLost(failed.reason)) { setRuns([]); setReady(null); setPreprocess(null); sessionStorage.removeItem(storageKey); throw failed.reason; }
        if (list.status === 'fulfilled') {
          setRuns(list.value); setLoaded(true); setChecked(new Date().toLocaleTimeString());
          if (!selectedRef.current && !pendingRef.current) { const own = list.value.find(run => run.requested_by === user.username); if (own) select(own.run_id); }
          again = list.value.some(run => active.has(run.status));
        }
        if (config.status === 'fulfilled') setReady(config.value);
        if (media.status === 'fulfilled') setPreprocess(media.value);
        setVerified(!failed); setError(failed?.status === 'rejected' ? failed.reason instanceof Error ? failed.reason.message : 'AI 상태 조회에 실패했습니다.' : '');
        again = again || !!failed || !!pendingRef.current;
      }
    } catch (value) {
      if (alive.current && current === sequence.current) { setVerified(false); if (accessLost(value)) { setRuns([]); setReady(null); setPreprocess(null); setPending(null); setSelectedId(''); pendingRef.current = null; selectedRef.current = ''; sessionStorage.removeItem(storageKey); } else again = true; setError(value instanceof Error ? value.message : 'AI 실행 상태 조회에 실패했습니다.'); }
    } finally {
      if (alive.current && current === sequence.current) {
        setLoading(false); inFlight.current = false; if (timer.current) clearTimeout(timer.current);
        if (again) timer.current = setTimeout(() => { void reload(true); }, 2000);
      }
    }
  }
  useEffect(() => {
    alive.current = true; generation.current++; working.current = false; setBusy(false); setControl(''); setVerified(false); void reload();
    const visible = () => { if (!document.hidden) void reload(); };
    document.addEventListener('visibilitychange', visible);
    return () => { alive.current = false; sequence.current++; generation.current++; if (timer.current) clearTimeout(timer.current); document.removeEventListener('visibilitychange', visible); };
  }, [path, item.input_revision, user.username]);
  async function work(operation: () => Promise<AiRunV4>, label: string) {
    if (working.current) return;
    const current = ++generation.current;
    sequence.current++; inFlight.current = false;
    working.current = true; setBusy(true); setControl(label); setError(''); setRequestError('');
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void reload(true); }, 2000);
    try { const value = await operation(); if (alive.current && current === generation.current) { accepted(value); await reload(); } }
    catch (value) {
      if (alive.current && current === generation.current) {
        const rejected = value instanceof ApiError && value.status < 500;
        if (rejected) { pendingRef.current = null; setPending(null); preserve(null, selectedRef.current); }
        setRequestError(value instanceof Error ? value.message : 'AI 실행 요청에 실패했습니다.');
        if (accessLost(value)) { setRuns([]); setReady(null); setPreprocess(null); sessionStorage.removeItem(storageKey); }
        else await reload(true);
      }
    }
    finally { if (alive.current && current === generation.current) { working.current = false; setBusy(false); setControl(''); } }
  }
  const allowed = ready?.enabled && preprocess?.result_pointer && ['complete', 'partial'].includes(preprocess.status) && !preprocess.outdated
    && preprocess.input_revision === item.input_revision;
  async function start() {
    if (!allowed || !preprocess?.result_pointer || !ready || pendingRef.current) throw new Error('현재 입력과 접수 상태를 확인하세요.');
    const fields = { expected_revision: item.input_revision, preprocess_ref: preprocess.result_pointer.ref, preprocess_hash: preprocess.result_pointer.hash,
      settings_version: ready.active_version, reuse_run_id: reuse || null };
    const request: AiStartV4 = { ...fields, request_id: crypto.randomUUID() };
    pendingRef.current = request; setPending(request); select(''); preserve(request, '');
    return api<AiRunV4>(path + '/runs-s1', 'POST', request);
  }
  const selected = runs.find(run => run.run_id === selectedId);
  const draft = pending ? busy ? '분석 요청 중' : '요청 접수 여부 확인 중' : !loaded && !error ? '확인 중' : selected ? selected.status === 'succeeded' ? selected.result_available ? '분석 완료' : '결과 게시 확인 필요' : ({ queued: '분석 대기', running: '분석 중', retry_wait: '자동 재시도 대기', partial_failed: '일부 완료 · 확인 필요', stopped: '중지됨', failed: '분석 실패', settings_required: '설정 확인 필요' } as Record<string, string>)[selected.status] ?? states[selected.status] : '준비 안 됨';
  return <section className="panel" aria-label="AI 실행" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>AI 분석</h2><p role="status">AI 초안: {control === '중지 요청 중' ? control : draft}</p>
    {selected && <section aria-label="현재 AI 분석 실행"><p>{selected.requested_by === user.username ? '내가 시작한 이번 실행' : `실행 직원: ${selected.requested_by}`} · 입력 {selected.input_revision}판</p>
      {selected.outdated && <p className="warning">이전 입력 기준 실행입니다.</p>}{selected.settings_outdated && <p className="warning">현재 활성 설정과 다릅니다.</p>}
      {selected.progress.state_uncertain && <p>실행 상태 확인 필요 · 현재 단계를 확인할 수 없습니다. 상태를 다시 조회하세요.</p>}
      {selected.progress.current_stage && <p>현재 단계: {stages[selected.progress.current_stage]}</p>}
      <ol>{selected.progress.stages.map(stage => <li key={stage.stage}>{stages[stage.stage]} · {stage.keys.length ? `완료 ${stage.completed} / 예정 ${stage.keys.length} · 실패 ${stage.failed} · 실행 중 ${stage.running} · 대기 ${stage.waiting}` : '실행 계획에 없음'}
        {stage.keys.some(key => key.reused) && ' · 명시 재사용'}</li>)}</ol>
      {selected.status === 'retry_wait' && <p>자동 재시도 예정: {selected.retry_at ? new Date(selected.retry_at).toLocaleString() : '시각 확인 필요'}</p>}
      <p>시작: {new Date(selected.created_at).toLocaleString()} · 기록 변경: {new Date(selected.updated_at).toLocaleString()}</p>
      {selected.failure_code && <p>일부 단계의 실행 조건 또는 응답을 확인해야 합니다. 아래 실행 사유와 재사용·재시도 경로를 확인하세요.</p>}
    </section>}
    <p className="fine">마지막 확인: {checked || '아직 없음'}</p>
    {runs.some(run => run.run_id !== selectedId && run.result_available) && <p>이전 분석 결과 있음</p>}
    <p>숫자 83개·관찰 메모 3개의 원자료를 요청하고 자동 4개는 앱이 계산합니다. 관찰·계산 뒤 근거 기반 AI 애착 판단을 별도로 수행합니다.</p>
    <details><summary>기술 정보</summary><p>입력 {item.input_revision}판 · 활성 설정 {ready?.active_version === 'inactive' ? '없음' : ready?.active_version ?? '확인 중'} · 기본 예정 공급자 호출 {ready?.planned_provider_calls ?? '—'}회</p>
      <p className="fine">실제 공급자의 정확도·시간·가격은 아직 측정하지 않았습니다. 메뉴 조회는 실행을 만들지 않으며, 실행 중 상태만 2초마다 갱신합니다.</p></details>
    {error && <p role="alert" className="error">상태 조회 연결 끊김 · {error}</p>}
    {requestError && <p role="alert" className="error">{requestError}</p>}
    <button disabled={loading} onClick={() => { void reload(); }}>AI 실행 상태 새로고침</button>
    {verified && !ready?.enabled && <p role="status">개발자가 AI 설정을 활성화해야 실행할 수 있습니다.</p>}
    {verified && (!preprocess?.result_pointer || preprocess.outdated) && <p role="status">현재 입력 기준의 전처리 결과가 필요합니다.</p>}
    {preprocess?.status === 'partial' && <p>전처리가 일부만 완성되었습니다. 없는 카메라·클립의 항목은 관찰 부족 사유를 유지합니다.</p>}
    <fieldset disabled={busy || loading}><legend>명시 실행과 재사용</legend>
      <label>성공 항목군 재사용<select aria-label="성공 항목군 재사용" value={reuse} onChange={event => setReuse(event.target.value)}><option value="">재사용 없이 새 실행</option>{runs.filter(run => !run.outdated && run.steps.some(step => step.stage === 'score_v4' && step.status === 'succeeded')).map(run => <option key={run.run_id} value={run.run_id}>{run.run_id.slice(0, 8)} · {states[run.status] ?? run.status} · 성공 항목군 {run.steps.filter(step => step.stage === 'score_v4' && step.status === 'succeeded').length}개</option>)}</select></label>
      <p className="fine">재사용은 같은 원본·창·카메라·오프셋·모델·설정 해시를 다시 검증합니다. 부분 완료의 재생성도 새 실행으로 기록합니다.</p>
      <button disabled={!allowed || !verified || !!pending} onClick={() => void work(start, '분석 요청 중')}>AI 분석 시작</button>
      {pending && <p role="status">요청 접수 여부 확인 중 · 상태 조회로 같은 요청을 확인합니다.</p>}
      <label>실행 제어 사유<input value={reason} onChange={event => setReason(event.target.value)} maxLength={2000} placeholder="중지 또는 재시도 이유" /></label>
    </fieldset>
    {!runs.length && <p>생성된 AI 실행이 없습니다.</p>}
    {runs.map(run => <article className="panel" key={run.run_id} aria-label={`AI 실행 기록 ${run.run_id.slice(0, 8)}`}>
      <button disabled={busy} onClick={() => select(run.run_id)}>이 실행 상태 보기</button>
      <h3>{states[run.status] ?? run.status}{run.outdated ? ' · 이전 입력 기준' : ''}</h3>
      <p>입력 {run.input_revision}판 · {new Date(run.updated_at).toLocaleString()}</p>
      {run.judgement_status !== 'implemented_professor_test_pending' && <p>이전 애착 판단 정책으로 만든 실행입니다.</p>}
      {run.failure_code && <p role="status">실행 사유: {run.failure_code}</p>}
      {run.steps.some(step => step.billing_uncertain) && <p className="warning">응답 또는 정산이 확인되지 않은 예약 호출이 있습니다. 과금 여부 미확인 상태를 유지합니다.</p>}
      {run.result_available && <p>원자료와 기본 계산이 게시되었습니다. 시트를 명시적으로 열면 실제 AI 열람 이력이 기록됩니다. 실행 상태에는 점수·판정을 표시하지 않습니다.</p>}
      <div className="toolbar">{active.has(run.status) && <button disabled={busy || !!pending || !verified || !reason.trim()} onClick={() => void work(() => api<AiRunV4>(`/runs-s1/${run.run_id}/stop`, 'POST', { expected_updated_at: run.updated_at, reason: reason.trim() }), '중지 요청 중')}>이 AI 실행 중지</button>}
        {['failed', 'stopped', 'settings_required'].includes(run.status) && <button disabled={busy || !!pending || !verified || !reason.trim() || run.outdated} onClick={() => void work(() => api<AiRunV4>(`/runs-s1/${run.run_id}/retry`, 'POST', { expected_updated_at: run.updated_at, reason: reason.trim() }), '재시도 요청 중')}>고정 입력으로 AI 재시도</button>}</div>
      <details><summary>기술 정보 · 단계별 시간·호출·부분 실패</summary><p className="fine">실행 {run.run_id} · 기본 계획 {run.planned_provider_calls}회 · 예약 {run.reserved_calls}회 / 상한 {run.max_ai_calls}회</p><p className="fine">시간은 기록된 단계 값입니다. 수리와 전체 단계는 다른 시간 항목과 겹칠 수 있으므로 합산하지 않습니다. 빈 계량은 0으로 추정하지 않습니다.</p>
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
  return <section className="panel" aria-label="공개한 AI 기본 결과" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h3>명시 공개한 AI 기본 결과 · 읽기 전용</h3><p>AI 열람 이력이 기록된 결과입니다. 독립 사람 원자료와 자동 계산은 보존되며, 유형과 근거·반대 근거·보류 사유를 확인하세요.</p>
    {!results.length && <p>공개한 원자료와 일치하는 기본 결과가 없습니다.</p>}
    {results.map(result => <article key={result.result_id}>
      <h4>AI 결과 {result.revision}판 · 원자료 {result.input.revision}판</h4><p>계산 판본 {result.rule_version} · 작성 {new Date(result.recorded_at).toLocaleString()}</p>
      {result.attachment_assessment && <details><summary>AI 애착 판단의 고정 출처</summary><p>독립 AI 판단 · 모델 {result.attachment_assessment.model} · 지침 {result.attachment_assessment.response.instruction_version}</p><p>지지 근거 ID: {result.attachment_assessment.response.evidence_refs.join(', ') || '없음'} · 반대 근거 ID: {result.attachment_assessment.response.counter_evidence_refs.join(', ') || '없음'}</p><p>입력 SHA-256: {result.attachment_assessment.response.input_hash}<br />지침 내용 SHA-256: {result.attachment_assessment.response.instruction_hash}</p></details>}
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
