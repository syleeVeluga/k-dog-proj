import { useEffect, useRef, useState } from 'react';
import { accessLost, api, ApiError } from './api';
import { useUnsaved } from './Editing';
import type { User } from './types';
import type { DefinitionInventoryV4, DefinitionReferenceV4, ExternalValuesV4, FileReferenceV4 } from './externalTypesV4';

const numbers: [keyof ExternalValuesV4, string][] = [['mean', '외부 평균'], ['standard_deviation', '외부 표준편차'], ['valid_n', '외부 유효 표본 n'], ['total_n', '외부 전체 표본 n']];
const blank = () => ({ mean: '', standard_deviation: '', valid_n: '', total_n: '' });

export function ExternalComparisonSettingsV4({ user, onChanged }: { user: User; onChanged?: () => void }) {
  const [inventory, setInventory] = useState<DefinitionInventoryV4 | null>(null), [sourceId, setSourceId] = useState('');
  const [draft, setDraft] = useState<{ source: DefinitionInventoryV4['sources'][number]; assetHash: string; revision: number } | null>(null);
  const [values, setValues] = useState(blank), [evidence, setEvidence] = useState<FileReferenceV4[]>([]);
  const [population, setPopulation] = useState(''), [provenance, setProvenance] = useState(''), [reason, setReason] = useState(''), [enabled, setEnabled] = useState(true);
  const [conditions, setConditions] = useState<{ key: string; value: string }[]>([]), [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const alive = useRef(true), working = useRef(false), sequence = useRef(0);
  useUnsaved(dirty);
  const source = draft?.source, prior = inventory?.documents[sourceId];
  const current = inventory?.references[sourceId];
  const currentRevision = current && 'definition_id' in current ? current.revision : 0;
  const stale = !!draft && !!inventory && (draft.assetHash !== inventory.asset_hash || draft.revision !== currentRevision);
  async function reload() {
    const request = ++sequence.current, result = await api<DefinitionInventoryV4>('/comparisons-s1/definitions');
    if (alive.current && request === sequence.current) setInventory(result);
  }
  async function work(action: () => Promise<void>) {
    if (working.current) return; working.current = true; setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (value) { if (alive.current) { setError(value instanceof Error ? value.message : '기준 정의 처리에 실패했습니다.'); if (accessLost(value)) { setInventory(null); setDraft(null); } } }
    finally { working.current = false; if (alive.current) setBusy(false); }
  }
  useEffect(() => { alive.current = true; void work(reload); return () => { alive.current = false; sequence.current++; }; }, [user.username]);
  function choose(id: string) {
    if (dirty && !window.confirm('입력 중인 기준 정의를 버리고 출처를 바꿀까요?')) return;
    const selected = inventory?.sources.find(row => row.source_id === id), stored = inventory?.documents[id], pointer = inventory?.references[id];
    setDraft(selected && inventory ? { source: selected, assetHash: inventory.asset_hash, revision: pointer && 'definition_id' in pointer ? pointer.revision : 0 } : null);
    setSourceId(id); setValues(stored && 'values' in stored ? Object.fromEntries(numbers.map(([key]) => [key, String(stored.values[key])])) as ReturnType<typeof blank> : blank());
    setEvidence(stored?.evidence ?? []); setPopulation(stored && 'values' in stored ? stored.population_scope : '');
    setProvenance(stored && 'number_provenance' in stored ? stored.number_provenance : ''); setReason('');
    setEnabled(stored && 'enabled' in stored ? stored.enabled : true);
    setConditions(Object.entries(stored?.scope.population_requirements ?? {}).map(([key, value]) => ({ key, value })));
    setDirty(false); setNotice('');
  }
  async function upload(file: File) {
    if (file.size > 16 * 1024 * 1024 || !file.size) throw new Error('근거 파일은 0바이트 초과, 16 MiB 이하로 선택하세요.');
    const response = await fetch('/api/comparisons-s1/evidence?filename=' + encodeURIComponent(file.name), { method: 'POST', credentials: 'same-origin', headers: { 'X-KDOG-Request': '1', 'Content-Type': 'application/octet-stream' }, body: file });
    const result = await response.json();
    if (!response.ok) { if (response.status === 401) window.dispatchEvent(new Event('kdog-session-expired')); throw new ApiError(typeof result.detail === 'string' ? result.detail : '근거 업로드에 실패했습니다.', response.status); }
    if (alive.current) { setEvidence(previous => [...previous, result as FileReferenceV4]); setDirty(true); }
  }
  async function save() {
    if (!source || !draft) return;
    if (conditions.some(row => !row.key.trim() || !row.value.trim()) || new Set(conditions.map(row => row.key.trim())).size !== conditions.length) throw new Error('대상 조건의 값과 중복 항목을 확인하세요.');
    const document = { source_id: sourceId, source_asset_hash: draft.assetHash, evidence, scope: { ...source.scope, population_requirements: Object.fromEntries(conditions.map(row => [row.key.trim(), row.value.trim()])) }, values: Object.fromEntries(numbers.map(([key]) => [key, Number(values[key])])), population_scope: population.trim(), number_provenance: provenance.trim(), enabled, reason: reason.trim() };
    const saved = await api<DefinitionReferenceV4>('/comparisons-s1/definitions', 'POST', { expected_revision: draft.revision, document });
    if (alive.current) { setDraft({ ...draft, revision: saved.revision }); setDirty(false); await reload(); setNotice(enabled ? '기준 정의를 저장하고 적용했습니다.' : '새 계산에서 사용 중단했습니다. 기존 발급 파일은 보존됩니다.'); onChanged?.(); }
  }
  return <section aria-label="외부 비교 기준 정의" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h3>외부 비교 기준 정의</h3><p>실제 수치·문항·원척도·산식·대상 조건을 입력합니다. 저장한 기준은 바로 적용하며 자료가 없거나 조건이 다르면 계산하지 않습니다.</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <button disabled={busy} onClick={() => void work(reload)}>기준 정의 새로고침</button>
    <fieldset disabled={busy}><legend>기준 출처</legend><label>연구 출처<select aria-label="연구 출처" value={sourceId} onChange={e => choose(e.target.value)}><option value="">출처를 선택하세요</option>{inventory?.sources.map(row => <option key={row.source_id} value={row.source_id}>{row.title}</option>)}</select></label>
      {source && <><p>{source.literature} · DOI {source.doi}</p><p>{source.scope.domain} · {source.scope.question_ids.join(', ')} · 원척도 {source.scope.scale_minimum}~{source.scope.scale_maximum} · {source.scope.direction} · {source.scope.aggregation} · {source.scope.missing_policy}</p>
        {inventory?.document_errors[sourceId] && <p role="status">{inventory.document_errors[sourceId]}</p>}
        {stale && <p role="status">작성 이후 기준이 변경됐습니다. 입력을 보존하며 새로 불러오기 전에는 최신 판본을 덮어쓰지 않습니다.</p>}<button onClick={() => choose(sourceId)}>최신 기준으로 새 작성</button>
        {prior && <details><summary>보존된 기준 출처 {prior.revision}판</summary><p>{prior.actor} · {prior.recorded_at} · {prior.reason}</p></details>}
        <div className="form-grid">{numbers.map(([key, title]) => <label key={key}>{title}<input aria-label={title} type="number" step={key.endsWith('_n') ? '1' : 'any'} value={values[key]} onChange={e => { setValues({ ...values, [key]: e.target.value }); setDirty(true); }} /></label>)}</div>
        <label>비교 대상 범위<textarea aria-label="비교 대상 범위" value={population} onChange={e => { setPopulation(e.target.value); setDirty(true); }} /></label><label>수치 출처·표 위치<textarea aria-label="수치 출처·표 위치" value={provenance} onChange={e => { setProvenance(e.target.value); setDirty(true); }} /></label>
        <label>기준 근거 파일<input type="file" aria-label="기준 근거 파일" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void work(() => upload(file)); }} /></label>
        {evidence.map((file, index) => <p key={file.ref}>근거 {index + 1}<button onClick={() => { setEvidence(evidence.filter((_, i) => i !== index)); setDirty(true); }}>이 근거 선택 제거</button></p>)}
        <p>접수 정보의 실제 값과 일치해야 하는 추가 대상 조건을 입력합니다.</p>{conditions.map((row, index) => <div className="form-grid" key={index}><label>대상 조건 항목<input aria-label={`대상 조건 항목 ${index + 1}`} placeholder="dog.sex" value={row.key} onChange={e => { setConditions(conditions.map((value, i) => i === index ? { ...value, key: e.target.value } : value)); setDirty(true); }} /></label><label>대상 조건 값<input aria-label={`대상 조건 값 ${index + 1}`} value={row.value} onChange={e => { setConditions(conditions.map((value, i) => i === index ? { ...value, value: e.target.value } : value)); setDirty(true); }} /></label><button onClick={() => { setConditions(conditions.filter((_, i) => i !== index)); setDirty(true); }}>조건 제거</button></div>)}
        <button onClick={() => { setConditions([...conditions, { key: '', value: '' }]); setDirty(true); }}>대상 조건 추가</button>
        <label className="check"><input type="checkbox" checked={enabled} onChange={e => { setEnabled(e.target.checked); setDirty(true); }} />새 계산에 사용</label>
        <label>기준 변경 기록<input aria-label="기준 변경 기록" value={reason} onChange={e => { setReason(e.target.value); setDirty(true); }} /></label>
        <button disabled={!evidence.length || !population.trim() || !provenance.trim() || !reason.trim() || numbers.some(([key]) => !values[key].trim())} onClick={() => void work(save)}>기준 정의 저장·적용</button>
      </>}
    </fieldset>
  </section>;
}
