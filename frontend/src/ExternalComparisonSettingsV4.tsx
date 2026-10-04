import { useEffect, useRef, useState } from 'react';
import { accessLost, api, ApiError } from './api';
import { useUnsaved } from './Editing';
import type { User } from './types';
import type { FileReferenceV4, ResearchCheckKeyV4, ResearchCheckV4, ResearchInventoryV4, ResearchReferenceV4 } from './externalTypesV4';

const checks: [ResearchCheckKeyV4, string][] = [['numerical_table', '문헌 표·수치·유효 표본수'], ['question_equivalence', '문항 원문·수정 문항 동등성'], ['scale_direction', '척도·점수 방향·산식'], ['missing_policy', '결측 응답 처리'], ['translation_usage', '번안·사용 조건'], ['population_scope', '비교 대상 범위']];
const emptyChecks = () => Object.fromEntries(checks.map(([key]) => [key, { status: 'pending', note: '', evidence_location: '' }])) as Record<ResearchCheckKeyV4, ResearchCheckV4>;

export function ExternalComparisonSettingsV4({ user, onChanged }: { user: User; onChanged?: () => void }) {
  const [inventory, setInventory] = useState<ResearchInventoryV4 | null>(null), [sourceId, setSourceId] = useState('');
  const [draft, setDraft] = useState<{ source: ResearchInventoryV4['sources'][number]; assetHash: string; revision: number } | null>(null);
  const [evaluation, setEvaluation] = useState(emptyChecks), [evidence, setEvidence] = useState<FileReferenceV4[]>([]);
  const [confirmer, setConfirmer] = useState(''), [date, setDate] = useState(''), [reason, setReason] = useState(''), [activationReason, setActivationReason] = useState('');
  const [conditions, setConditions] = useState<{ key: string; value: string }[]>([]), [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const alive = useRef(true), working = useRef(false), sequence = useRef(0);
  useUnsaved(dirty);
  const source = draft?.source, prior = inventory?.documents?.[sourceId], activation = inventory?.activations[sourceId];
  const stale = !!draft && !!inventory && (draft.assetHash !== inventory.asset_hash || draft.revision !== (inventory.confirmations[sourceId]?.revision ?? 0));
  async function reload() {
    const request = ++sequence.current, result = await api<ResearchInventoryV4>('/comparisons-s1/research');
    if (alive.current && request === sequence.current) setInventory(result);
  }
  async function work(action: () => Promise<void>) {
    if (working.current) return; working.current = true; setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (value) { if (alive.current) { setError(value instanceof Error ? value.message : '연구 확인자료 처리에 실패했습니다.'); if (accessLost(value)) { setInventory(null); setDraft(null); } } }
    finally { working.current = false; if (alive.current) setBusy(false); }
  }
  useEffect(() => { alive.current = true; if (user.role === 'admin') void work(reload); return () => { alive.current = false; sequence.current++; }; }, [user.username, user.role]);
  function choose(id: string) {
    if (dirty && !window.confirm('입력 중인 연구 확인 내용을 버리고 출처를 바꿀까요?')) return;
    const selected = inventory?.sources.find(row => row.source_id === id);
    setDraft(selected && inventory ? { source: selected, assetHash: inventory.asset_hash, revision: inventory.confirmations[id]?.revision ?? 0 } : null);
    setSourceId(id); setEvaluation(emptyChecks()); setEvidence([]); setConfirmer(''); setDate(''); setReason(''); setConditions([]); setActivationReason(''); setDirty(false); setNotice('');
  }
  async function upload(file: File) {
    if (file.size > 16 * 1024 * 1024 || !file.size) throw new Error('근거 파일은 0바이트 초과, 16 MiB 이하로 선택하세요.');
    const response = await fetch('/api/comparisons-s1/evidence?filename=' + encodeURIComponent(file.name), { method: 'POST', credentials: 'same-origin', headers: { 'X-KDOG-Request': '1', 'Content-Type': 'application/octet-stream' }, body: file });
    const result = await response.json();
    if (!response.ok) { if (response.status === 401) window.dispatchEvent(new Event('kdog-session-expired')); throw new ApiError(typeof result.detail === 'string' ? result.detail : '근거 업로드에 실패했습니다.', response.status); }
    if (alive.current) { setEvidence(previous => [...previous, result as FileReferenceV4]); setDirty(true); }
  }
  async function save() {
    if (!inventory || !source || !draft) return;
    if (conditions.some(row => !row.value.trim()) || new Set(conditions.map(row => row.key)).size !== conditions.length) throw new Error('대상 조건의 값과 중복 항목을 확인하세요.');
    const document = { source_id: sourceId, source_asset_hash: draft.assetHash, confirmed_by: confirmer.trim(), confirmed_at: date, evidence, scope: { ...source.scope, population_requirements: Object.fromEntries(conditions.map(row => [row.key, row.value.trim()])) }, ...evaluation, reason: reason.trim() };
    const saved = await api<ResearchReferenceV4>('/comparisons-s1/research', 'POST', { expected_revision: draft.revision, document });
    if (alive.current) { setDraft({ ...draft, revision: saved.revision }); setDirty(false); await reload(); setNotice('연구 확인자료를 보존했습니다. 별도 기술 활성화 전에는 출력하지 않습니다.'); onChanged?.(); }
  }
  async function activate(enabled: boolean) {
    if (!inventory) return;
    await api('/comparisons-s1/activation', 'POST', { source_id: sourceId, expected_revision: activation?.revision ?? 0, enabled, confirmation: inventory.confirmations[sourceId] ?? null, reason: activationReason.trim() });
    if (alive.current) { await reload(); setNotice(enabled ? '확인된 범위의 기술 활성화를 기록했습니다. 대상별 조건은 출력 전에 다시 검사합니다.' : '외부 비교를 비활성화했습니다. 해당 출처를 사용한 출력의 제공 조건에 반영됩니다.'); onChanged?.(); }
  }
  if (user.role !== 'admin') return <p>연구 확인자료 등록과 기술 활성화는 운영 관리자 계정에서 수행합니다.</p>;
  return <section aria-label="외부 비교 연구 확인" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h3>외부 비교 연구 확인과 활성화</h3><p>연구자 확인자료를 그대로 기록합니다. 파일 수령이나 관리자 버튼만으로 연구 승인으로 간주하지 않습니다. 실제 확인이 없으면 확인 대기를 유지하세요.</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <button disabled={busy} onClick={() => void work(reload)}>연구 확인·활성화 이력 새로고침</button>
    <fieldset disabled={busy}><legend>연구 확인 출처</legend><label>연구 출처<select aria-label="연구 출처" value={sourceId} onChange={e => choose(e.target.value)}><option value="">출처를 선택하세요</option>{inventory?.sources.map(row => <option key={row.source_id} value={row.source_id}>{row.title}</option>)}</select></label>
      {source && <><p>{source.literature} · DOI {source.doi}</p><p>{source.number_provenance}</p><p>대조할 기록: 평균 {source.reference_values.mean}, 표준편차 {source.reference_values.standard_deviation}, 유효 n={source.reference_values.valid_n}, 전체 n={source.reference_values.total_n}</p><p>{source.scope.domain} · {source.scope.question_ids.join(', ')} · 원척도 {source.scope.scale_minimum}~{source.scope.scale_maximum}</p>
        {stale && <p role="status">작성 기준 이후 연구 확인자료 또는 출처가 변경되었습니다. 현재 입력은 이전 판본 기준으로 보존 시도하며, 최신 자료로 덮어쓰지 않습니다.</p>}<button onClick={() => choose(sourceId)}>최신 확인자료 기준으로 새 작성</button>
        {prior && <details><summary>보존된 최신 연구 확인 {prior.revision}판</summary><p>{prior.confirmed_by} · {prior.confirmed_at} · {prior.reason}</p>{checks.map(([key, title]) => <p key={key}>{title}: {prior[key].status === 'confirmed' ? '확인' : prior[key].status === 'rejected' ? '불허' : '대기'} · {prior[key].note} · {prior[key].evidence_location}</p>)}</details>}
        <label>확인 근거 파일<input type="file" aria-label="확인 근거 파일" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void work(() => upload(file)); }} /></label><p className="fine">파일별 최대 16 MiB. 파일 내용을 자동으로 승인하거나 수식을 실행하지 않습니다.</p>
        {evidence.map((file, index) => <p key={file.ref}>근거 {index + 1} · SHA-256 {file.hash}<button onClick={() => { setEvidence(evidence.filter((_, i) => i !== index)); setDirty(true); }}>이 근거 선택 제거</button></p>)}
        <label>연구 확인자<input aria-label="연구 확인자" value={confirmer} onChange={e => { setConfirmer(e.target.value); setDirty(true); }} /></label><label>연구 확인일<input type="date" aria-label="연구 확인일" value={date} onChange={e => { setDate(e.target.value); setDirty(true); }} /></label>
        {checks.map(([key, title]) => <fieldset key={key}><legend>{title}</legend><label>{title} 상태<select aria-label={`${title} 상태`} value={evaluation[key].status} onChange={e => { setEvaluation({ ...evaluation, [key]: { ...evaluation[key], status: e.target.value as ResearchCheckV4['status'] } }); setDirty(true); }}><option value="pending">확인 대기</option><option value="confirmed">연구 확인 완료</option><option value="rejected">불허·철회</option></select></label><label>{title} 판단 근거<textarea aria-label={`${title} 판단 근거`} value={evaluation[key].note} onChange={e => { setEvaluation({ ...evaluation, [key]: { ...evaluation[key], note: e.target.value } }); setDirty(true); }} /></label><label>{title} 자료 위치<input aria-label={`${title} 자료 위치`} placeholder="문서·표·쪽 또는 회신 위치" value={evaluation[key].evidence_location} onChange={e => { setEvaluation({ ...evaluation, [key]: { ...evaluation[key], evidence_location: e.target.value } }); setDirty(true); }} /></label></fieldset>)}
        <p>추가 대상 조건은 연구 확인 범위에 있는 경우에만 입력합니다. 해당 접수 정보가 없거나 값이 다르면 출력하지 않습니다.</p>{conditions.map((row, index) => <div className="form-grid" key={index}><label>대상 조건 항목<select aria-label={`대상 조건 항목 ${index + 1}`} value={row.key} onChange={e => { setConditions(conditions.map((value, i) => i === index ? { ...value, key: e.target.value } : value)); setDirty(true); }}>{[['dog.breed', '견종'], ['dog.sex', '성별'], ['dog.size', '크기'], ['dog.adoption_route', '입양 경로']].map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>허용한 정확한 값<input aria-label={`대상 조건 값 ${index + 1}`} value={row.value} onChange={e => { setConditions(conditions.map((value, i) => i === index ? { ...value, value: e.target.value } : value)); setDirty(true); }} /></label><button onClick={() => { setConditions(conditions.filter((_, i) => i !== index)); setDirty(true); }}>이 대상 조건 제거</button></div>)}<button onClick={() => { setConditions([...conditions, { key: 'dog.breed', value: '' }]); setDirty(true); }}>대상 조건 추가</button>
        <label>연구 확인 기록 사유<textarea aria-label="연구 확인 기록 사유" value={reason} onChange={e => { setReason(e.target.value); setDirty(true); }} /></label><button disabled={!evidence.length || !confirmer.trim() || !date || !reason.trim() || checks.some(([key]) => !evaluation[key].note.trim() || !evaluation[key].evidence_location.trim())} onClick={() => void work(save)}>새 연구 확인 판본 보존</button>
        <h4>별도의 기술 활성화</h4><p>{activation ? `${activation.revision}판 · ${activation.enabled ? '활성 요청 기록' : '비활성'} · ${activation.reason}` : '활성화 이력이 없습니다.'}</p><label>활성화·철회 사유<textarea aria-label="활성화·철회 사유" value={activationReason} onChange={e => setActivationReason(e.target.value)} /></label><button disabled={!inventory?.confirmations[sourceId] || !activationReason.trim() || dirty || stale} onClick={() => void work(() => activate(true))}>최신 연구 확인 범위 활성화</button><button disabled={!activationReason.trim()} onClick={() => void work(() => activate(false))}>이 출처 비활성화·철회</button>
      </>}
    </fieldset>
  </section>;
}
