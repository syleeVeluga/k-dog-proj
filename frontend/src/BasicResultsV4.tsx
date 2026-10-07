import type { AttachmentAssessmentV4 } from './attachmentTypesV4';
import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { mayLeave, useUnsaved } from './Editing';
import type { EvidenceV4, ObservationV4, SheetDocumentV4, SheetReferenceV4 } from './ScoringTypesV4';

type DecisionKey = 'owner_type' | 'attachment_type';
type Decision = { key: DecisionKey; label: string | null; status: 'draft' | 'complete' | 'held'; evidence_codes: string[]; counter_codes: string[]; evidence: EvidenceV4[]; counter_evidence: EvidenceV4[]; counter_note: string | null; reason: string };
type Edit = Pick<Decision, 'key' | 'label' | 'status' | 'evidence_codes' | 'counter_note' | 'reason'> & { counter_codes: string[] };
type Metric = { key: string; value: number | string | null; status: string; reason: string; inputs: ObservationV4[]; used_codes: string[]; excluded: Record<string, string>; numerator: number | null; denominator: number | null; caution: boolean; internal_only: boolean };
type Summary = { result_id: string; revision: number; manifest_ref: string; manifest_hash: string; input: SheetReferenceV4 };
export type BasicResultViewV4 = { summary: Summary; sheet_changed: boolean; source_changed: boolean; document: {
  revision: number; actor: string; recorded_at: string; change_reason: string; attachment_assessment?: AttachmentAssessmentV4; input: SheetReferenceV4; input_document: SheetDocumentV4;
  conditions: { same_object: boolean | null; same_object_reason: string | null }; rule_version: string; rule_hash: string;
  evaluation_context: { purpose: string; ai_exposed: boolean; exposures: SheetReferenceV4[] };
  decisions: Decision[]; automatic_decisions: Decision[]; manual_decisions: Decision[]; decision_sources: Record<DecisionKey, string>;
  previous: { revision: number; ref: string; hash: string }[];
  calculations: { metrics: Metric[]; policy_pending_codes: string[]; safe_base: { status: 'confirmed_sequence' | 'unconfirmed'; reasons: string[]; event_ids: string[]; reference_seconds: number[] };
    owner: { label: string | null; reason: string; valid_items: number; valid_scenes: number; ratios: number[] | null; totals: number[];
      scene_means: Record<string, number[]>; items: { code: string; value: number | null; scene: string; points: number[] | null; used: boolean; reason: string }[] } };
} };
const names: Record<DecisionKey, string> = { owner_type: '보호자 교육태도', attachment_type: '반려견·보호자 관계' };
const choices: Record<DecisionKey, string[]> = { owner_type: ['허용형', '조율형', '통제형'], attachment_type: ['곁에서 안심하는 사이', '가까이 있어도 안심이 어려운 사이', '거리를 두고 지내는 사이', '다가감과 물러섬이 함께 나오는 사이'] };
const states: Record<string, string> = { calculated: '계산됨', missing: '근거 부족', invalid: '조건 무효', condition_unknown: '조건 확인 필요', policy_pending: '규칙 확인 대기', held: '판정보류', draft: '작성 중', complete: '완료' };
const sequenceReasons: Record<string, string> = { actual_approach_contact_exploration_sequence_missing: '실제 접근·접촉·탐색 재개 순서를 기록하지 않음', sequence_event_missing: '순서에 연결된 실제 사건이 부족함', sequence_event_kind_or_synchronization_unconfirmed: '사건 종류 또는 카메라 동기화 미확인', actual_sequence_order_not_established: '확정된 실제 접근·접촉·탐색 재개 순서가 성립하지 않음' };
const valueText = (value: number | string | null) => value === null ? '—' : typeof value === 'number' ? String(Number(value.toFixed(4))) : value;
const errorText = (error: unknown) => error instanceof Error ? error.message : '기본 결과를 확인할 수 없습니다.';

export function BasicResultsV4({ sheetId, input, blocked }: { sheetId: string; input: SheetReferenceV4; blocked: boolean }) {
  const [rows, setRows] = useState<Summary[]>([]), [selected, setSelected] = useState('');
  const [sameObject, setSameObject] = useState(''), [basis, setBasis] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const path = `/score-sheets-s1/${sheetId}/basic-results-s1`;
  const reload = async () => setRows(await api<Summary[]>(path));
  useEffect(() => { let active = true; api<Summary[]>(path).then(values => { if (active) setRows(values); }).catch(e => { if (active) setError(errorText(e)); }); return () => { active = false; }; }, [path]);
  async function calculate() {
    if (busy || !mayLeave()) return;
    setBusy(true); setError('');
    try {
      const result = await api<BasicResultViewV4>(path, 'POST', { input, same_object: sameObject === '' ? null : sameObject === 'yes', same_object_reason: basis.trim() || null });
      await reload(); setSelected(result.summary.result_id);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <section className="panel basic-s1" aria-label="S1 기본 결과">
    <h3>S1 계산과 기본 판정</h3><p>제출 원자료 {input.revision}판을 고정해 계산합니다. 수동 선택을 완료해도 자동 계산과 원자료는 보존됩니다.</p>
    <fieldset disabled={blocked || busy}><div className="form-grid"><label>입장·퇴장 같은 물건 확인<select value={sameObject} onChange={e => setSameObject(e.target.value)}><option value="">미확인</option><option value="yes">같은 물건</option><option value="no">다른 물건</option></select></label>
      <label>같은 물건 확인 근거<input value={basis} onChange={e => setBasis(e.target.value)} maxLength={2000} /></label></div>
      <button disabled={sameObject !== '' && !basis.trim()} onClick={() => void calculate()}>제출 원자료로 계산</button></fieldset>
    {blocked && <p>원자료를 저장·제출한 뒤 계산할 수 있습니다.</p>}{error && <p role="alert" className="error">{error}</p>}
    <div className="toolbar"><label>기본 결과 선택<select value={selected} onChange={e => { if (mayLeave()) setSelected(e.target.value); }}><option value="">결과를 선택하세요</option>{rows.map(row => <option key={row.result_id} value={row.result_id}>원자료 {row.input.revision}판 · 결과 {row.revision}판 · {row.result_id.slice(0, 8)}</option>)}</select></label><button onClick={() => void reload().catch(e => setError(errorText(e)))}>결과 목록 새로고침</button></div>
    {selected && <ResultEditor key={selected} resultId={selected} blocked={blocked || busy} />}
  </section>;
}

function editsOf(view: BasicResultViewV4): Edit[] {
  return view.document.decisions.map(applied => {
    const value = view.document.manual_decisions.find(item => item.key === applied.key) ?? applied;
    return { key: value.key, label: value.label, status: value.status, evidence_codes: [...value.evidence_codes], counter_codes: [...value.counter_codes], counter_note: value.counter_note, reason: value.reason };
  });
}

function ResultEditor({ resultId, blocked }: { resultId: string; blocked: boolean }) {
  const path = `/basic-results-s1/${resultId}`;
  const [view, setView] = useState<BasicResultViewV4 | null>(null), [edits, setEdits] = useState<Edit[]>([]);
  const [reason, setReason] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [historical, setHistorical] = useState(false);
  const sequence = useRef(0), pending = useRef(false);
  useUnsaved(dirty);
  function adopt(next: BasicResultViewV4, old = false) { setView(next); setEdits(editsOf(next)); setReason(''); setDirty(false); setHistorical(old); setError(''); }
  useEffect(() => {
    const current = ++sequence.current; pending.current = true; setBusy(true);
    api<BasicResultViewV4>(path).then(next => { if (current === sequence.current) adopt(next); }).catch(e => { if (current === sequence.current) setError(errorText(e)); })
      .finally(() => { if (current === sequence.current) { pending.current = false; setBusy(false); } });
    return () => { sequence.current++; pending.current = false; };
  }, [path]);
  async function load(revision?: number) {
    if (pending.current || !mayLeave()) return;
    const current = ++sequence.current; pending.current = true; setBusy(true); setError('');
    try { const next = await api<BasicResultViewV4>(revision ? `${path}/revisions/${revision}` : path); if (current === sequence.current) adopt(next, revision !== undefined); }
    catch (e) { if (current === sequence.current) setError(errorText(e)); }
    finally { if (current === sequence.current) { pending.current = false; setBusy(false); } }
  }
  function change(index: number, value: Partial<Edit>) { setDirty(true); setEdits(edits.map((edit, i) => i === index ? { ...edit, ...value } : edit)); }
  async function save() {
    if (!view || pending.current) return;
    const current = ++sequence.current; pending.current = true; setBusy(true); setError('');
    try { const next = await api<BasicResultViewV4>(`${path}/judgements`, 'PUT', { expected_revision: view.document.revision, reason, decisions: edits }); if (current === sequence.current) adopt(next); }
    catch (e) { if (current === sequence.current) setError(errorText(e)); }
    finally { if (current === sequence.current) { pending.current = false; setBusy(false); } }
  }
  if (!view) return <p role="status">{error || '기본 결과 조회 중'}</p>;
  const doc = view.document, owner = doc.calculations.owner;
  const readonly = blocked || busy || historical || doc.input_document.sheet.rater_kind !== 'human';
  return <div>
    <h4>결과 {doc.revision}판 · 원자료 {doc.input.revision}판</h4>
    <p>{doc.input_document.rater_name} · {doc.evaluation_context.purpose} · AI 결과 열람 {doc.evaluation_context.ai_exposed ? '있음' : '없음'}</p>
    {(view.sheet_changed || view.source_changed) && <p role="status">현재 입력 또는 시트가 변경되었습니다. 이 결과는 표시한 원자료 판본의 계산을 유지합니다.</p>}
    <div className="toolbar"><button disabled={busy} onClick={() => void load()}>최신 기본 결과 불러오기</button>{doc.previous.map(previous => <button key={previous.revision} disabled={busy} onClick={() => void load(previous.revision)}>보존 결과 {previous.revision}판</button>)}</div>
    {historical && <p role="status">보존한 결과를 읽는 중입니다. 수정하려면 최신 기본 결과를 불러오세요.</p>}
    <h4>보호자 배점과 관찰 기회</h4><p>{owner.label ?? '판정보류'} · {owner.valid_items}항목 / {owner.valid_scenes}장면 · {owner.reason}</p>
    <p>허용 / 조율 / 통제: {owner.ratios ? owner.ratios.map(ratio => `${(ratio * 100).toFixed(1)}%`).join(' / ') : '근거 부족으로 비율 보류'}</p>
    <div className="table-wrap"><table><thead><tr><th>항목 / 장면</th><th>원값</th><th>허용·조율·통제 배점</th><th>사용 / 제외 근거</th></tr></thead><tbody>{owner.items.map(item => <tr key={item.code}><td>{item.code} / {item.scene}</td><td>{valueText(item.value)}</td><td>{item.points?.join(' / ') ?? '—'}</td><td>{item.used ? '사용' : '제외'} · {item.reason}</td></tr>)}</tbody></table></div>
    <details><summary>장면 평균·합계와 고정 출처</summary><p>장면 합계: {owner.totals.map(valueText).join(' / ')}</p>{Object.entries(owner.scene_means).map(([scene, means]) => <p key={scene}>{scene}: {means.map(valueText).join(' / ')}</p>)}<p className="fine">원자료 {doc.input.ref} · SHA256 {doc.input.hash}<br />계산 {doc.rule_version} · SHA256 {doc.rule_hash}<br />작성 {doc.actor} · {doc.recorded_at} · {doc.change_reason}</p></details>
    <h4>계산·원값·보류 사유</h4>{doc.calculations.metrics.map(metric => <details key={metric.key}><summary>{metric.key}: {valueText(metric.value)} · {states[metric.status] ?? metric.status}{metric.caution ? ' · 주의' : ''}{metric.internal_only ? ' · 내부 보조값' : ''}</summary><p>{metric.reason}</p><p>분자 {valueText(metric.numerator)} / 분모 {valueText(metric.denominator)} · 사용 {metric.used_codes.join(', ') || '없음'}</p>{metric.inputs.map(item => <p key={item.code}>{item.code}: {valueText(item.value)} · {item.status}{metric.excluded[item.code] && ` · 제외: ${metric.excluded[item.code]}`}</p>)}</details>)}
    <p>안전기지 실제 순서: {doc.calculations.safe_base.status === 'confirmed_sequence' ? '접근·접촉·탐색 재개 순서 확인' : '확인 필요'}{doc.calculations.safe_base.reasons.map(reason => ` · ${sequenceReasons[reason] ?? reason}`)}{doc.calculations.safe_base.reference_seconds.length > 0 && ` · 기준 영상 ${doc.calculations.safe_base.reference_seconds.map(value => `${value}초`).join(' → ')}`}</p>
    <p className="fine">정책 확인 대기: {doc.calculations.policy_pending_codes.join(', ')}. 개21 전체30초 자동 집계·보5 복수 사건 종합은 규칙 확인 대기입니다. AI 애착 판단은 별도 실행 결과와 보류 사유를 확인하세요.</p>
    <h4>기본 유형 선택</h4><p>작성 중 선택은 자동 초안을 유지합니다. 완료 또는 판정보류로 저장하면 수동 선택을 적용합니다.</p>
    <fieldset disabled={readonly}>{edits.map((edit, index) => {
      const automatic = doc.automatic_decisions.find(item => item.key === edit.key)!;
      const applied = doc.decisions.find(item => item.key === edit.key)!;
      return <section className="panel" key={edit.key}><h4>{names[edit.key]}</h4><p>자동: {automatic.label ?? '판정보류'} · 적용: {applied.label ?? '판정보류'} ({doc.decision_sources[edit.key]})</p>
        <div className="form-grid"><label>{names[edit.key]} 선택<select value={edit.label ?? ''} onChange={e => change(index, { label: e.target.value || null, status: e.target.value ? 'draft' : 'held' })}><option value="">판정보류</option>{choices[edit.key].map(label => <option key={label}>{label}</option>)}</select></label>
          <label>{names[edit.key]} 상태<select value={edit.status} onChange={e => change(index, { status: e.target.value as Edit['status'], ...(e.target.value === 'held' ? { label: null } : {}) })}><option value="draft" disabled={!edit.label}>작성 중</option><option value="complete" disabled={!edit.label}>완료</option><option value="held">판정보류</option></select></label></div>
        <details><summary>{names[edit.key]} 근거·반대 근거 선택</summary>{doc.input_document.sheet.observations.filter(item => item.status === 'observed' && ['valid', 'caution'].includes(item.validity)).map(item => <div className="toolbar" key={item.code}><span>{item.code}: {valueText(item.value)}</span><label className="check"><input type="checkbox" checked={edit.evidence_codes.includes(item.code)} onChange={e => change(index, { evidence_codes: e.target.checked ? [...edit.evidence_codes, item.code] : edit.evidence_codes.filter(code => code !== item.code), counter_codes: edit.counter_codes.filter(code => code !== item.code) })} />근거로 선택</label><label className="check"><input type="checkbox" disabled={!edit.evidence_codes.includes(item.code)} checked={edit.counter_codes.includes(item.code)} onChange={e => change(index, { counter_codes: e.target.checked ? [...edit.counter_codes, item.code] : edit.counter_codes.filter(code => code !== item.code) })} />반대 근거</label>{item.evidence.map((basis, i) => <small key={i}>{basis.camera_id} {basis.window_id} {basis.start_seconds}–{basis.end_seconds}초 · {basis.note}</small>)}</div>)}</details>
        <label>{names[edit.key]} 반대 근거 검토 메모<textarea aria-label={`${names[edit.key]} 반대 근거 검토 메모`} value={edit.counter_note ?? ''} onChange={e => change(index, { counter_note: e.target.value || null })} maxLength={2000} /></label>
        <label>{names[edit.key]} 판단 이유<textarea aria-label={`${names[edit.key]} 판단 이유`} value={edit.reason} onChange={e => change(index, { reason: e.target.value })} maxLength={2000} /></label>
      </section>;
    })}<label>기본 판정 수정 사유<input value={reason} onChange={e => { setReason(e.target.value); setDirty(true); }} maxLength={2000} /></label><button onClick={() => void save()} disabled={!dirty || !reason.trim()}>기본 판정 저장</button></fieldset>
    {error && <p role="alert" className="error">{error} · 편집값은 유지했습니다. 최신 기본 결과를 확인한 뒤 다시 검토하세요.</p>}
  </div>;
}
