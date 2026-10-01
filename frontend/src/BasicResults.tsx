import { useEffect, useRef, useState } from 'react';
import { accessLost, api } from './api';
import { mayLeave, useEditBase } from './Editing';
import { Notification } from './Notification';
import type { Evidence, Observation, SheetDocument, SheetReference } from './ScoringTypes';

type Value = { key: string; value: number | null; status: string; reason: string | null; input_codes: string[] };
type Decision = { key: string; label: string | null; status: 'draft' | 'complete' | 'held'; evidence_codes: string[]; evidence: Evidence[]; counter_evidence: Evidence[]; counter_note: string | null; opportunity_note: string; reason: string; rater_id: string; recorded_at: string };
type OwnerItem = { code: string; scene: string; raw_value: number | null; points: number[] | null; used: boolean; reason: string; used_evidence: Evidence[]; excluded_evidence: { evidence: Evidence; reason: string; event_ids: string[] }[] };
type ResultSummary = { result_id: string; revision: number; manifest_ref: string; manifest_hash: string; input: SheetReference };
export type ResultView = { summary: ResultSummary; sheet_changed: boolean; source_changed: boolean; document: {
  revision: number; input: SheetReference; input_document: SheetDocument; rule_version: string; rule_hash: string;
  previous: { revision: number; ref: string; hash: string }[]; decisions: Decision[]; decision_sources: Record<string, string>; evaluation_context: { purpose: string; ai_exposed: boolean; exposures: SheetReference[] };
  calculations: { values: Value[]; descriptions: { key: string; text: string | null; status: string; reason: string | null }[];
    owner: { items: OwnerItem[]; scene_means: Record<string, number[]>; totals: number[]; ratios: number[] | null; evidence_items: number; scenes: number; label: string | null; reason: string };
    directions: { key: string; raw_values: Record<string, number>; negative_sum: number | null; positive_sum: number | null; observed_items: number; status: string; actual_contact: boolean | null }[];
    vocalizations: { code: string; actual_interval_seconds: number | null; audio_available_seconds: number | null; listened_seconds: number | null; cumulative_vocal_seconds: number | null; result: Value }[];
    comparisons: Record<string, Observation[]>; raw_observations: Observation[];
  };
} };
type Edit = { key: string; label: string | null; status: Decision['status']; evidence_codes: string[]; counter_codes: string[]; counter_note: string | null; opportunity_note: string; reason: string };
const labels: Record<string, string[]> = {
  attachment: ['곁에서 안심하는 사이', '가까이 있어도 안심이 어려운 사이', '거리를 두고 지내는 사이', '다가감과 물러섬이 함께 나오는 사이'],
  owner_type: ['허용형', '조율형', '통제형'], entry: ['주저함 · 거리를 벌림', '뚜렷한 치우침 없음', '살피지 않고 들이닥침', '자극에 따라 다름'],
};
const names: Record<string, string> = { attachment: '관계 판정', owner_type: '교육태도', entry: '입장 판단' };
const statuses: Record<string, string> = { calculated: '계산됨', missing: '자료 부족', invalid: '시행 무효', condition_unknown: '조건 미확인', policy_pending: '정책 확인 대기' };

export function BasicResults({ sheetId, input, blocked }: { sheetId: string; input: SheetReference; blocked: boolean }) {
  const [rows, setRows] = useState<ResultSummary[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const path = `/sheets/${sheetId}/basic-results`;
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const values = await api<ResultSummary[]>(path); if (active) { setRows(values); setUnavailable(false); } }
      catch (e) { if (active) { setError(e instanceof Error ? e.message : '기본 결과 조회 실패'); if (accessLost(e)) setUnavailable(true); } }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [path]);
  async function calculate() {
    if (!mayLeave()) return;
    setBusy(true); setError('');
    try { const result = await api<ResultView>(path, 'POST', { input }); setRows(await api<ResultSummary[]>(path)); setSelected(result.summary.result_id); }
    catch (e) { setError(e instanceof Error ? e.message : '계산 실패'); }
    finally { setBusy(false); }
  }
  return <section className="panel" aria-label="기본 계산과 판정"><h2>기본 계산과 판정</h2>
    <Notification message={error} kind="error" onClose={() => setError('')} />
    <p>현재 선택한 시트 r{input.revision}을 계산합니다. 기술값은 내부 기록이며 능력 점수나 성격 확률로 해석하지 않습니다.</p>
    <button disabled={busy || blocked || unavailable} onClick={() => void calculate()}>선택 시트 r{input.revision} 기본 계산</button>
    <label>고정 기본 결과<select aria-label="고정 기본 결과" disabled={busy || unavailable} value={selected} onChange={event => { if (mayLeave()) setSelected(event.target.value); }}><option value="">기본 결과 선택</option>{rows.map(row => <option key={row.result_id} value={row.result_id}>입력 시트 r{row.input.revision} · 판정 r{row.revision} · {row.result_id.slice(0, 8)}</option>)}</select></label>
    {selected && !unavailable && <ResultEditor key={selected} resultId={selected} blocked={blocked} />}
  </section>;
}

function editsOf(view: ResultView): Edit[] {
  return view.document.decisions.map(item => ({ key: item.key, label: item.label, status: item.status, evidence_codes: item.evidence_codes,
    counter_codes: view.document.input_document.sheet.observations.filter(raw => raw.evidence.some(basis => item.counter_evidence.some(other => JSON.stringify(other) === JSON.stringify(basis)))).map(raw => raw.code),
    counter_note: item.counter_note, opportunity_note: item.opportunity_note, reason: item.reason }));
}

function ResultEditor({ resultId, blocked }: { resultId: string; blocked: boolean }) {
  const [latest, setLatest] = useState<ResultView | null>(null);
  const [historical, setHistorical] = useState<ResultView | null>(null);
  const [draft, setDraft] = useState<Edit[]>([]);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const edit = useEditBase(latest);
  const clean = useRef(true); clean.current = !edit.dirty;
  const path = `/basic-results/${resultId}`;
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const result = await api<ResultView>(path); if (active) { setLatest(result); setUnavailable(false); if (clean.current) setDraft(editsOf(result)); } }
      catch (e) { if (active) { setError(e instanceof Error ? e.message : '기본 결과 조회 실패'); if (accessLost(e)) setUnavailable(true); } }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [path]);
  const view = historical ?? edit.view;
  if (!view || unavailable) return <p role="status">{error || '고정 기본 결과 조회 중…'}</p>;
  const doc = view.document, calc = doc.calculations;
  const writable = !historical && doc.input_document.sheet.rater_kind === 'human';
  function change(index: number, patch: Partial<Edit>) { edit.change(); setDraft(previous => previous.map((item, position) => position === index ? { ...item, ...patch } : item)); }
  async function save() {
    setBusy(true); setError('');
    try { const result = await api<ResultView>(path + '/decisions', 'PUT', { expected_revision: doc.revision, reason, decisions: draft }); setLatest(result); setDraft(editsOf(result)); setReason(''); edit.reset(); }
    catch (e) { setError(e instanceof Error ? e.message : '판정 저장 실패'); }
    finally { setBusy(false); }
  }
  return <div aria-label="고정 기본 결과 내용">
    <Notification message={error} kind="error" onClose={() => setError('')} />
    <p role="status">입력 시트 r{doc.input.revision} · 판정 r{doc.revision} · {doc.rule_version}</p>
    <p>판정 기록 목적 {doc.evaluation_context.purpose} · {doc.evaluation_context.ai_exposed ? 'AI 결과 노출됨' : 'AI 결과 미노출'} · 다른 결과 노출 {doc.evaluation_context.exposures.length}개</p>
    {(view.sheet_changed || view.source_changed) && <p role="status">현재 원시트/촬영 입력이 변경되었습니다. 이 기본 결과는 표시된 고정 입력을 보존합니다.</p>}
    {edit.dirty && latest?.document.revision !== doc.revision && <p role="status">다른 판정 변경이 저장되었습니다. 미저장 입력은 유지하며 저장 시 충돌을 확인합니다.</p>}
    <label>기본 판정 보존본<select aria-label="기본 판정 보존본" disabled={busy || edit.dirty} value={historical?.document.revision ?? ''} onChange={event => {
      const number = event.target.value; if (!number) { setHistorical(null); return; }
      setBusy(true); void api<ResultView>(path + `/revisions/${number}`).then(setHistorical).catch(e => setError(String(e))).finally(() => setBusy(false));
    }}><option value="">현재 판정 r{latest?.document.revision}</option>{latest?.document.previous.map(item => <option key={item.ref} value={item.revision}>보존 판정 r{item.revision}</option>)}</select></label>
    <div className="table-wrap"><table><thead><tr><th>기술값</th><th>값 / 상태</th><th>조건·원항목·사유</th></tr></thead><tbody>{calc.values.map(value => <tr key={value.key}><td>{value.key}</td><td>{value.value ?? '빈값'} · {statuses[value.status]}</td><td>{value.input_codes.join(' · ')} · {value.reason}</td></tr>)}</tbody></table></div>
    {calc.descriptions.map(item => <p key={item.key}>{item.key}: {item.text ?? statuses[item.status]} · {item.reason}</p>)}
    <details><summary>방향·원값·접촉 기록</summary><ul>{calc.directions.map(item => <li key={item.key}>{item.key} · −합계 {item.negative_sum ?? '빈값'} / +합계 {item.positive_sum ?? '빈값'} · 관찰{item.observed_items}항목 · {item.status} · 실제 접촉 {item.actual_contact === null ? '미확인' : item.actual_contact ? '있음' : '없음'}<pre>{JSON.stringify(item.raw_values, null, 2)}</pre></li>)}</ul></details>
    <details><summary>발성 실제 분모·음성·청취량</summary><ul>{calc.vocalizations.map(item => <li key={item.code}>{item.code} · 실제 구간 {item.actual_interval_seconds ?? '미확인'}초 · 음성 사용 가능 {item.audio_available_seconds ?? '미확인'}초 · 청취 {item.listened_seconds ?? '미확인'}초 · 누적 발성 {item.cumulative_vocal_seconds ?? '미확인'}초 · {statuses[item.result.status]}</li>)}</ul></details>
    <details><summary>교육태도 사용·제외 근거</summary><p>{calc.owner.reason} · 근거{calc.owner.evidence_items}항목·{calc.owner.scenes}장면 · 비율 {calc.owner.ratios?.map(value => `${(value * 100).toFixed(2)}%`).join(' / ') ?? '빈값'} (허용/조율/통제)</p>
      <pre>{JSON.stringify({ scene_means: calc.owner.scene_means, totals: calc.owner.totals }, null, 2)}</pre>
      <ul>{calc.owner.items.map(item => <li key={item.code}>{item.code} · {item.scene} · 원값 {item.raw_value ?? '빈값'} · 배점 {item.points?.join('/') ?? '없음'} · {item.used ? '사용' : '제외'} · {item.reason}<ul>{item.excluded_evidence.map((basis, index) => <li key={index}>{basis.evidence.start_seconds}~{basis.evidence.end_seconds}초 · {basis.reason} · {basis.event_ids.join(' · ')}</li>)}</ul></li>)}</ul>
    </details>
    <details><summary>물건·몸·꼬리·입장 원자료 비교</summary>{Object.entries(calc.comparisons).map(([key, rows]) => <div key={key}><strong>{key}</strong><ul>{rows.map(item => <li key={item.code}>{item.code} · {item.value ?? item.reason} · {item.status} · {item.validity} · {item.evidence.map(basis => `${basis.window_id} ${basis.start_seconds}~${basis.end_seconds}초`).join(' / ')}</li>)}</ul></div>)}</details>
    <details><summary>계산에 고정한 전체 원관찰·실제 근거</summary><ul>{calc.raw_observations.map(item => <li key={item.code}>{item.code} · {item.value ?? item.reason} · {item.status} · {item.validity} · 기회 {item.opportunity}<ul>{item.evidence.map((basis, index) => <li key={index}>{basis.video_id} · {basis.window_id} · {basis.start_seconds}~{basis.end_seconds}초 · 확인{basis.observed_seconds}초 · {basis.note}</li>)}</ul></li>)}</ul></details>
    <p>Q06 완료 조건 확인 대기 · 관계 완료에는 실제 분리·재회와 보호자 접근·몸 상태의 다중 영상 근거가 필요합니다. 보류는 다섯 번째 유형이 아닙니다.</p>
    <fieldset disabled={busy || blocked || !writable}>{(historical ? editsOf(historical) : draft).map((item, index) => <article className="scoring-item" key={item.key} aria-label={`${names[item.key]} 기록`}><h3>{names[item.key]}</h3>
      <p>{doc.decision_sources[item.key] === 'automatic' ? '자동 계산 초안 · 평가자 검토 필요' : '평가자 기록'} · {doc.decisions[index].rater_id} · {doc.decisions[index].recorded_at}</p>
      <label>판정 상태<select aria-label={`${names[item.key]} 상태`} value={item.status} onChange={event => change(index, { status: event.target.value as Edit['status'], ...(event.target.value === 'held' ? { label: null } : {}) })}><option value="draft">미완료 초안</option><option value="complete">완료된 유형</option><option value="held">완료된 판정보류</option></select></label>
      <label>기본 유형<select aria-label={`${names[item.key]} 유형`} disabled={item.status === 'held'} value={item.label ?? ''} onChange={event => change(index, { label: event.target.value || null })}><option value="">유형 미선택</option>{labels[item.key].map(label => <option key={label}>{label}</option>)}</select></label>
      <details><summary>{names[item.key]} 근거·반대 근거 선택</summary><p>고정 시트에서 관찰한 항목과 실제 영상 근거를 선택하세요. 반대 근거도 남기며 모든 실제 근거 시각을 보존합니다.</p>{doc.input_document.sheet.observations.filter(raw => raw.status === 'observed').map(raw => <div className="row" key={raw.code}><label className="check"><input type="checkbox" checked={item.evidence_codes.includes(raw.code)} onChange={event => change(index, { evidence_codes: event.target.checked ? [...item.evidence_codes, raw.code] : item.evidence_codes.filter(code => code !== raw.code), counter_codes: item.counter_codes.filter(code => code !== raw.code) })} />{raw.code} · {raw.value} · {raw.validity}</label><label className="check"><input type="checkbox" disabled={!item.evidence_codes.includes(raw.code)} checked={item.counter_codes.includes(raw.code)} onChange={event => change(index, { counter_codes: event.target.checked ? [...item.counter_codes, raw.code] : item.counter_codes.filter(code => code !== raw.code) })} />{raw.code} 반대 근거</label></div>)}</details>
      <label>관찰 기회·미실시 영향<textarea aria-label={`${names[item.key]} 관찰 기회`} value={item.opportunity_note} onChange={event => change(index, { opportunity_note: event.target.value })} /></label>
      <label>반대 근거 검토·없는 사유<textarea aria-label={`${names[item.key]} 반대 근거 검토`} value={item.counter_note ?? ''} onChange={event => change(index, { counter_note: event.target.value || null })} /></label>
      <label>판정·보류 사유<textarea aria-label={`${names[item.key]} 사유`} value={item.reason} onChange={event => change(index, { reason: event.target.value })} /></label>
    </article>)}<label>판정 수정 사유<input aria-label="판정 수정 사유" value={reason} onChange={event => { edit.change(); setReason(event.target.value); }} /></label></fieldset>
    {writable && <div className="toolbar"><button disabled={busy || blocked || !edit.dirty || !reason.trim()} onClick={() => void save()}>기본 판정 저장</button><button disabled={busy || !edit.dirty} onClick={() => { if (edit.discard() && latest) { setDraft(editsOf(latest)); setReason(''); } }}>미저장 판정 버리고 최신 조회</button></div>}
    <details><summary>기본 결과의 고정 참조·해시</summary><pre>{JSON.stringify({ result: view.summary, input: doc.input, rule_hash: doc.rule_hash }, null, 2)}</pre></details>
  </div>;
}
