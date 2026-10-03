import { useEffect, useState } from 'react';
import { api } from './api';
import { useEditBase } from './Editing';
import { Notification } from './Notification';
import { AiSettingsV4 } from './AiSettingsV4';

type Stage = { model: string; prompt: string; processing_mode: 'static' | 'agentic'; fps: number | null; media_resolution: string; thinking_level: string; max_output_tokens: number };
type Pipeline = { groups: Record<string, Stage>; judgement: Stage; q11_scope_confirmed: boolean; max_attempts: number; max_ai_calls: number; max_schema_repairs: number };
type View = { active_version: string; config: Pipeline; groups: Record<string, { windows: string[]; codes: string[] }>; planned_provider_calls: number; versions: { version: string }[]; trials: { group: string; status: string; mode: string }[] };
type Difference = { active_version: string; version: string; config: Pipeline; diff: string };

export function AiSettings() {
  const [spec, setSpec] = useState(''), [error, setError] = useState('');
  useEffect(() => { let active = true; api<{ spec: string }>('/health').then(value => { if (active) setSpec(value.spec); }).catch(value => { if (active) setError(String(value)); }); return () => { active = false; }; }, []);
  if (!spec) return <p role="status">{error || 'AI 설정 판본 확인 중'}</p>;
  return spec === '20261002' ? <AiSettingsV4 /> : <LegacyAiSettings />;
}

function LegacyAiSettings() {
  const [latest, setLatest] = useState<View | null>(null);
  const [draft, setDraft] = useState<Pipeline | null>(null);
  const [group, setGroup] = useState('judgement');
  const [saved, setSaved] = useState<Difference | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const edit = useEditBase(latest);
  const view = edit.view;
  const config = edit.dirty ? draft : view?.config;
  const path = '/developer/settings-v3';
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const result = await api<View>(path); if (active) setLatest(result); }
      catch (e) { if (active) setError(String(e)); }
      if (active) timer = setTimeout(poll, 3000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, []);
  function change(patch: Partial<Pipeline>) { if (config) { edit.change(); setDraft({ ...config, ...patch }); setSaved(null); } }
  function stageChange(patch: Partial<Stage>) {
    if (!config) return;
    if (group === 'judgement') change({ judgement: { ...config.judgement, ...patch } });
    else change({ groups: { ...config.groups, [group]: { ...config.groups[group], ...patch } } });
  }
  async function work(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await action(); setLatest(await api<View>(path)); }
    catch (e) { setError(e instanceof Error ? e.message : '신판 설정 작업 실패'); }
    finally { setBusy(false); }
  }
  if (!view || !config) return <Notification message={error} kind="error" onClose={() => setError('')} />;
  const selected = group === 'judgement' ? config.judgement : config.groups[group];
  return <section className="panel" aria-label="신판 AI 설정"><h2>신판 AI 설정 · 직접 109행</h2>
    <Notification message={error} kind="error" onClose={() => setError('')} /><Notification message={notice} onClose={() => setNotice('')} />
    <p>활성 판본 {latest?.active_version} · 기본 계획 {view.planned_provider_calls}회 · 가격 미확인</p>
    <p className="fine">구판 설정과 별도로 저장합니다. 원본 fps·전체 오디오를 보존하며 요청 fps는 항목군마다 다릅니다. 실제 판독 정확도는 미검증입니다.</p>
    <fieldset disabled={busy}>
      <label>설정 항목군<select aria-label="설정 항목군" value={group} onChange={e => setGroup(e.target.value)}><option value="judgement">기본 판정</option>{Object.entries(view.groups).map(([key, item]) => <option key={key} value={key}>{item.windows.join(' + ')} · {item.codes.join(', ')}</option>)}</select></label>
      <p>모델 {selected.model} · 제작 fps 원본</p>
      <label>Processing mode<select value={selected.processing_mode} onChange={e => stageChange({ processing_mode: e.target.value as Stage['processing_mode'], fps: e.target.value === 'agentic' ? null : 8 })}><option value="static">static · 명시 fps</option><option value="agentic">agentic · 동적 읽기</option></select></label>
      {selected.processing_mode === 'static' && <label>Provider 요청 fps<input type="number" min="0.1" max="10" step="0.1" value={selected.fps ?? 8} onChange={e => stageChange({ fps: Number(e.target.value) })} /></label>}
      <label>Media resolution<select value={selected.media_resolution} onChange={e => stageChange({ media_resolution: e.target.value })}>{['low', 'medium', 'high'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Thinking level<select value={selected.thinking_level} onChange={e => stageChange({ thinking_level: e.target.value })}>{['low', 'medium', 'high'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>출력 token 상한<input type="number" min="256" max="65536" value={selected.max_output_tokens} onChange={e => stageChange({ max_output_tokens: Number(e.target.value) })} /></label>
      <label>항목군 프롬프트<textarea rows={8} maxLength={24000} value={selected.prompt} onChange={e => stageChange({ prompt: e.target.value })} /></label>
      <label>전체 호출 상한<input type="number" min={view.planned_provider_calls} max="1000" value={config.max_ai_calls} onChange={e => change({ max_ai_calls: Number(e.target.value) })} /></label>
      <label>단계 시도 상한<input type="number" min="1" max="3" value={config.max_attempts} onChange={e => change({ max_attempts: Number(e.target.value) })} /></label>
      <label>Schema 수리 상한<input type="number" min="0" max="1" value={config.max_schema_repairs} onChange={e => change({ max_schema_repairs: Number(e.target.value) })} /></label>
      <label><input type="checkbox" checked={config.q11_scope_confirmed} onChange={e => change({ q11_scope_confirmed: e.target.checked })} />Q11 운영 AI 적용 범위를 확인한 설정</label>
      <button onClick={() => void work(async () => { const result = await api<{ version: string }>(path + '/drafts', 'POST', { expected_active: view.active_version, config }); setSaved(await api<Difference>(path + '/' + result.version)); edit.reset(); setNotice('신판 초안을 저장했습니다. 차이를 확인하고 활성화하세요.'); })}>신판 초안 저장</button>
      {edit.dirty && <button onClick={() => edit.discard()}>미저장 입력 버리고 최신 설정</button>}
      <label>보존 설정<select value={saved?.version ?? ''} onChange={e => { const version = e.target.value; if (!edit.dirty) void work(async () => { setSaved(version ? await api<Difference>(path + '/' + version) : null); }); }} disabled={edit.dirty}><option value="">설정 선택</option>{latest?.versions.map(value => <option key={value.version}>{value.version}</option>)}</select></label>
      {saved && <><details open><summary>활성본과의 차이 · {saved.version}</summary><pre>{saved.diff || '차이 없음'}</pre></details>
        <button disabled={edit.dirty || !saved.config.q11_scope_confirmed} onClick={() => void work(async () => { await api(path + '/' + saved.version + '/activate', 'POST', { expected_active: saved.active_version }); setSaved(null); edit.reset(); setNotice('신판 설정을 활성화했습니다. 기존 실행 입력은 보존됩니다.'); })}>이 신판 초안 활성화</button>
        {(['schema', 'provider'] as const).map(mode => <button key={mode} disabled={edit.dirty} onClick={() => void work(async () => { const result = await api<{ status: string }>(path + '/' + saved.version + '/trial', 'POST', { group, mode }); setNotice(`${mode} 합성 시험: ${result.status}`); })}>{mode === 'schema' ? '계약 시험' : 'Provider 합성 시험 · 외부 호출 1회'}</button>)}</>}
    </fieldset>
    <ul>{latest?.trials.map((trial, i) => <li key={i}>{trial.group} · {trial.mode} · {trial.status} · 합성 자료 시험</li>)}</ul>
  </section>;
}
