import { useEffect, useRef, useState } from 'react';
import { accessLost, api } from './api';
import { useUnsaved } from './Editing';
import type { CohortSelectionV4, ComparisonSourcesV4 } from './comparisonTypesV4';
import type { ExternalReferenceV4, ExternalSummaryV4 } from './externalTypesV4';

export function ExternalComparisonPickerV4({ target, value, onChange, disabled = false }: { target: CohortSelectionV4 | null; value: ExternalReferenceV4 | null; onChange: (value: ExternalReferenceV4 | null) => void; disabled?: boolean }) {
  const [sources, setSources] = useState<ComparisonSourcesV4 | null>(null), [history, setHistory] = useState<ExternalSummaryV4[]>([]), [ids, setIds] = useState<string[]>([]), [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const sequence = useRef(0), operation = useRef(0), alive = useRef(true), pending = useRef(false), request = useRef({ key: '', id: '' }), changed = useRef(onChange); changed.current = onChange;
  const identity = JSON.stringify(target), context = useRef(identity); context.current = identity;
  useUnsaved(ids.length > 0 || !!reason);
  const rows = target ? history.filter(row => row.target.case_id === target.case_id && row.target.session_id === target.session_id && row.target.expected_revision === target.expected_revision && row.target.input.manifest_hash === target.input.manifest_hash) : [];
  async function reload() {
    const seq = ++sequence.current, scope = context.current;
    const [available, list] = await Promise.all([api<ComparisonSourcesV4>('/comparisons-s1/sources'), api<ExternalSummaryV4[]>('/comparisons-s1/external-snapshots')]);
    if (alive.current && seq === sequence.current && scope === context.current) { setSources(available); setHistory(list); }
  }
  async function work(action: () => Promise<void>) {
    if (pending.current) return; pending.current = true; setBusy(true); setError(''); const scope = context.current, ticket = ++operation.current;
    try { await action(); } catch (e) { if (alive.current && scope === context.current) { setError(e instanceof Error ? e.message : '외부 비교 조건을 확인하지 못했습니다.'); if (accessLost(e)) { setSources(null); setHistory([]); changed.current(null); } } }
    finally { if (ticket === operation.current) { pending.current = false; if (alive.current && scope === context.current) setBusy(false); } }
  }
  useEffect(() => {
    alive.current = true; sequence.current++; operation.current++; pending.current = false; setBusy(false); setIds([]); setReason(''); setHistory([]); changed.current(null); request.current = { key: '', id: '' };
    if (target) void work(reload);
    return () => { alive.current = false; sequence.current++; };
  }, [identity]);
  async function create() {
    if (!target) return;
    const body = { target, source_ids: [...ids].sort(), reason: reason.trim() }, key = JSON.stringify(body), scope = context.current;
    if (request.current.key !== key) request.current = { key, id: crypto.randomUUID() };
    const result = await api<{ reference: ExternalReferenceV4 }>('/comparisons-s1/external-snapshots', 'POST', { ...body, request_id: request.current.id });
    if (!alive.current || scope !== context.current) return;
    changed.current(result.reference); setIds([]); setReason(''); request.current = { key: '', id: '' }; await reload();
  }
  return <fieldset disabled={disabled || busy} aria-label="이 출력의 외부 비교"><legend>이 출력의 외부 비교</legend>
    <p>연구 확인과 기술 활성화가 모두 유효한 출처만 선택합니다. 이 대상의 원문·원척도·응답·필요 프로필을 다시 검사해 고정합니다. 외부 비교 없이도 나머지 결과를 출력할 수 있습니다.</p>
    {!target ? <p>먼저 출력할 원자료·최종본을 선택하세요.</p> : <>
      {error && <p role="alert" className="error">{error}</p>}<button onClick={() => void work(reload)}>외부 비교 조건 새로고침</button><p>선택한 대상·회차의 입력 {target.expected_revision}판 기준입니다.</p>
      <label>이 출력의 외부 비교<select aria-label="이 출력의 외부 비교" value={value?.snapshot_id ?? ''} onChange={e => changed.current(rows.find(row => row.reference.snapshot_id === e.target.value)?.reference ?? null)}><option value="">외부 비교 없음</option>{rows.map(row => <option key={row.reference.snapshot_id} value={row.reference.snapshot_id} disabled={row.status !== 'approved'}>{row.source_titles.join(' / ')} · {new Date(row.recorded_at).toLocaleString()}{row.status !== 'approved' ? ' · 제공 차단' : ''}</option>)}</select></label>
      {value && !rows.some(row => row.reference.hash === value.hash && row.status === 'approved') && <p role="status">선택한 외부 비교를 현재 제공할 수 없습니다. 외부 비교 없음을 선택하거나 조건을 새로 확인하세요.</p>}
      {rows.filter(row => row.status === 'blocked').map(row => <p key={row.reference.snapshot_id}>{row.source_titles.join(' / ')}: {row.reason}</p>)}
      <details><summary>확인된 출처로 새 비교 고정</summary>{sources?.sources.map(row => <label key={row.source_id}><input type="checkbox" aria-label={`${row.title} 외부 비교 포함`} disabled={row.status !== 'conditionally_available'} checked={ids.includes(row.source_id)} onChange={e => setIds(e.target.checked ? [...ids, row.source_id] : ids.filter(id => id !== row.source_id))} />{row.title} · {row.reason}</label>)}
        <label>외부 비교 고정 사유<textarea aria-label="외부 비교 고정 사유" value={reason} onChange={e => setReason(e.target.value)} /></label><button disabled={!ids.length || !reason.trim()} onClick={() => void work(create)}>선택 조건으로 외부 비교 고정</button>
        {request.current.id && <p role="status">응답이 유실되면 같은 선택으로 다시 요청하세요. 동일 요청을 중복 생성하지 않습니다.</p>}
      </details>
    </>}
  </fieldset>;
}
