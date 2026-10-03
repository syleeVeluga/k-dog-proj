import { useEffect, useRef, useState } from 'react';
import { accessLost, api } from './api';
import { mayLeave, useEditBase } from './Editing';
import type { Case } from './types';
import type { BasicResultViewV4 } from './BasicResultsV4';
import type { EvidenceV4, InterpretationReferenceV4, SheetSummaryV4 } from './ScoringTypesV4';
import { DOMAIN_NAMES_V4, type BasicReferenceV4, type BasicSummaryV4, type DomainKeyV4, type DomainOpinionV4, type FinalSummaryV4, type FinalViewV4, type OpinionMetadataV4, type OpinionViewV4 } from './finalTypesV4';

const states: Record<string, string> = { draft: '작성 중', complete: '완료', withdrawn: '철회', selected: '유형 선택 적용', observation_text: '관찰 의견', facts_available: '원관찰 있음', missing: '근거 부족', policy_pending: '규칙 확인 대기' };
const sources = { completed_opinion: '완료 의견', manual_selection: '유효 수동 선택', basic: '고정 기본 결과' };
const choices: Partial<Record<DomainKeyV4, string[]>> = { attachment: ['곁에서 안심하는 사이', '가까이 있어도 안심이 어려운 사이', '거리를 두고 지내는 사이', '다가감과 물러섬이 함께 나오는 사이'], education_attitude: ['허용형', '조율형', '통제형'] };
const domains = Object.keys(DOMAIN_NAMES_V4) as DomainKeyV4[];
const blankDomain = (domain: DomainKeyV4): DomainOpinionV4 => ({ domain, text: '', label: null, reason: '', evidence_codes: [], counter_codes: [], counter_note: null, scene_refs: [] });
const message = (error: unknown) => error instanceof Error ? error.message : 'S1 의견·최종 결과를 확인하지 못했습니다.';
const basicRef = (value: BasicResultViewV4): BasicReferenceV4 => ({ result_id: value.summary.result_id, revision: value.summary.revision, ref: value.summary.manifest_ref, hash: value.summary.manifest_hash });
const sameBasic = (left: BasicReferenceV4 | null | undefined, right: BasicReferenceV4 | null | undefined) => !!left && !!right && left.result_id === right.result_id && left.revision === right.revision && left.ref === right.ref && left.hash === right.hash;
const sceneKey = (scene: EvidenceV4) => JSON.stringify(scene);
const sceneText = (scene: EvidenceV4) => `${scene.camera_id} · ${scene.window_id} · ${scene.start_seconds}~${scene.end_seconds}초 · 실제 관찰 ${scene.observed_seconds}초 · ${scene.note}`;

export function FinalResultsV4({ item, sheets, refreshSheets }: { item: Case; sheets: SheetSummaryV4[]; refreshSheets: () => Promise<void> }) {
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const [viewer, setViewer] = useState(''), [metadata, setMetadata] = useState<OpinionMetadataV4 | null>(null);
  const [opinion, setOpinion] = useState<OpinionViewV4 | null>(null), [finals, setFinals] = useState<FinalSummaryV4[]>([]), [candidates, setCandidates] = useState<BasicSummaryV4[]>([]);
  const [basic, setBasic] = useState<BasicResultViewV4 | null>(null), [selectedFinal, setSelectedFinal] = useState<FinalViewV4 | null>(null);
  const [error, setError] = useState(''), [opinionError, setOpinionError] = useState(''), [busy, setBusy] = useState(false), [unavailable, setUnavailable] = useState(false);
  const [revealReason, setRevealReason] = useState(''), [assembleReason, setAssembleReason] = useState(''), [dirty, setDirty] = useState(false), [editorBusy, setEditorBusy] = useState(false);
  const alive = useRef(true), pending = useRef(false), sequence = useRef(0);
  const context = useRef(''); context.current = `${path}:${viewer}`;
  const query = viewer ? `?viewer_sheet_id=${encodeURIComponent(viewer)}` : '';
  const own = sheets.filter(sheet => sheet.own && sheet.active && sheet.rater_kind === 'human' && sheet.state === 'submitted');
  const viewerRow = own.find(sheet => sheet.sheet_id === viewer);
  const selectedBasic = basic ? basicRef(basic) : null;
  async function reload() {
    const current = ++sequence.current, scope = context.current;
    const [meta, list, available] = await Promise.all([api<OpinionMetadataV4>(path + '/opinions-s1/metadata'), api<FinalSummaryV4[]>(path + '/final-results-s1' + query), api<BasicSummaryV4[]>(path + '/final-results-s1/candidates' + query)]);
    if (!alive.current || current !== sequence.current || scope !== context.current) return;
    setMetadata(meta); setFinals(list); setCandidates(available); setUnavailable(false); setOpinionError('');
    if (meta.requires_reveal) setOpinion(null);
    else {
      try { const value = await api<OpinionViewV4>(path + '/opinions-s1' + query); if (alive.current && current === sequence.current && scope === context.current) setOpinion(value); }
      catch (reason) { if (alive.current && current === sequence.current && scope === context.current) { setOpinion(null); setOpinionError(message(reason)); } }
    }
    if (!alive.current || current !== sequence.current || scope !== context.current) return;
    if (basic && !available.some(row => row.result_id === basic.summary.result_id && row.revision === basic.summary.revision && row.manifest_hash === basic.summary.manifest_hash)) setBasic(null);
    if (selectedFinal) {
      try { const value = await api<FinalViewV4>(path + `/final-results-s1/${selectedFinal.reference.final_id}` + query); if (alive.current && current === sequence.current && scope === context.current) setSelectedFinal(value); }
      catch (reason) { if (alive.current && current === sequence.current && scope === context.current) { setSelectedFinal(null); setError(message(reason)); } }
    }
  }
  useEffect(() => {
    alive.current = true;
    void reload().catch(reason => { if (alive.current) { setError(message(reason)); if (accessLost(reason)) { setUnavailable(true); setOpinion(null); setSelectedFinal(null); setBasic(null); } } });
    return () => { alive.current = false; sequence.current++; };
  }, [path, viewer]);
  async function work(operation: () => Promise<void>) {
    if (pending.current || editorBusy) return;
    pending.current = true; setBusy(true); setError('');
    try { await operation(); }
    catch (reason) { if (alive.current) { setError(message(reason)); if (accessLost(reason)) { setOpinion(null); setSelectedFinal(null); setBasic(null); } } }
    finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  async function selectBasic(row: BasicSummaryV4) {
    const scope = context.current;
    const value = await api<BasicResultViewV4>(path + `/final-results-s1/candidates/${row.result_id}/${row.revision}` + query);
    if (alive.current && scope === context.current) { setBasic(value); setDirty(false); }
  }
  async function reveal(target: InterpretationReferenceV4) {
    if (!viewerRow || !revealReason.trim() || !mayLeave()) return;
    const scope = context.current;
    await api(path + (target.kind === 'opinion' ? '/opinions-s1/reveal' : `/final-results-s1/${target.document_id}/reveal`), 'POST', { target, viewer_sheet_id: viewerRow.sheet_id, expected_viewer_revision: viewerRow.revision, reason: revealReason.trim() });
    if (!alive.current || scope !== context.current) return;
    await refreshSheets(); await reload();
    if (target.kind === 'final' && alive.current && scope === context.current) { const value = await api<FinalViewV4>(path + `/final-results-s1/${target.document_id}` + query); if (alive.current && scope === context.current) setSelectedFinal(value); }
  }
  if (unavailable) return <section className="panel" aria-label="S1 의견과 최종 결과"><p role="alert">{error}</p></section>;
  return <section className="panel" aria-label="S1 의견과 최종 결과" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>S1 행사 의견과 최종 결과</h2>
    <p>영역별 완료 의견 → 유효 수동 선택 → 고정 기본 결과 순서로 적용합니다. 원점수·자동 비율과 이전 최종본은 보존됩니다.</p>
    <p className="fine">여섯 영역 모두 작성하거나 사람 판정을 확정해야만 최종본을 만들 수 있는 것은 아닙니다. 자유서술의 유형 추출은 D04 확인 대기이며, 입장 선택만으로 완료하는 대안은 G01 원양식 확인 대기입니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <fieldset disabled={busy || editorBusy}><legend>고정 입력과 공개 맥락</legend>
      <label>해석 공개를 기록할 본인 제출 시트<select aria-label="해석 공개를 기록할 본인 제출 시트" value={viewer} onChange={event => { if (mayLeave()) { setViewer(event.target.value); setBasic(null); setOpinion(null); setSelectedFinal(null); setDirty(false); } }}><option value="">본인 결과만 사용</option>{own.map(sheet => <option key={sheet.sheet_id} value={sheet.sheet_id}>{sheet.rater_name} · r{sheet.revision} · {sheet.purpose === 'independent' ? '독립' : '공개 후 검수'}</option>)}</select></label>
      <button onClick={() => void work(reload)}>의견·최종 목록 새로고침</button>
      <label>행사에 사용할 고정 기본 결과<select aria-label="행사에 사용할 고정 기본 결과" value={basic ? `${basic.summary.result_id}:${basic.summary.revision}` : ''} onChange={event => { if (!mayLeave()) return; const row = candidates.find(value => `${value.result_id}:${value.revision}` === event.target.value); if (row) void work(() => selectBasic(row)); else { setBasic(null); setDirty(false); } }}><option value="">기본 결과를 명시적으로 선택하세요</option>{candidates.map(row => { const source = sheets.find(sheet => sheet.sheet_id === row.input.sheet_id); return <option key={`${row.result_id}:${row.revision}`} value={`${row.result_id}:${row.revision}`}>{source?.rater_name ?? row.input.sheet_id.slice(0, 8)} · {source?.rater_kind === 'ai' ? 'AI' : '사람'} · 원자료 r{row.input.revision} · 계산 r{row.revision}</option>; })}</select></label>
      <p className="fine">본인 결과와 실제 공개가 허용된 고정 원본만 후보에 표시합니다. 다른 평가자·AI 원자료는 본인 시트에서 먼저 명시 공개해야 합니다.</p>
      {basic && <p>{basic.document.input_document.rater_name} · {basic.document.input_document.sheet.rater_kind === 'ai' ? 'AI' : '사람'} · 선택한 기본 결과 r{basic.summary.revision} · 입력 r{basic.document.input.revision}<br />SHA-256: {basic.summary.manifest_hash}</p>}
    </fieldset>
    <section aria-label="현재 행사 의견"><h3>현재 행사 의견</h3>
      {metadata?.reference ? <p>의견 r{metadata.reference.revision} · {states[metadata.state ?? ''] ?? metadata.state} · 작성 계정 {metadata.actor}</p> : <p>저장된 행사 의견이 없습니다.</p>}
      {metadata?.requires_reveal && <p>다른 작성자의 해석입니다. 명시 공개 전 내용은 표시하지 않습니다.</p>}
      {opinionError && <p role="status">{opinionError}</p>}
      {(metadata?.requires_reveal || finals.some(value => value.requires_reveal)) && <fieldset disabled={busy || dirty}><legend>해석의 명시 공개</legend><p>열람 시 본인 제출 시트에 노출 이력을 남깁니다. 독립 제출본은 보존하고 이후 기록은 검수로 구분합니다.</p>
        <label>해석 공개 사유<input maxLength={2000} value={revealReason} onChange={event => setRevealReason(event.target.value)} /></label>
        {!viewerRow && <p>같은 고정 입력의 본인 제출 시트를 선택하세요.</p>}
        {metadata?.requires_reveal && metadata.reference && <button disabled={!viewerRow || !revealReason.trim()} onClick={() => void work(() => reveal({ kind: 'opinion', document_id: metadata.reference!.opinion_id, revision: metadata.reference!.revision, ref: metadata.reference!.ref, hash: metadata.reference!.hash }))}>현재 의견을 명시 공개하고 노출 기록</button>}
      </fieldset>}
      {opinion?.document && !basic && <><p>평가자 {opinion.document.evaluator || '미입력'} · 실제 완료 {opinion.document.state === 'complete' ? '충족' : '미충족'}</p><p>연결된 기본 결과를 선택하면 의견과 근거를 확인·편집할 수 있습니다.</p><button disabled={busy || !candidates.some(row => row.result_id === opinion.document!.basic.result_id && row.revision === opinion.document!.basic.revision)} onClick={() => { const row = candidates.find(row => row.result_id === opinion.document!.basic.result_id && row.revision === opinion.document!.basic.revision); if (row) void work(() => selectBasic(row)); }}>현재 의견의 고정 기본 결과 선택</button></>}
      {basic && opinion && !metadata?.requires_reveal && <OpinionEditor key={basic.summary.manifest_ref} basic={basic} latest={opinion} path={path} viewer={viewer} blocked={busy} saved={async () => { await reload(); }} invalidated={() => { setOpinion(null); setBasic(null); setSelectedFinal(null); }} onDirty={setDirty} onBusy={setEditorBusy} />}
    </section>
    <fieldset disabled={busy || editorBusy || dirty}><legend>새 최종본 고정</legend>
      <p>현재 의견 {metadata?.reference ? `r${metadata.reference.revision} (${states[metadata.state ?? ''] ?? metadata.state})` : '없음'}을 함께 연결합니다. 철회·작성 중 의견도 출처로 고정하지만 완료 의견으로 적용하지 않습니다.</p>
      {metadata?.basic && selectedBasic && !sameBasic(metadata.basic, selectedBasic) && <p role="status">현재 의견과 선택한 기본 결과가 다릅니다. 의견을 재개방하고 고정 기본 입력과 근거를 다시 연결하세요.</p>}
      <label>최종본 고정 사유<input maxLength={4000} value={assembleReason} onChange={event => setAssembleReason(event.target.value)} /></label>
      <button disabled={!basic || !metadata || metadata.requires_reveal || !!metadata.basic && !sameBasic(metadata.basic, selectedBasic) || !assembleReason.trim()} onClick={() => void work(async () => { const value = await api<FinalViewV4>(path + '/final-results-s1', 'POST', { basic: selectedBasic, opinion: metadata?.reference ?? null, viewer_sheet_id: viewer || null, reason: assembleReason.trim() }); await reload(); if (alive.current) { setSelectedFinal(value); setAssembleReason(''); } })}>선택한 판본으로 새 최종본 생성</button>
      {dirty && <p>의견의 미저장 입력을 먼저 저장하거나 버리세요.</p>}
    </fieldset>
    <h3>보존 최종본</h3>{!finals.length && <p>생성된 최종본이 없습니다.</p>}
    <ul>{finals.map(row => <li key={row.reference.final_id}><p>{new Date(row.recorded_at).toLocaleString()} · {row.actor} · 기본 r{row.basic.revision} · 의견 {row.opinion ? `r${row.opinion.revision}` : '없음'}</p>
      {row.requires_reveal ? <button disabled={busy || dirty || !viewerRow || !revealReason.trim()} onClick={() => void work(() => reveal({ kind: 'final', document_id: row.reference.final_id, revision: null, ref: row.reference.ref, hash: row.reference.hash }))}>이 최종본을 명시 공개하고 노출 기록</button> : <button disabled={busy} onClick={() => void work(async () => { const value = await api<FinalViewV4>(path + `/final-results-s1/${row.reference.final_id}` + query); if (alive.current) setSelectedFinal(value); })}>최종본 {row.reference.final_id.slice(0, 8)} 읽기</button>}
    </li>)}</ul>
    {selectedFinal && <FinalSnapshot value={selectedFinal} />}
  </section>;
}

type OpinionDraft = { evaluator: string; completion_requested: boolean; priority_help: string; domains: DomainOpinionV4[] };
function draftOf(value: OpinionViewV4): OpinionDraft { return { evaluator: value.document?.evaluator ?? '', completion_requested: value.document?.completion_requested ?? false, priority_help: value.document?.priority_help ?? '', domains: domains.map(domain => value.document?.domains.find(item => item.domain === domain) ?? blankDomain(domain)) }; }

function OpinionEditor({ basic, latest, path, viewer, blocked, saved, invalidated, onDirty, onBusy }: { basic: BasicResultViewV4; latest: OpinionViewV4; path: string; viewer: string; blocked: boolean; saved: () => Promise<void>; invalidated: () => void; onDirty: (value: boolean) => void; onBusy: (value: boolean) => void }) {
  const edit = useEditBase(latest), [draft, setDraft] = useState<OpinionDraft>(() => draftOf(latest)), [reason, setReason] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const pending = useRef(false), alive = useRef(true); const view = edit.view, value = edit.dirty ? draft : draftOf(view);
  useEffect(() => { onDirty(edit.dirty); }, [edit.dirty, onDirty]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; onDirty(false); onBusy(false); }; }, [onDirty, onBusy]);
  const locked = !!view.document && view.document.state !== 'draft';
  const available = basic.document.input_document.sheet.observations.filter(row => row.status === 'observed' && ['valid', 'caution'].includes(row.validity) && row.evidence.some(scene => Number(scene.observed_seconds) > 0));
  function change(patch: Partial<OpinionDraft>) { edit.change(); setDraft({ ...value, ...patch }); }
  function domainChange(domain: DomainKeyV4, patch: Partial<DomainOpinionV4>) { change({ domains: value.domains.map(item => item.domain === domain ? { ...item, ...patch } : item) }); }
  async function work(action: () => Promise<unknown>) {
    if (pending.current) return; pending.current = true; setBusy(true); onBusy(true); setError('');
    try { await action(); await saved(); if (alive.current) { edit.reset(); setReason(''); } }
    catch (failure) { if (alive.current) { setError(message(failure)); if (accessLost(failure)) invalidated(); } }
    finally { pending.current = false; if (alive.current) { setBusy(false); onBusy(false); } }
  }
  return <section className="panel" aria-label="S1 의견 편집" style={{ minWidth: 0 }}>
    <h3>여섯 영역 의견</h3><p>실제 완료: {view.document?.state === 'complete' ? '충족' : '미충족'} · {states[view.document?.state ?? 'draft']} · r{view.reference?.revision ?? 0}</p>
    {error && <p role="alert" className="error">{error} 미저장 의견은 유지합니다.</p>}
    {edit.dirty && latest.reference?.hash !== view.reference?.hash && <p role="status">다른 의견 판본이 저장되었습니다. 편집 시작 판본과 입력을 유지합니다.</p>}
    {view.document?.completion_issues.map(issue => <p role="status" key={issue}>{issue}</p>)}
    <fieldset disabled={blocked || busy || locked}><legend>평가자와 영역별 원문</legend>
      <label>의견 평가자<input maxLength={200} value={value.evaluator} onChange={event => change({ evaluator: event.target.value })} /></label>
      {value.domains.map(item => { const name = DOMAIN_NAMES_V4[item.domain]; const selected = available.filter(row => item.evidence_codes.includes(row.code)); const scenes = [...new Map(selected.flatMap(row => row.evidence.map(scene => [sceneKey(scene), scene] as const))).values()]; return <section className="panel" key={item.domain} aria-label={`${name} 의견`}>
        <h4>{name}</h4><label>{name} 의견 원문<textarea aria-label={`${name} 의견 원문`} rows={3} maxLength={12000} value={item.text} onChange={event => domainChange(item.domain, { text: event.target.value })} /></label>
        {choices[item.domain] && <><label>{name} 명시 유형<select aria-label={`${name} 명시 유형`} value={item.label ?? ''} onChange={event => domainChange(item.domain, { label: event.target.value || null })}><option value="">유형 선택 없음 · 서술에서 자동 추정하지 않음</option>{choices[item.domain]!.map(label => <option key={label}>{label}</option>)}</select></label><label>{name} 유형 근거<textarea aria-label={`${name} 유형 근거`} value={item.reason} maxLength={4000} onChange={event => domainChange(item.domain, { reason: event.target.value })} /></label></>}
        {view.selection_issues[item.domain] && <p role="status">유형 선택 미적용: {view.selection_issues[item.domain]}</p>}
        <details><summary>{name} 근거 항목·반대 근거·고정 장면</summary>
          <p>현재 선택한 기본 입력의 실제 관찰만 연결합니다. 장면은 원항목의 영상·해시·카메라·시각을 그대로 보존합니다.</p>
          {!available.length && <p>연결할 실제 유효 관찰이 없습니다.</p>}
          {available.map(row => <label className="check" key={row.code}><input type="checkbox" aria-label={`${name} 근거 ${row.code}`} checked={item.evidence_codes.includes(row.code)} onChange={event => { const codes = event.target.checked ? [...item.evidence_codes, row.code] : item.evidence_codes.filter(code => code !== row.code); const allowed = new Set(available.filter(value => codes.includes(value.code)).flatMap(value => value.evidence.map(sceneKey))); domainChange(item.domain, { evidence_codes: codes, counter_codes: item.counter_codes.filter(code => codes.includes(code)), scene_refs: item.scene_refs.filter(scene => allowed.has(sceneKey(scene))) }); }} />{row.code}: {row.value} · {row.evidence.length}개 실제 근거</label>)}
          {item.evidence_codes.filter(code => !available.some(row => row.code === code)).map(code => <p key={code}>{code}: 선택한 기본 입력에 유효한 근거가 없습니다. <button onClick={() => domainChange(item.domain, { evidence_codes: item.evidence_codes.filter(value => value !== code), counter_codes: item.counter_codes.filter(value => value !== code), scene_refs: [] })}>이전 근거 {code} 제거</button></p>)}
          {selected.map(row => <label className="check" key={row.code}><input aria-label={`${name} 반대 근거 ${row.code}`} type="checkbox" checked={item.counter_codes.includes(row.code)} onChange={event => domainChange(item.domain, { counter_codes: event.target.checked ? [...item.counter_codes, row.code] : item.counter_codes.filter(code => code !== row.code) })} />{row.code}를 반대 근거로 검토</label>)}
          <label>{name} 반대 근거 검토<textarea aria-label={`${name} 반대 근거 검토`} value={item.counter_note ?? ''} maxLength={4000} onChange={event => domainChange(item.domain, { counter_note: event.target.value || null })} /></label>
          {scenes.map((scene, index) => <label className="check" key={sceneKey(scene)}><input type="checkbox" aria-label={`${name} 지정 장면 ${index + 1}`} checked={item.scene_refs.some(value => sceneKey(value) === sceneKey(scene))} onChange={event => domainChange(item.domain, { scene_refs: event.target.checked ? [...item.scene_refs, scene] : item.scene_refs.filter(value => sceneKey(value) !== sceneKey(scene)) })} />{sceneText(scene)}</label>)}
        </details>
      </section>; })}
      <label>D39 우선 도움<textarea aria-label="D39 우선 도움" maxLength={12000} value={value.priority_help} onChange={event => change({ priority_help: event.target.value })} /></label>
      <p className="fine">우선 도움은 부속 정보입니다. 이것만 작성하거나 유형만 선택한 상태로는 실제 완료되지 않습니다.</p>
      <label className="check"><input type="checkbox" checked={value.completion_requested} onChange={event => change({ completion_requested: event.target.checked })} />B40 의견 완료 요청</label>
    </fieldset>
    <label>의견 저장·상태 변경 사유<input disabled={busy || blocked} maxLength={4000} value={reason} onChange={event => setReason(event.target.value)} /></label>
    <div className="toolbar">{!locked && <button disabled={busy || blocked || !reason.trim()} onClick={() => void work(() => api(path + '/opinions-s1', 'PUT', { expected_revision: view.reference?.revision ?? 0, basic: basicRef(basic), viewer_sheet_id: viewer || null, ...value, reason: reason.trim() }))}>의견 저장·완료 조건 확인</button>}
      {locked && <button disabled={busy || blocked || !reason.trim()} onClick={() => void work(() => api(path + '/opinions-s1/reopen', 'POST', { expected_revision: view.reference!.revision, viewer_sheet_id: viewer || null, reason: reason.trim() }))}>의견 재개방</button>}
      {view.document && view.document.state !== 'withdrawn' && <button disabled={busy || blocked || edit.dirty || !reason.trim()} onClick={() => void work(() => api(path + '/opinions-s1/withdraw', 'POST', { expected_revision: view.reference!.revision, viewer_sheet_id: viewer || null, reason: reason.trim() }))}>의견 철회</button>}
      {edit.dirty && <button disabled={busy || blocked} onClick={() => { if (edit.discard()) { setReason(''); setError(''); } }}>미저장 의견 버리고 최신 조회</button>}
    </div>
    {view.reference && <details><summary>의견 판본과 해시</summary><p>{view.reference.ref}<br />SHA-256: {view.reference.hash}</p><p>이전 판본 {view.document?.previous.map(value => `r${value.revision}`).join(', ') || '없음'}</p></details>}
  </section>;
}

function FinalSnapshot({ value }: { value: FinalViewV4 }) {
  const doc = value.document;
  return <section className="panel" aria-label="S1 보존 최종본" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h3>고정 최종본 · 읽기 전용</h3><p>{new Date(doc.recorded_at).toLocaleString()} · 작성 계정 {doc.actor} · {doc.change_reason}</p>
    <p>기본 r{doc.basic.revision} · 의견 {doc.opinion ? `r${doc.opinion.revision}` : '없음'} · {doc.independent_ai ? '독립 AI 기본 결과' : '선택한 입력과 의견을 적용한 행사 결과'}</p>
    {doc.opinion_document && <p>의견 평가자 {doc.opinion_document.evaluator || '미입력'} · 의견 작성 계정 {doc.opinion_document.actor} · {states[doc.opinion_document.state]}</p>}
    <p>상세 유형 자동 해석은 D04 확인 대기입니다. 누락·보류 사유를 함께 보존합니다.</p>
    {doc.domains.map(domain => <article key={domain.domain} aria-label={`${DOMAIN_NAMES_V4[domain.domain]} 최종 영역`}><h4>{DOMAIN_NAMES_V4[domain.domain]} · {domain.label ?? '유형 확정 없음'}</h4><p>{sources[domain.source]} · {states[domain.status] ?? domain.status} · {domain.reason}</p>{domain.text && <p style={{ whiteSpace: 'pre-wrap' }}>{domain.text}</p>}<p>원래 자동 유형: {domain.original_label ?? '보류'} · 사용 항목: {domain.evidence_codes.join(', ') || '없음'} · 반대 근거: {domain.counter_codes.join(', ') || '없음'}</p>{domain.counter_note && <p>반대 근거 검토: {domain.counter_note}</p>}
      {domain.source === 'completed_opinion' && doc.opinion_document?.domains.find(item => item.domain === domain.domain)?.scene_refs.map((scene, index) => <p key={index}>고정 장면: {sceneText(scene)}</p>)}
    </article>)}
    <h4>우선 도움</h4><p>{doc.priority_help ?? '완료 의견에서 적용한 우선 도움 없음'}</p>
    <details><summary>보존된 자동 교육태도 배점 비율</summary><p>{doc.basic_document.calculations.owner.ratios?.map(value => Number(value.toFixed(4))).join(' / ') ?? '계산 근거 부족'} · {doc.basic_document.calculations.owner.reason}</p><p>의견 때문에 비율을 변경하지 않습니다.</p></details>
    <details><summary>최종본·기본 입력·의견 출처 해시</summary><p>최종본: {value.reference.ref}<br />SHA-256: {value.reference.hash}</p><p>기본 결과: {doc.basic.ref}<br />SHA-256: {doc.basic.hash}</p><p>원자료: {doc.basic_document.input.ref}<br />SHA-256: {doc.basic_document.input.hash}</p>{doc.opinion && <p>의견: {doc.opinion.ref}<br />SHA-256: {doc.opinion.hash}</p>}</details>
  </section>;
}
