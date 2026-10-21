import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { Case } from './types';

type FileRef = { ref: string; hash: string };
type Submission = { reference: FileRef & { submission_id: string }; kind: 'first' | 'correction' | 'revisit'; case_id: string; session_id: string; input_revision: number; evidence: string; submitted_at: string | null; actor: string; recorded_at: string; representative: boolean };
type PairCase = { case_id: string; event_id: string; participant_id: string; dog_name: string; guardian_name: string };
export type PairViewV4 = { pair_id: string; revision: number; status: 'included' | 'excluded'; status_reason: string | null; representative_status: 'confirmed' | 'unconfirmed'; cases: PairCase[]; submissions: Submission[]; actor: string; recorded_at: string };
export type PairInventoryV4 = { case_pair_id: string | null; pairs: PairViewV4[]; counts: Record<string, number> };

const KIND = { first: '최초 제출', correction: '오입력 정정', revisit: '재방문' } as const;
const label = (pair: PairViewV4) => pair.cases.map(item => `${item.dog_name || '이름 없음'}${item.guardian_name ? ` · ${item.guardian_name}` : ''} (${item.event_id})`).join(' / ') || '연결된 대상 없음';
const day = (value: string) => value.slice(0, 10);

// 비교용 참여쌍·대표 설문만 기록한다. 원응답 저장·일괄 등록은 대표를 바꾸지 않는다.
export function ComparisonParticipationV4({ selected, writable }: { selected: Case; writable: boolean }) {
  const [inventory, setInventory] = useState<PairInventoryV4 | null>(null), [target, setTarget] = useState(''), [reason, setReason] = useState('');
  const [submittedAt, setSubmittedAt] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const generation = useRef(0), working = useRef(false);
  const pair = inventory?.pairs.find(item => item.pair_id === inventory.case_pair_id) ?? null;
  async function reload(current = generation.current) {
    const value = await api<PairInventoryV4>(`/comparisons-s1/pairs?case_id=${encodeURIComponent(selected.case_id)}`);
    if (current === generation.current) setInventory(value);
  }
  useEffect(() => {
    const current = ++generation.current;
    setInventory(null); setTarget(''); setReason(''); setSubmittedAt(''); setError(''); setNotice('');
    reload(current).catch(e => { if (current === generation.current) setError(e instanceof Error ? e.message : '참여쌍을 조회하지 못했습니다.'); });
    return () => { generation.current++; };
  }, [selected.case_id, selected.input_revision]);
  async function work(message: string, action: (request_id: string) => Promise<unknown>) {
    if (working.current) return;
    const current = generation.current; working.current = true; setBusy(true); setError(''); setNotice('');
    try { await action(crypto.randomUUID()); if (current === generation.current) { setReason(''); setSubmittedAt(''); setNotice(message); await reload(current); } }
    catch (e) { if (current === generation.current) { setError(e instanceof Error ? e.message : '처리에 실패했습니다.'); await reload(current).catch(() => undefined); } }
    finally { working.current = false; setBusy(false); }
  }
  const link = (destination: PairViewV4 | null) => work(destination ? '참여쌍에 연결했습니다.' : '새 참여쌍을 만들었습니다.', request_id => api('/comparisons-s1/pairs', 'POST', {
    request_id, case_id: selected.case_id, pair_id: destination?.pair_id ?? null, expected_revision: destination?.revision ?? 0,
    expected_case_pair_id: pair?.pair_id ?? null, expected_case_pair_revision: pair?.revision ?? null, reason: reason.trim() }));
  const submit = (kind: keyof typeof KIND) => pair && work(`${KIND[kind]}을 기록했습니다.`, request_id => api(`/comparisons-s1/pairs/${pair.pair_id}/submissions`, 'POST', {
    request_id, expected_revision: pair.revision, kind, case_id: selected.case_id, session_id: selected.selected_session_id,
    expected_input_revision: selected.input_revision, evidence: reason.trim(), submitted_at: submittedAt.trim() || null }));
  const status = (value: 'included' | 'excluded') => pair && work(value === 'excluded' ? '누적 비교에서 제외했습니다.' : '누적 비교에 다시 포함했습니다.', request_id => api(`/comparisons-s1/pairs/${pair.pair_id}/state`, 'POST', {
    request_id, expected_revision: pair.revision, status: value, reason: reason.trim() }));
  const others = inventory?.pairs.filter(item => item.pair_id !== pair?.pair_id) ?? [];
  const chosen = others.find(item => item.pair_id === target) ?? null;
  const representative = pair?.submissions.find(item => item.representative);
  return <section className="panel" aria-label="누적 비교 참여">
    <h3>누적 비교 참여</h3>
    <p className="fine">‘모두 응답·등록 현황’과 별개로, 이 보호자–반려견 참여쌍의 대표 설문 1건만 우리 누적 평균에 포함합니다. 설문 저장·일괄 등록만으로 대표가 바뀌지 않습니다.</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!inventory ? !error && <p>참여쌍 조회 중…</p> : <>
      {pair ? <div>
        <p><strong>{pair.status === 'excluded' ? '누적 비교 제외' : pair.representative_status === 'confirmed' ? '대표 설문 확정' : '대표 설문 미확정'}</strong> · 참여쌍: {label(pair)}</p>
        {pair.status_reason && <p className="fine">제외 사유: {pair.status_reason}</p>}
        {representative ? <p className="fine">대표: {KIND[representative.kind]} · 입력 판본 {representative.input_revision} · {day(representative.submitted_at ?? representative.recorded_at)} · {representative.actor}</p>
          : <p className="fine">근거를 확인해 최초 제출을 기록하기 전에는 누적 평균에 포함하지 않습니다.</p>}
        {pair.submissions.length > 0 && <details><summary>제출 기록 {pair.submissions.length}건</summary><ul>{pair.submissions.map(item =>
          <li key={item.reference.submission_id}>{KIND[item.kind]}{item.representative ? ' (현재 대표)' : ''} · 입력 판본 {item.input_revision} · {day(item.recorded_at)} · {item.actor} · {item.evidence}</li>)}</ul></details>}
      </div> : <p>아직 참여쌍에 연결되지 않았습니다. 같은 보호자의 다른 반려견은 다른 참여쌍입니다. 이름으로 자동 연결하지 않습니다.</p>}
      {writable && <fieldset disabled={busy}>
        <label>근거·사유<input aria-label="참여 근거·사유" value={reason} onChange={e => setReason(e.target.value)} placeholder="예: 현장 제출 확인, 보호자 정정 요청" /></label>
        {pair && pair.status === 'included' && <>
          {pair.representative_status === 'unconfirmed' && <label>실제 과거 제출일(선택)<input aria-label="실제 과거 제출일" value={submittedAt} onChange={e => setSubmittedAt(e.target.value)} placeholder="과거 자료를 등록할 때만 입력" /></label>}
          <div className="toolbar">
            {pair.representative_status === 'unconfirmed' && <button disabled={!reason.trim()} onClick={() => void submit('first')}>현재 설문을 최초 제출로 기록</button>}
            {pair.representative_status === 'confirmed' && <><button disabled={!reason.trim()} onClick={() => void submit('correction')}>오입력 정정으로 대표 교체</button>
              <button disabled={!reason.trim()} onClick={() => void submit('revisit')}>재방문 설문으로 기록</button></>}
          </div></>}
        <div className="toolbar">
          {pair && <button disabled={!reason.trim()} onClick={() => void status(pair.status === 'included' ? 'excluded' : 'included')}>{pair.status === 'included' ? '누적 비교에서 제외' : '누적 비교에 다시 포함'}</button>}
          {!pair && <button disabled={!reason.trim()} onClick={() => void link(null)}>새 참여쌍 만들기</button>}
          {others.length > 0 && <><label>기존 참여쌍<select aria-label="기존 참여쌍" value={target} onChange={e => setTarget(e.target.value)}><option value="">선택하세요</option>
            {others.map(item => <option key={item.pair_id} value={item.pair_id}>{label(item)}</option>)}</select></label>
            <button disabled={!chosen || !reason.trim()} onClick={() => void link(chosen)}>{pair ? '선택한 참여쌍으로 연결 정정' : '선택한 참여쌍에 연결'}</button></>}
        </div>
      </fieldset>}
      <p className="fine">전체 참여쌍 {inventory.counts.pairs ?? 0} · 누적 포함 {inventory.counts.included_confirmed ?? 0} · 대표 미확정 {inventory.counts.representative_unconfirmed ?? 0} · 제외 {inventory.counts.excluded ?? 0} · 미연결 S1 대상 {inventory.counts.unlinked_s1_cases ?? 0}</p>
    </>}
  </section>;
}
