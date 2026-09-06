import { useEffect, useState } from 'react';
import { api } from './api';

type Stage = 'observe' | 'dog' | 'owner' | 'report';
type StageConfig = { provider: string; model: string; prompt: string; max_output_tokens: number };
type Pipeline = Record<Stage, StageConfig> & { fps: number; max_attempts: number; evaluation_concurrency: number; max_ai_calls: number };
type Trial = { trial_id: string; stage: Stage; mode: string; status: string; output?: unknown; usage: unknown };
type Settings = { active_version: string; config: Pipeline; versions: { version: string; created_at: string; actor: string }[];
  trials: Trial[]; keys: { provider: string; available: boolean; reference: string }[] };
const stages: Record<Stage, string> = { observe: 'Gemini 관찰', dog: '반려견 평가', owner: '보호자 평가', report: '리포트 설명' };

export function DeveloperSettings({ onVersionModeChange }: { onVersionModeChange: (active: boolean) => void }) {
  const [data, setData] = useState<Settings | null>(null);
  const [config, setConfig] = useState<Pipeline | null>(null);
  const [stage, setStage] = useState<Stage>('observe');
  const [version, setVersion] = useState('');
  const [diff, setDiff] = useState('');
  const [trial, setTrial] = useState<Trial | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [provider, setProvider] = useState('gemini');
  async function reload(reset = false) {
    const value = await api<Settings>('/developer/settings');
    setData(value); if (reset) setConfig(value.config);
    onVersionModeChange(value.active_version !== 'legacy');
  }
  useEffect(() => { void reload(true).catch(e => setError(e.message)); }, []);
  async function work(action: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : '작업에 실패했습니다.'); }
    finally { setBusy(false); }
  }
  async function selectVersion(id: string) {
    const value = await api<{ config: Pipeline; diff: string }>(`/developer/settings/${id}`);
    setVersion(id); setConfig(value.config); setDiff(value.diff || '운영 버전과 내용이 같습니다.'); setTrial(null);
  }
  function edit(value: Partial<StageConfig>) {
    if (config) setConfig({ ...config, [stage]: { ...config[stage], ...value } });
    setVersion(''); setDiff(''); setTrial(null);
  }
  function limits(value: Partial<Pipeline>) {
    if (config) setConfig({ ...config, ...value });
    setVersion(''); setDiff(''); setTrial(null);
  }
  return <section className="panel developer-settings"><h2>프롬프트·파이프라인 버전</h2>
    <p className="fine">현재 버전을 복제하여 편집합니다. 초안 저장과 시험은 참가자 결과에 영향을 주지 않습니다. 운영 적용·복원은 새 분석부터 사용합니다.</p>
    {error && <p className="error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    {data && config && <fieldset disabled={busy}>
      <p className="fine">운영 버전 <span className="mono">{data.active_version}</span></p>
      <div className="form-grid"><label>저장 버전<select value={version} onChange={e => { const id = e.target.value; if (id) void work(() => selectVersion(id)); }}>
        <option value="">편집 중인 새 초안</option>{data.versions.map(v => <option key={v.version} value={v.version}>{v.created_at.slice(0, 19)} · {v.version.slice(0, 8)} · {v.actor}</option>)}
      </select></label><label>편집 단계<select value={stage} onChange={e => setStage(e.target.value as Stage)}>
        {Object.entries(stages).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
      </select></label></div>
      <div className="form-grid"><label>단계 공급자<select value={config[stage].provider} onChange={e => edit({ provider: e.target.value, model: '' })} disabled={stage === 'observe'}>
        <option value="gemini">Gemini</option><option value="openai">GPT · OpenAI</option><option value="anthropic">Claude · Anthropic</option>
      </select></label><label>단계 모델 ID<input value={config[stage].model} maxLength={150} onChange={e => edit({ model: e.target.value })} /></label>
      <label>최대 출력 토큰<input type="number" min={256} max={16384} value={config[stage].max_output_tokens} onChange={e => edit({ max_output_tokens: Number(e.target.value) })} /></label></div>
      <label>단계 프롬프트<textarea rows={12} maxLength={24000} value={config[stage].prompt} onChange={e => edit({ prompt: e.target.value })} /></label>
      <div className="form-grid"><label>관찰 FPS<input type="number" min={0.1} max={10} step={0.1} value={config.fps} onChange={e => limits({ fps: Number(e.target.value) })} /></label>
        <label>최대 시도 수<input type="number" min={1} max={3} value={config.max_attempts} onChange={e => limits({ max_attempts: Number(e.target.value) })} /></label>
        <label>평가 동시 요청<select value={config.evaluation_concurrency} onChange={e => limits({ evaluation_concurrency: Number(e.target.value) })}><option value={1}>1</option><option value={2}>2</option></select></label>
        <label>분석당 AI 호출 상한<input type="number" min={1} max={1000} value={config.max_ai_calls} onChange={e => limits({ max_ai_calls: Number(e.target.value) })} /></label></div>
      <p className="fine">호출 상한에는 재시도·응답 유실도 포함합니다. 통화 금액 한도는 아닙니다. 참가자·카메라 동시 처리는 각각 1건이며 확정 항목집·계산 규칙은 편집하지 않습니다.</p>
      <div className="toolbar"><button onClick={() => void work(async () => {
        const saved = await api<{ version: string }>('/developer/settings/drafts', 'POST', { expected_active: data.active_version, config });
        await reload(); await selectVersion(saved.version); setMessage('초안을 저장했습니다. 운영 버전은 유지됩니다.');
      })}>새 초안 저장</button>
        <button disabled={!version} onClick={() => void work(async () => { setTrial(await api<Trial>(`/developer/settings/${version}/trial`, 'POST', { stage, mode: 'schema' })); })}>스키마 시험</button>
        <button disabled={!version} onClick={() => void work(async () => { setTrial(await api<Trial>(`/developer/settings/${version}/trial`, 'POST', { stage, mode: 'provider' })); })}>합성 샘플 API 시험 · 과금 가능</button>
        <button className="primary" disabled={!version} onClick={() => void work(async () => {
          await api(`/developer/settings/${version}/activate`, 'POST', { expected_active: data.active_version });
          await reload(); await selectVersion(version); setMessage('선택 버전을 운영 적용·복원했습니다. 기존 분석은 고정 설정을 유지합니다.');
        })}>선택 버전 운영 적용·복원</button></div>
      {diff && <details open><summary>운영 버전과 차이</summary><pre className="settings-diff">{diff}</pre></details>}
      <p className="fine">합성 샘플은 회색 무음 영상 또는 빈 관찰 근거를 사용합니다. 실 참가자 정보는 사용하지 않으며, 한 단계당 AI 요청 1회를 실행합니다. 스키마 통과는 모델 지원·품질 검증을 뜻하지 않습니다.</p>
      {trial && <div role="status"><strong>시험 결과: {trial.status}</strong><pre className="settings-diff">{JSON.stringify(trial, null, 2)}</pre></div>}
      {!!data.trials.length && <details><summary>저장된 시험 이력</summary>{data.trials.map(t => <p key={t.trial_id}>{stages[t.stage]} · {t.mode} · {t.status}</p>)}</details>}
      <h3>공급자 키 관리</h3><p className="fine">Windows 실행 계정의 DPAPI로 보호합니다. 등록 후 원문은 조회할 수 없습니다. 폐기하면 환경 변수 키로 자동 복귀하지 않습니다.</p>
      <ul>{data.keys.map(k => <li key={k.provider}>{k.provider} · {k.available ? '등록됨' : '개발자 설정 필요'}</li>)}</ul>
      <form onSubmit={e => { e.preventDefault(); const form = e.currentTarget;
        const value = String(new FormData(form).get('secret') || ''); form.reset();
        void work(async () => { await api(`/developer/keys/${provider}`, 'PUT', { value }); await reload(); setMessage('키를 보호하여 저장했습니다.'); });
      }}><label>키 공급자<select value={provider} onChange={e => setProvider(e.target.value)}><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></label>
        <label>새 API 키<input type="password" name="secret" autoComplete="off" minLength={8} maxLength={512} required /></label>
        <div className="toolbar"><button type="submit">키 등록·교체</button><button type="button" onClick={() => void work(async () => {
          const result = await api<{ status: string }>(`/developer/keys/${provider}/test`, 'POST'); setMessage(`연결 시험: ${result.status} · 모델 실행 지원은 샘플 시험에서 확인하세요.`);
        })}>키 연결 시험</button><button type="button" onClick={() => void work(async () => {
          await api(`/developer/keys/${provider}`, 'DELETE'); await reload(); setMessage('키를 폐기했습니다.');
        })}>선택 공급자 키 폐기</button></div>
      </form>
    </fieldset>}
  </section>;
}

export function Recovery() {
  const [status, setStatus] = useState<{ message: string; free_bytes: number; deletion_requests: number; runs: Record<string, number>; last_backup: { path: string } | null } | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api<typeof status>('/admin/recovery').then(setStatus).catch(e => setMessage(e.message)); }, []);
  return <details className="panel"><summary>자료 백업·복구</summary>
    {status && <><p>{status.message}</p><p>남은 공간 {(status.free_bytes / 1024 ** 3).toFixed(1)} GB · 삭제 요청 {status.deletion_requests}건</p>
      <p className="fine">최근 백업: {status.last_backup?.path ?? '없음'}</p></>}
    <button disabled={busy} onClick={() => { setBusy(true); void api<{ path: string }>('/admin/backups', 'POST')
      .then(v => setMessage(`검증된 백업 저장 완료: ${v.path}`)).catch(e => setMessage(e.message)).finally(() => setBusy(false)); }}>{busy ? '파일 검증·백업 중…' : '자료 백업 생성 · 키 제외'}</button>
    {message && <p role="status" className="fine">{message}</p>}
  </details>;
}
