import { useEffect, useRef, useState } from 'react';
import { api, accessLost } from './api';
import { useEditBase } from './Editing';
import { WINDOW_NAMES } from './recordingTypesV4';
import type { AiDifferenceV4, AiPipelineV4, AiSettingsViewV4, AiStageV4, AiTrialV4 } from './aiTypesV4';

export function AiSettingsV4() {
  const [latest, setLatest] = useState<AiSettingsViewV4 | null>(null), [draft, setDraft] = useState<AiPipelineV4 | null>(null);
  const [group, setGroup] = useState(''), [saved, setSaved] = useState<AiDifferenceV4 | null>(null);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false), [unavailable, setUnavailable] = useState(false);
  const edit = useEditBase(latest), alive = useRef(true), pending = useRef(false), sequence = useRef(0);
  const view = edit.view, config = edit.dirty ? draft : view?.config;
  async function reload() {
    const current = ++sequence.current;
    const value = await api<AiSettingsViewV4>('/settings-s1');
    if (alive.current && current === sequence.current) { setLatest(value); setUnavailable(false); }
  }
  useEffect(() => {
    alive.current = true;
    void reload().catch(value => { if (alive.current) { setError(value.message); setUnavailable(accessLost(value)); } });
    return () => { alive.current = false; sequence.current++; };
  }, []);
  function change(patch: Partial<AiPipelineV4>) { if (config) { edit.change(); setDraft({ ...config, ...patch }); setSaved(null); } }
  const selectedGroup = group && config?.groups[group] ? group : Object.keys(config?.groups ?? {})[0];
  const stage = config?.groups[selectedGroup], specification = view?.groups[selectedGroup];
  function stageChange(patch: Partial<AiStageV4>) { if (config && stage) change({ groups: { ...config.groups, [selectedGroup]: { ...stage, ...patch } } }); }
  async function work(operation: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setNotice('');
    try { await operation(); if (alive.current) await reload(); }
    catch (value) { if (alive.current) { setError(value instanceof Error ? value.message : 'S1 설정 작업에 실패했습니다.'); if (accessLost(value)) setUnavailable(true); } }
    finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  function validate() {
    if (!config || !view) throw new Error('S1 설정을 불러오세요.');
    if (!Number.isInteger(config.max_ai_calls) || config.max_ai_calls < view.planned_provider_calls || config.max_ai_calls > 1000) throw new Error(`전체 호출 상한은 ${view.planned_provider_calls}~1000의 정수여야 합니다.`);
    if (!Number.isInteger(config.max_attempts) || config.max_attempts < 1 || config.max_attempts > 3 || ![0, 1].includes(config.max_schema_repairs)) throw new Error('시도 상한 1~3, 스키마 수리 상한 0~1을 확인하세요.');
    for (const value of Object.values(config.groups)) {
      if (!value.prompt.trim() || !Number.isInteger(value.max_output_tokens) || value.max_output_tokens < 256 || value.max_output_tokens > 65536) throw new Error('각 항목군의 프롬프트와 출력 토큰 상한을 확인하세요.');
      if (value.processing_mode === 'static' && (value.fps === null || value.fps <= 0 || value.fps > (value.input_variant === 'ai' ? 1 : 10))) throw new Error('정적 읽기의 요청 FPS는 0보다 커야 하며, AI용 클립은 최대 1 FPS입니다.');
    }
  }
  if (unavailable) return <section className="panel" aria-label="S1 AI 설정"><p role="alert">{error || 'S1 설정 접근 권한을 확인하세요.'}</p></section>;
  if (!view || !config || !stage || !specification) return <section className="panel" aria-label="S1 AI 설정"><p role="status">{error || 'S1 설정 조회 중…'}</p><button disabled={busy} onClick={() => void work(async () => {})}>S1 설정 새로고침</button></section>;
  return <section className="panel" aria-label="S1 AI 설정" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>S1 관찰 원자료 AI 설정</h2>
    <p>숫자 83개 · 관찰 메모 3개 · {Object.keys(view.groups).length}개 항목군 · 기본 예정 공급자 호출 {view.planned_provider_calls}회</p>
    <p>활성 설정: {latest?.active_version === 'inactive' ? '없음' : latest?.active_version} · 비용: {view.price_estimate ?? '미측정'}</p>
    <p>자동 4개는 앱이 계산합니다. 개21 복수 사건 집계와 D04 상세 유형 해석은 보류하며, 이 화면의 범위 확인으로 승인되지 않습니다.</p>
    <p className="fine">합성 스키마 검증은 외부 호출 0회입니다. 실제 공급자 정확도·처리 시간은 S16에서 별도로 측정합니다.</p>
    {error && <p role="alert" className="error">{error} 미저장 입력은 유지합니다.</p>}{notice && <p role="status">{notice}</p>}
    {edit.dirty && latest?.active_version !== view.active_version && <p role="status">다른 활성 설정이 저장되었습니다. 입력과 편집 시작 판본을 유지합니다.</p>}
    <button disabled={busy} onClick={() => void work(async () => {})}>S1 설정 새로고침</button>
    <fieldset disabled={busy}><legend>항목군 설정</legend>
      <label>설정할 S1 항목군<select aria-label="설정할 S1 항목군" value={selectedGroup} onChange={event => setGroup(event.target.value)}>{Object.entries(view.groups).map(([key, value]) => <option key={key} value={key}>{value.codes.join(', ')} · {value.windows.map(window => WINDOW_NAMES[window] ?? window).join(' + ')}</option>)}</select></label>
      <p>{specification.modality === 'audio' ? '연속 오디오 관찰' : '영상 관찰'} · {specification.whole ? '전체 창 관찰 필요' : '항목별 실제 관찰 범위'} · 기회 조건 {specification.opportunity_codes.join(', ') || '별도 코드 없음'}</p>
      {!specification.provider_call && <p role="status">이 항목군은 규칙 확인 대기입니다. 공급자에게 호출하지 않으며 null과 보류 사유를 보존합니다.</p>}
      <fieldset disabled={!specification.provider_call}><legend>공급자 입력</legend><p>모델: {stage.model}</p>
        <label>입력 클립<select aria-label="입력 클립" value={stage.input_variant} onChange={event => { const input_variant = event.target.value as AiStageV4['input_variant']; stageChange({ input_variant, fps: stage.fps === null ? null : input_variant === 'ai' ? Math.min(stage.fps, 1) : stage.fps }); }}><option value="ai">AI용 · 실제 1초 1프레임</option><option value="original">원본 FPS 클립</option></select></label>
        <label>영상 읽기 방식<select aria-label="영상 읽기 방식" value={stage.processing_mode} onChange={event => stageChange({ processing_mode: event.target.value as AiStageV4['processing_mode'], fps: event.target.value === 'agentic' ? null : 1 })}><option value="static">정적 읽기 · 요청 FPS 지정</option><option value="agentic">동적 읽기 · 공급자 선택</option></select></label>
        {stage.processing_mode === 'static' && <label>공급자 요청 FPS<input aria-label="공급자 요청 FPS" type="number" min={0.1} max={stage.input_variant === 'ai' ? 1 : 10} step={0.1} value={stage.fps ?? 1} onChange={event => stageChange({ fps: Number(event.target.value) })} /></label>}
        <p className="fine">클립 제작 FPS와 공급자 요청 FPS는 별개입니다. 없는 원본 프레임을 늘려 관찰량으로 간주하지 않습니다. 오디오는 연속 구간을 사용합니다.</p>
        <div className="form-grid"><label>입력 해상도<select aria-label="입력 해상도" value={stage.media_resolution} onChange={event => stageChange({ media_resolution: event.target.value as AiStageV4['media_resolution'] })}>{['low', 'medium', 'high'].map(value => <option key={value}>{value}</option>)}</select></label>
          <label>추론 수준<select aria-label="추론 수준" value={stage.thinking_level} onChange={event => stageChange({ thinking_level: event.target.value as AiStageV4['thinking_level'] })}>{['low', 'medium', 'high'].map(value => <option key={value}>{value}</option>)}</select></label>
          <label>출력 토큰 상한<input type="number" min={256} max={65536} value={stage.max_output_tokens} onChange={event => stageChange({ max_output_tokens: Number(event.target.value) })} /></label></div>
        <label>S1 항목군 프롬프트<textarea aria-label="S1 항목군 프롬프트" rows={9} maxLength={24000} value={stage.prompt} onChange={event => stageChange({ prompt: event.target.value })} /></label>
      </fieldset>
      <div className="form-grid"><label>전체 호출 상한<input type="number" min={view.planned_provider_calls} max={1000} value={config.max_ai_calls} onChange={event => change({ max_ai_calls: Number(event.target.value) })} /></label>
        <label>단계 시도 상한<input type="number" min={1} max={3} value={config.max_attempts} onChange={event => change({ max_attempts: Number(event.target.value) })} /></label>
        <label>스키마 수리 상한<input type="number" min={0} max={1} value={config.max_schema_repairs} onChange={event => change({ max_schema_repairs: Number(event.target.value) })} /></label></div>
      <label className="check"><input type="checkbox" checked={config.raw_observation_scope_confirmed} onChange={event => change({ raw_observation_scope_confirmed: event.target.checked })} />관찰 원자료 적용 범위를 확인했습니다. D04 상세 해석은 계속 보류합니다.</label>
      <div className="toolbar"><button onClick={() => void work(async () => { validate(); const next = await api<{ version: string }>('/settings-s1', 'POST', { expected_active: view.active_version, config }); const difference = await api<AiDifferenceV4>(`/settings-s1/${next.version}/diff`); if (alive.current) { setSaved(difference); edit.reset(); setNotice('S1 초안을 저장했습니다. 차이와 범위를 확인한 뒤 활성화하세요.'); } })}>S1 설정 초안 저장</button>
        {edit.dirty && <button onClick={() => { if (edit.discard()) { setDraft(null); setError(''); } }}>미저장 설정 버리고 최신 조회</button>}</div>
      <label>보존 S1 설정<select aria-label="보존 S1 설정" disabled={edit.dirty} value={saved?.version ?? ''} onChange={event => { const version = event.target.value; void work(async () => { const next = version ? await api<AiDifferenceV4>(`/settings-s1/${version}/diff`) : null; if (alive.current) setSaved(next); }); }}><option value="">저장한 설정 선택</option>{latest?.versions.map(value => <option key={value.version} value={value.version}>{new Date(value.created_at).toLocaleString()} · {value.actor} · {value.version.slice(0, 8)}</option>)}</select></label>
      {saved && <><details open><summary>활성 설정과의 차이</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{saved.diff || '차이 없음'}</pre></details>
        <p>초안 {saved.version} · 관찰 원자료 범위 {saved.config.raw_observation_scope_confirmed ? '확인' : '미확인'} · D04 해석 보류</p>
        <div className="toolbar"><button disabled={edit.dirty || !saved.config.raw_observation_scope_confirmed} onClick={() => void work(async () => { await api(`/settings-s1/${saved.version}/activate`, 'POST', { expected_active: saved.active_version }); if (alive.current) { setSaved(null); edit.reset(); setNotice('S1 관찰 원자료 설정을 활성화했습니다. 기존 실행의 고정 설정은 보존됩니다.'); } })}>선택한 S1 설정 활성화</button>
          <button disabled={edit.dirty} onClick={() => void work(async () => { const result = await api<AiTrialV4>(`/settings-s1/${saved.version}/validate-s1`, 'POST', { group: selectedGroup, mode: 'schema' }); if (alive.current) setNotice(`합성 스키마 검증 완료 · 외부 호출 ${result.usage.provider_calls}회 · 실제 판독은 미측정`); })}>합성 스키마 검증 · 외부 호출 없음</button></div>
      </>}
    </fieldset>
    <details><summary>합성 검증 기록</summary>{latest?.trials.map(trial => <article key={trial.trial_id}><p>{new Date(trial.created_at).toLocaleString()} · {view.groups[trial.group]?.codes.join(', ')} · 스키마 통과 · 외부 호출 {trial.usage.provider_calls}회</p><details><summary>합성 응답</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(trial.output, null, 2)}</pre></details></article>)}</details>
  </section>;
}
