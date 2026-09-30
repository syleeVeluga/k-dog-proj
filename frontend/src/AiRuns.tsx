import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { Notification } from './Notification';
import type { Case } from './types';

type Run = { run_id: string; status: string; updated_at: string; input_revision: number; outdated: boolean; failure_code: string | null; result_available: boolean; steps: { stage: string; key: string; attempt: number; status: string; code: string | null; billing_uncertain: boolean; call_reserved: boolean }[] };
type Ready = { active_version: string; enabled: boolean; planned_provider_calls: number };
type Preprocess = { status: string; outdated: boolean; result_pointer: { ref: string; hash: string } | null };
const statuses: Record<string, string> = { queued: '접수됨', running: '처리 중', retry_wait: '재시도 대기', succeeded: '완료', partial_failed: '일부 요청 실패 · 부분 결과 보존', failed: '실패', stopped: '중지', settings_required: '설정 필요' };

export function AiRuns({ item, manager }: { item: Case; manager: boolean }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [ready, setReady] = useState<Ready | null>(null);
  const [preprocess, setPreprocess] = useState<Preprocess | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reuse, setReuse] = useState('');
  const pending = useRef<{ input: string; request_id: string } | null>(null);
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [list, config, media] = await Promise.all([api<Run[]>(path + '/runs-v3'), api<Ready>('/scoring-ai/status'), api<Preprocess>(path + '/preprocess')]);
        if (active) { setRuns(list); setReady(config); setPreprocess(media); }
      } catch (e) { if (active) { setError(String(e)); setReady(null); setPreprocess(null); } }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [path]);
  async function work(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); setRuns(await api<Run[]>(path + '/runs-v3')); }
    catch (e) { setError(e instanceof Error ? e.message : 'AI 실행 실패'); }
    finally { setBusy(false); }
  }
  async function start() {
    if (!ready || !preprocess?.result_pointer) return;
    const fields = { expected_revision: item.input_revision, preprocess_ref: preprocess.result_pointer.ref, preprocess_hash: preprocess.result_pointer.hash,
      settings_version: ready.active_version, reuse_run_id: reuse || null };
    const input = JSON.stringify(fields);
    if (pending.current?.input !== input) pending.current = { input, request_id: crypto.randomUUID() };
    await api(path + '/runs-v3', 'POST', { ...fields, request_id: pending.current.request_id });
    pending.current = null;
  }
  const allowed = ready?.enabled && preprocess?.status === 'complete' && !preprocess.outdated && preprocess.result_pointer && item.consents.analysis_feedback === 'confirmed';
  return <section className="panel" aria-label="독립 AI 실행"><h2>독립 AI 실행</h2>
    <Notification message={error} kind="error" onClose={() => setError('')} />
    <p>입력 r{item.input_revision} · 설정 {ready?.active_version ?? '조회 중'} · 기본 계획 {ready?.planned_provider_calls ?? '—'}회 · 비용 미확인</p>
    <p className="fine">분석·피드백 동의, 최신 전처리, Q11 적용 범위를 확인한 설정이 필요합니다. 메뉴 재방문·조회는 실행을 생성하지 않습니다.</p>
    {manager && <><label>성공 항목군 명시 재사용<select value={reuse} onChange={e => setReuse(e.target.value)} disabled={busy}><option value="">재사용 없이 새 실행</option>{runs.filter(run => run.steps.some(step => step.stage === 'score_v3' && step.status === 'succeeded')).map(run => <option key={run.run_id} value={run.run_id}>{run.run_id.slice(0, 8)} · {statuses[run.status]}</option>)}</select></label>
      <button disabled={busy || !allowed} onClick={() => void work(start)}>현재 입력으로 AI 새 실행 생성</button></>}
    {runs.length === 0 && <p>생성한 AI 실행이 없습니다.</p>}
    {runs.map(run => <article key={run.run_id}><h3>{statuses[run.status] ?? run.status}</h3><p>{run.run_id} · 입력 r{run.input_revision} {run.outdated && '· 이전 입력 기준'} · 예약 호출 {run.steps.filter(step => step.call_reserved).length}회</p>
      {run.failure_code && <p role="status">{run.failure_code}</p>}
      {run.result_available && <p>완료 원자료·기본 계산은 독립 제출 뒤 명시 공개한 시트에서 열 수 있습니다.</p>}
      {manager && <div className="toolbar">{['queued', 'running', 'retry_wait'].includes(run.status) && <button disabled={busy} onClick={() => void work(() => api('/runs-v3/' + run.run_id + '/stop', 'POST', { expected_updated_at: run.updated_at, reason: '운영자 명시 중지' }))}>이 실행 중지</button>}
        {['failed', 'stopped', 'settings_required'].includes(run.status) && <button disabled={busy} onClick={() => void work(() => api('/runs-v3/' + run.run_id + '/retry', 'POST', { expected_updated_at: run.updated_at, reason: '운영자 명시 재시도' }))}>고정 입력으로 재시도</button>}</div>}
      <details><summary>단계·시도·오류 상태</summary><ul>{run.steps.map((step, i) => <li key={i}>{step.stage} / {step.key} · 시도 {step.attempt} · {step.status} {step.code && `· ${step.code}`} {step.billing_uncertain && '· 과금 여부 미확인'}</li>)}</ul></details>
    </article>)}
  </section>;
}
