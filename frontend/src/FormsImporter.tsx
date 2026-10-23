import { useState } from 'react';
import type { DragEvent } from 'react';
import { api } from './api';
import { autoMap, festival, festivalLabels, itemLabel, parseLabelLines, parseQuestionRange, profileFields, questionKeys, requiredKeys } from './formsAutoMap';
import type { AutoMap } from './formsAutoMap';
import { errorFileName, errorRowsCsv, hasErrorRows } from './formsCsv';
import { FormsPresets } from './FormsPresets';
import type { Preset } from './FormsPresets';
import type { Case, Run } from './types';

type Target = { row_number: number; case_id: string; session_id: string; expected_revision: number };
type PreviewRow = { row_number: number; action: 'create' | 'update'; matched_by: 'id' | 'explicit' | null; file_dog_name: string | null; case_id: string; session_id: string; event_id: string; participant_id: string; dog_name: string; answers: Record<string, number | null>; previous_answers: Record<string, number | null>; blank_reasons: Record<string, string>; previous_blank_reasons: Record<string, string>; changed_questions: string[]; registration_status: string };
type Issue = { row_number: number | null; message: string; raw_values: Record<string, string | number | boolean | null> | null };
type Preview = { preview_id: string; preview_hash: string; source_hash: string; original_headers: string[]; already_committed: boolean; rows: PreviewRow[]; errors: Issue[] };
const questions = questionKeys;
const templates = [['roster', '명단만'], ['full', '명단 + 설문 28문항']] as const;
const EVENT_KEY = 'kdog.forms.eventId';
const INPUT_SHEET = '입력';

// 브라우저 저장소는 편의용이다. 막혀 있어도 동작해야 한다.
function storedEvent() { try { return window.localStorage.getItem(EVENT_KEY) ?? ''; } catch { return ''; } }
function rememberEvent(value: string) { try { window.localStorage.setItem(EVENT_KEY, value); } catch { /* 저장 실패는 무시한다 */ } }

function encodedFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'));
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.readAsDataURL(file);
  });
}

const fileFormat = (file: File) => file.name.toLowerCase().endsWith('.xlsx') ? 'xlsx' : 'csv';

export function FormsImporter({ cases, run, done }: { cases: Case[]; run: Run; done: (message: string) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [eventId, setEventId] = useState(storedEvent);
  const [layout, setLayout] = useState('rows');
  const [sheet, setSheet] = useState('');
  const [sheets, setSheets] = useState<string[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [auto, setAuto] = useState<AutoMap | null>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const labelLines = { ...festivalLabels(mapping), ...labels };
  const [bulkRange, setBulkRange] = useState('');
  const [bulkLabels, setBulkLabels] = useState('');
  const [bulkMessage, setBulkMessage] = useState('');
  const [profile, setProfile] = useState('google-forms');
  const [version, setVersion] = useState('forms-map-1');
  const [historical, setHistorical] = useState(false);
  const [historicalVersion, setHistoricalVersion] = useState('');
  const [targets, setTargets] = useState<Target[]>([]);
  const [result, setResult] = useState<Preview | null>(null);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [commitId, setCommitId] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [confirmUpdates, setConfirmUpdates] = useState(false);
  const [outcome, setOutcome] = useState<{ registered: number; excluded: number } | null>(null);

  function invalidate() { setResult(null); setConfirmUpdates(false); setOutcome(null); setRequestId(crypto.randomUUID()); setCommitId(crypto.randomUUID()); }
  function clearColumns() { setColumns([]); setMapping({}); setAuto(null); setLabels({}); setTargets([]); setBulkMessage(''); }
  async function work(action: () => Promise<void>) {
    setBusy(true);
    try { await run(action); } finally { setBusy(false); }
  }
  // 파일·배치·시트가 정해지면 열을 읽고 헤더로 자동 연결을 제안한다.
  async function inspect(source: File, nextLayout: string, nextSheet: string) {
    invalidate();
    if (!/\.(csv|xlsx)$/i.test(source.name)) throw new Error('CSV 또는 XLSX 파일 하나만 올릴 수 있습니다.');
    if (source.size > 32 * 1024 * 1024) throw new Error('파일은 32 MiB 이하로 나누어 등록하세요.');
    const read = (sheetName: string) => {
      const query = new URLSearchParams({ format: fileFormat(source), layout: nextLayout }); if (sheetName) query.set('sheet', sheetName);
      return api<{ columns: { key: string }[]; sheets: string[]; selected_sheet: string | null }>(`/forms/columns?${query}`, 'POST', source);
    };
    let found = await read(nextSheet);
    // 표준 양식을 안내 시트에서 저장한 경우처럼 첫 시트가 안내뿐이면 「입력」 시트를 대신 읽는다.
    if (!nextSheet && found.selected_sheet !== INPUT_SHEET && found.sheets.includes(INPUT_SHEET)
      && !Object.keys(autoMap(found.columns.map(c => c.key)).mapping).length) found = await read(INPUT_SHEET);
    const keys = found.columns.map(c => c.key), proposal = autoMap(keys);
    const sourceLabels = festivalLabels(proposal.mapping), isFestival = Object.keys(sourceLabels).length > 0;
    setColumns(keys); setSheets(found.sheets); setSheet(found.selected_sheet ?? ''); setMapping(proposal.mapping); setAuto(proposal);
    setLabels({}); setProfile(isFestival ? festival.source_profile : 'google-forms');
    setVersion(isFestival ? festival.version : 'forms-map-1');
    setTargets([]); setBulkMessage(''); invalidate();
  }
  function chooseFile(next: File | null) {
    setFile(next); clearColumns(); setSheets([]); setSheet(''); invalidate();
    if (next) void work(() => inspect(next, layout, ''));
  }
  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault(); setDragging(false);
    if (!busy) chooseFile(event.dataTransfer.files[0] ?? null);
  }
  function parsedLabels() {
    const answerLabels: Record<string, Record<string, number>> = {};
    for (const [question, lines] of Object.entries(labelLines)) {
      if (!lines.trim()) {
        if (question in labels) answerLabels[question] = {};
        continue;
      }
      const parsed = parseLabelLines(lines);
      if ('error' in parsed) throw new Error(`${question}: ${parsed.error}`);
      answerLabels[question] = parsed.values;
    }
    return answerLabels;
  }
  async function preview() {
    if (!file) return;
    const config = { request_id: requestId, event_id: eventId.trim(), filename: file.name, format: fileFormat(file),
      mapping: { version, source_profile: profile, survey_version: historical ? historicalVersion : 'survey-20260929-v3',
        sheet: sheet || null, layout, historical_reference_only: historical, columns: mapping, answer_labels: parsedLabels() }, targets, match_existing_ids: true };
    setResult(await api<Preview>('/forms/preview', 'POST', { config, file_base64: await encodedFile(file) }));
    rememberEvent(eventId.trim());
  }
  function applyBulkLabels() {
    const chosen = bulkRange.trim() ? parseQuestionRange(bulkRange) : questions.filter(q => mapping[q]);
    if (!chosen) { setBulkMessage('문항 번호는 「1-9, 15, 20-28」처럼 1~28 범위로 쓰세요.'); return; }
    const parsed = parseLabelLines(bulkLabels);
    if ('error' in parsed || !bulkLabels.trim()) { setBulkMessage('error' in parsed ? parsed.error : '적용할 원라벨=숫자를 입력하세요.'); return; }
    const linked = chosen.filter(q => mapping[q]);
    if (!linked.length) { setBulkMessage('선택한 문항에 연결된 원본 열이 없습니다.'); return; }
    if (Object.values(parsed.values).some(value => value > 4) && linked.some(q => ['s10', 's11', 's12', 's13', 's14'].includes(q))) {
      setBulkMessage('10~14번은 0~4만 쓸 수 있습니다. 5가 있는 라벨은 10~14번을 뺀 문항 번호로 나누어 적용하세요.'); return;
    }
    setLabels({ ...labels, ...Object.fromEntries(linked.map(q => [q, bulkLabels])) });
    setBulkMessage(`${linked.length}개 문항에 같은 라벨을 적용했습니다. 미리보기에서 결과를 확인하세요.`); invalidate();
  }
  function currentMapping() {
    return { columns: mapping, answer_labels: parsedLabels(), layout, source_profile: profile, version };
  }
  // 저장한 연결을 자동 연결 위에 덮어쓴다. 파일에 없는 헤더는 연결 안 됨으로 두고 알려 준다.
  function applyPreset(preset: Preset) {
    const present = new Set(columns), next = { ...(auto?.mapping ?? {}) }, missing: string[] = [];
    const stored = Object.fromEntries(Object.entries(preset.mapping.columns).filter(([key]) => !key.startsWith('consent_')));
    const claimed = new Set(Object.values(stored));
    for (const [key, header] of Object.entries(next)) if (claimed.has(header) && stored[key] !== header) delete next[key];
    for (const [key, header] of Object.entries(stored)) {
      if (present.has(header)) next[key] = header; else { delete next[key]; missing.push(`${itemLabel(key)}(${header})`); }
    }
    const nextLabels: Record<string, string> = Object.fromEntries(Object.entries(labels).filter(([question]) => next[question]));
    for (const [question, values] of Object.entries(preset.mapping.answer_labels)) if (next[question])
      nextLabels[question] = Object.entries(values).map(([label, value]) => `${label}=${value}`).join('\n');
    setMapping(next); setLabels(nextLabels); setProfile(preset.mapping.source_profile); setVersion(preset.mapping.version); invalidate();
    const note = preset.mapping.layout !== layout ? ` 이 설정은 ${preset.mapping.layout === 'rows' ? '일반' : '전치'} 배치용입니다. 「고급 설정」에서 배치를 확인하세요.` : '';
    return `‘${preset.name}’ 연결을 적용했습니다.${missing.length ? ` 파일에 없는 열 ${missing.length}개는 연결 안 됨: ${missing.join(', ')}.` : ''}${note}`;
  }
  function downloadErrors() {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([errorRowsCsv(result.original_headers, result.errors)], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = errorFileName(eventId); link.click();
    URL.revokeObjectURL(url);
  }
  function setTarget(index: number, caseId: string) {
    const item = cases.find(c => c.case_id === caseId);
    setTargets(targets.map((target, i) => i !== index ? target : { ...target, case_id: caseId, session_id: item?.selected_session_id ?? '', expected_revision: item?.input_revision ?? 1 })); invalidate();
  }
  function columnSelect(key: string, label: string, ariaLabel = `폼 열 ${key}`) {
    return <label key={key}>{label}<select aria-label={ariaLabel} value={mapping[key] ?? ''} onChange={e => {
      const next = { ...mapping }; if (e.target.value) next[key] = e.target.value; else delete next[key]; setMapping(next);
      if (profile === 'google-forms' && version === 'forms-map-1' && Object.keys(festivalLabels(next)).length) {
        setProfile(festival.source_profile); setVersion(festival.version);
      }
      invalidate();
    }}><option value="">연결 안 함</option>{columns.map(column => <option key={column} value={column}>{column}</option>)}</select></label>;
  }

  // 참가자 ID 열이 있으면 이미 접수된 ID의 행은 이름 없이도 기존 참가자로 연결되므로 이름 열을 막지 않는다(새로 만들 행만 서버가 오류로 알린다).
  const missingRequired = requiredKeys.filter(key => !mapping[key] && !(key === 'dog_name' && (targets.length || mapping.participant_id)));
  const previewBlock = !file ? '파일을 올리세요.' : !columns.length ? '파일의 열을 읽는 중이거나 파일을 확인하세요.'
    : !eventId.trim() ? '행사 ID를 입력하세요.' : missingRequired.length ? `${missingRequired.map(itemLabel).join('·')} 열을 연결하세요.`
    : historical && !historicalVersion ? '고급 설정에서 원문 설문 판본을 입력하세요.' : !version || !profile ? '고급 설정에서 원자료 프로필과 매핑 버전을 입력하세요.' : '';
  const idRows = result?.rows.filter(row => row.action === 'update' && row.matched_by === 'id') ?? [];
  const unchanged = idRows.filter(row => !row.changed_questions.length).length;
  const mismatched = idRows.filter(row => row.file_dog_name);
  const commitBlock = !result ? '' : !result.rows.length ? '등록할 정상 행이 없습니다. 오류를 고쳐 다시 올리세요.'
    : idRows.length && !confirmUpdates && !result.already_committed ? '「기존 참가자 갱신 확인」을 체크하세요.' : '';
  const commitReady = !!result && !!result.rows.length && !commitBlock;
  const sessionNumber = (row: PreviewRow) => (cases.find(item => item.case_id === row.case_id)?.manifest.sessions.findIndex(item => item.session_id === row.session_id) ?? -1) + 1;
  const rowLabel = (row: PreviewRow) => row.action === 'create' ? '신규' : row.matched_by === 'id'
    ? `기존 참가자 갱신 · ${row.participant_id} ${row.dog_name}${sessionNumber(row) ? ` · ${sessionNumber(row)}차 촬영` : ''}${row.file_dog_name ? ` · 파일 이름 ${row.file_dog_name}과 다름` : ''}${row.changed_questions.length ? '' : ' · 변경 없음'}` : '기존 응답 변경';
  const linkedProfile = profileFields.filter(([key]) => mapping[key]);
  const answerCount = questions.filter(q => mapping[q]).length, reasonCount = questions.filter(q => mapping[`${q}_reason`]).length;

  return <section aria-label="Forms 참가자와 설문 등록">
    <div className="page-heading"><div><p className="eyebrow">UPLOAD</p><h1>참가자/설문 일괄 등록</h1></div></div>
    <p className="fine">명단이나 설문 응답 파일(CSV·Excel)을 올리면 참가자와 설문을 등록합니다. 이름으로 기존 참가자를 추정하지 않습니다. 참가자 ID 열이 없으면 미리보기에서 ID를 발급하고, 동의 열이 없으면 미확인으로 남깁니다.</p>
    {columns.length > 0 && profile === festival.source_profile && <p className="fine" role="status">{festival.name} 양식의 문항과 한글 응답 라벨을 연결했습니다. 영역별 번호는 전체 Q01~Q28에 대응합니다. 두려움 Q10~Q14는 전혀 아니다=0 · 약간=1 · 보통=2 · 꽤 그렇다=3 · 매우 그렇다=4입니다. 나이는 정수 연수로 표시하며 개월을 포함한 원문은 보존합니다. 동의·연락처·거주지·중성화 여부·희망 일시·최종 확인은 원자료에 보존합니다. 희망 일시는 확정 예약으로 등록하지 않습니다.</p>}
    <fieldset disabled={busy}><legend>① 양식 받기 (선택)</legend>
      <p className="fine">표준 양식을 채워 올리면 열 연결을 고칠 필요가 없습니다. 이미 가진 파일은 그대로 올려도 됩니다. Excel 양식(XLSX)을 권장합니다. CSV를 Excel에서 다시 저장하면 0001의 앞자리 0이 사라질 수 있습니다.</p>
      <div className="toolbar">{templates.map(([kind, name]) => <span key={kind} className="template-links"><strong>{name}</strong>
        {(['xlsx', 'csv'] as const).map(format => <a key={format} className="button-link" href={`/api/forms/template?kind=${kind}&format=${format}`} download>{name} {format === 'xlsx' ? 'Excel' : 'CSV'} 내려받기</a>)}</span>)}</div>
    </fieldset>
    <fieldset disabled={busy}><legend>② 파일 올리기</legend>
      <div className={`dropzone${dragging ? ' dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
        <label>Forms 파일<input aria-label="Forms 파일" type="file" accept=".csv,.xlsx" onClick={e => { e.currentTarget.value = ''; }} onChange={e => chooseFile(e.target.files?.[0] ?? null)} /></label>
        <p className="fine">파일을 여기로 끌어다 놓거나 위에서 선택하세요. 올리면 열을 자동으로 읽습니다.{file ? ` 선택한 파일: ${file.name}` : ''}</p>
      </div>
      <div className="form-grid">
        <label>등록 행사 ID<input aria-label="폼 행사 ID" value={eventId} placeholder="KDOG-2026" onChange={e => { setEventId(e.target.value); invalidate(); }} /><small>필수 · 마지막으로 쓴 행사 ID를 제안합니다.</small></label>
        {sheets.length > 1 && <label>원본 시트<select aria-label="원본 시트" value={sheet} onChange={e => { setSheet(e.target.value); clearColumns(); invalidate(); if (file) void work(() => inspect(file, layout, e.target.value)); }}>{sheets.map(s => <option key={s}>{s}</option>)}</select><small>시트가 여러 개입니다. 입력 내용이 있는 시트를 고르세요.</small></label>}
      </div>
      <details><summary>고급 설정</summary><div className="form-grid">
        <label>파일 배치<select aria-label="파일 배치" value={layout} onChange={e => { setLayout(e.target.value); clearColumns(); invalidate(); if (file) void work(() => inspect(file, e.target.value, '')); }}><option value="rows">첫 행이 질문·항목, 이후 행이 참가자</option><option value="transposed">첫 열이 질문·항목, 이후 열이 참가자</option></select></label>
        <label>원자료 프로필<input aria-label="원자료 프로필" value={profile} onChange={e => { setProfile(e.target.value); invalidate(); }} /></label>
        <label>매핑 버전<input aria-label="매핑 버전" value={version} onChange={e => { setVersion(e.target.value); invalidate(); }} /></label>
        <label className="check"><input type="checkbox" checked={historical} onChange={e => { setHistorical(e.target.checked); invalidate(); }} />과거 판본 원자료 참고만 등록</label>
        {historical && <label>원문 설문 판본<input aria-label="원문 설문 판본" value={historicalVersion} onChange={e => { setHistoricalVersion(e.target.value); invalidate(); }} /></label>}
      </div><p className="fine">현재 반영 판본은 survey-20260929-v3입니다. 10~14번은 0~4, 나머지는 1~5입니다. 과거 척도는 자동 환산하지 않습니다.</p></details>
    </fieldset>
    {!!columns.length && <fieldset disabled={busy}><legend>③ 열 연결 확인</legend>
      {auto && <p role="status">자동 연결 {Object.keys(auto.mapping).length}개 · 확인 필요 {auto.review.length + auto.conflicts.length}개 · 연결 안 됨 {auto.unmatched.length}개</p>}
      {!!missingRequired.length && <div className="warning" role="alert">{missingRequired.map(key => <div key={key}>
        {columnSelect(key, `필수: ${itemLabel(key)} 열을 고르세요`, `폼 필수 열 ${key}`)}</div>)}</div>}
      {!mapping.dog_name && !!mapping.participant_id && !targets.length && <p className="warning">반려견 이름 열이 연결되지 않았습니다. 이미 접수된 참가자 ID의 행만 기존 참가자에 연결되고, 그 외 행은 새로 등록할 수 없어 오류로 표시됩니다.</p>}
      {!mapping.participant_id && <p className="warning">참가자 ID 열이 연결되지 않았습니다. 이 파일을 올리면 참가자마다 새 ID를 발급하며, 고친 파일을 다시 올리면 같은 사람이 중복 등록됩니다. ID 열이 있다면 「모든 연결 보기」에서 연결하세요.</p>}
      {layout !== 'rows' && <p className="warning">전치 파일(첫 열이 항목)로 읽는 중입니다. 일반 파일이면 「고급 설정」에서 파일 배치를 바꾸세요.</p>}
      {!!auto?.review.length && <ul className="warning">{auto.review.map(item => <li key={item.column}>‘{item.column}’ 열은 {item.keys.map(itemLabel).join('·')} 중 무엇인지 알 수 없어 연결하지 않았습니다. 「모든 연결 보기」에서 직접 고르세요.</li>)}</ul>}
      {!!auto?.conflicts.length && <ul className="warning">{auto.conflicts.map(item => <li key={item.key}>{itemLabel(item.key)}에 맞는 열이 여러 개입니다({item.columns.join(', ')}). 연결하지 않았으니 「모든 연결 보기」에서 하나를 고르세요.</li>)}</ul>}
      <p className="fine">연결된 항목: {linkedProfile.length ? linkedProfile.map(([key, label]) => `${label} ← ${mapping[key]}`).join(' · ') : '참가자 항목 없음'}{answerCount ? ` · 설문 응답 ${answerCount}문항` : ''}{reasonCount ? ` · 빈칸 사유 ${reasonCount}개` : ''}</p>
      <FormsPresets current={currentMapping} canSave={Object.keys(mapping).length > 0} apply={applyPreset} run={run} disabled={busy} />
      <details><summary>모든 연결 보기</summary>
        <div className="form-grid">{profileFields.filter(([key]) => !missingRequired.includes(key)).map(([key, label]) => columnSelect(key, label))}</div>
        <details><summary>28문항과 빈칸 사유 연결</summary><div className="form-grid">{questions.map((q, i) => <div key={q}>
          {columnSelect(q, `${i + 1}번 원응답`)}{columnSelect(`${q}_reason`, `${i + 1}번 빈칸 사유`)}
          {mapping[q] && <label>{i + 1}번 원라벨=원점수<textarea aria-label={`폼 라벨 ${q}`} placeholder="전혀 그렇지 않다=1" value={labelLines[q] ?? ''} onChange={e => { setLabels({ ...labels, [q]: e.target.value }); invalidate(); }} /><small>숫자 원응답은 그대로 읽습니다. 문장 응답은 줄마다 원라벨=숫자로 명시하세요.</small></label>}
        </div>)}</div></details>
        <details><summary>선택 문항에 같은 라벨 적용</summary>
          <div className="form-grid">
            <label>적용할 문항<input aria-label="라벨 적용 문항" value={bulkRange} placeholder="예: 1-9, 15-28 (비우면 연결된 모든 문항)" onChange={e => setBulkRange(e.target.value)} /></label>
            <label>원라벨=원점수<textarea aria-label="라벨 일괄 입력" placeholder={'매우 그렇다=5\n그렇다=4'} value={bulkLabels} onChange={e => setBulkLabels(e.target.value)} /></label>
          </div>
          <button onClick={applyBulkLabels}>선택 문항에 같은 라벨 적용</button>
          {bulkMessage && <p className="fine" role="status">{bulkMessage}</p>}
        </details>
        <details><summary>기존 참가자·회차에 명시적으로 연결 ({targets.length})</summary>
          <p className="fine">대상 행 번호는 첫 참가자가 2입니다. 전치 파일은 첫 참가자 열이 2입니다. 선택하지 않은 행은 신규 등록하며, 같은 ID가 있으면 오류로 표시합니다.</p>
          {targets.map((target, index) => { const item = cases.find(c => c.case_id === target.case_id); return <div className="form-grid" key={index}>
            <label>원행 번호<input aria-label={`연결 ${index + 1} 원행`} type="number" min="2" value={target.row_number} onChange={e => { setTargets(targets.map((v, i) => i === index ? { ...v, row_number: Number(e.target.value) } : v)); invalidate(); }} /></label>
            <label>기존 참가자<select aria-label={`연결 ${index + 1} 참가자`} value={target.case_id} onChange={e => setTarget(index, e.target.value)}><option value="">대상 선택</option>{cases.map(c => <option key={c.case_id} value={c.case_id}>{c.event_id} / {c.participant_id} · {c.dog_name}</option>)}</select></label>
            <label>촬영 회차<select aria-label={`연결 ${index + 1} 회차`} value={target.session_id} onChange={e => { setTargets(targets.map((v, i) => i === index ? { ...v, session_id: e.target.value } : v)); invalidate(); }}>{item?.manifest.sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.session_id}</option>)}</select></label>
            <button disabled={!target.case_id} onClick={() => void work(async () => {
              const latest = await api<Case>(`/cases/${target.case_id}`);
              setTargets(targets.map((v, i) => i === index ? { ...v, expected_revision: latest.input_revision } : v)); invalidate();
            })}>대상 최신 상태로 다시 연결</button>
            <button onClick={() => { setTargets(targets.filter((_, i) => i !== index)); invalidate(); }}>이 연결 제거</button>
          </div>; })}
          <button onClick={() => { setTargets([...targets, { row_number: 2 + targets.length, case_id: '', session_id: '', expected_revision: 1 }]); invalidate(); }}>기존 대상 연결 추가</button>
        </details>
      </details>
    </fieldset>}
    <fieldset disabled={busy}><legend>④ 미리보기·등록</legend>
      <div className="toolbar"><button className="primary" disabled={!!previewBlock} aria-describedby="forms-preview-reason" onClick={() => void work(preview)}>Forms 등록 미리보기</button>
        <span id="forms-preview-reason" className="fine" aria-live="polite">{previewBlock}</span></div>
    </fieldset>
    {result && <section aria-label="Forms 등록 미리보기 결과"><h3>원행 {result.rows.length}개 · 오류 {result.errors.length}개</h3>
      {result.already_committed && <p role="status">이미 확정한 파일입니다. 재확정해도 참가자가 추가되지 않습니다.</p>}
      {!!idRows.length && <div className="panel">
        <label className="check"><input type="checkbox" aria-label="기존 참가자 갱신 확인" checked={confirmUpdates} disabled={result.already_committed} onChange={e => setConfirmUpdates(e.target.checked)} />기존 참가자 {idRows.length}명 갱신 확인</label>
        <p className="fine">참가자 ID가 이미 접수된 ID와 정확히 같은 행입니다. 이름·견명으로는 연결하지 않았습니다. 설문 응답만 갱신하며 이름·동의 등 접수 정보는 바꾸지 않습니다. 파일의 빈 칸과 연결하지 않은 문항은 기존 응답을 지우지 않고, 값이 있는 문항만 바뀝니다. 행을 펼치면 바뀌는 문항을 전후 값으로 볼 수 있습니다.{unchanged ? ` 바뀌는 문항이 없는 행이 ${unchanged}명 있습니다(새 입력 버전을 만들지 않습니다).` : ''}</p>
        {!!mismatched.length && <p className="warning">파일의 반려견 이름이 접수된 이름과 다른 행이 {mismatched.length}명 있습니다. 참가자 ID를 잘못 쓴 것은 아닌지 확인하세요: {mismatched.map(row => `${row.participant_id}(접수 ${row.dog_name} ↔ 파일 ${row.file_dog_name})`).join(', ')}</p>}</div>}
      {!!result.errors.length && <div role="alert">{result.errors.map((error, i) => <p key={i}>{error.row_number ? `${error.row_number}행: ` : ''}{error.message}</p>)}
        <p>{result.rows.length ? `오류가 있는 ${result.errors.length}행을 빼고 정상 ${result.rows.length}행만 등록할 수 있습니다. 제외한 행은 오류 사유를 붙인 CSV로 내려받아 고친 뒤 다시 올리세요.` : '오류를 모두 해결한 후 다시 확인하세요.'}</p>
        {hasErrorRows(result.errors) && <div className="toolbar"><button onClick={downloadErrors}>오류 행 CSV 내려받기</button><span className="fine">참가자 정보가 들어 있습니다. 현장 PC에만 보관하고 작업 후 삭제하세요.{layout !== 'rows' ? ' 전치 파일의 오류 행도 일반 배치(첫 행이 항목)로 내려받습니다. 다시 올릴 때 「고급 설정」의 파일 배치를 일반으로 바꾸세요.' : ''}{result.errors.some(error => !error.raw_values) ? ' 원행이 없는 오류는 CSV에 들어 있지 않습니다.' : ''}</span></div>}</div>}
      {result.rows.map(row => <details key={row.row_number}><summary>{row.row_number}행 · {rowLabel(row)} · {row.event_id}/{row.participant_id} · {row.dog_name} · {row.registration_status === 'reference_only' ? '원자료 참고' : `응답 ${Object.values(row.answers).filter(v => v !== null).length}/28`}</summary>
        <div className="table-wrap"><table><thead><tr><th>문항</th><th>이전 원응답</th><th>반영 원응답</th><th>이전 빈칸 사유</th><th>반영 빈칸 사유</th></tr></thead><tbody>{questions.filter(q => row.changed_questions.includes(q) || row.answers[q] !== null || row.blank_reasons[q]).map(q => <tr key={q}><td>{q}</td><td>{row.previous_answers[q] ?? '빈칸'}</td><td>{row.answers[q] ?? '빈칸'}</td><td>{row.previous_blank_reasons[q] ?? '—'}</td><td>{row.blank_reasons[q] ?? '—'}</td></tr>)}</tbody></table></div>
      </details>)}
      <div className="toolbar"><button className="primary" disabled={busy || !commitReady} onClick={() => void work(async () => {
        const partial = result.errors.length > 0;
        // 다른 변경으로 거절되면 미리보기를 비운다. 다시 미리보기를 누르면 최신 상태로 새로 만든다.
        const committed = await api<{ rows: { case_id: string }[]; excluded: Issue[] }>('/forms/commit', 'POST', { request_id: commitId, preview_id: result.preview_id, preview_hash: result.preview_hash, accept_partial: partial }).catch(error => { invalidate(); throw error; });
        setResult({ ...result, already_committed: true }); setOutcome({ registered: committed.rows.length, excluded: committed.excluded.length });
        await done(`${committed.rows.length}개 원행의 참가자·설문 등록을 확인했습니다.${committed.excluded.length ? ` 오류 ${committed.excluded.length}행은 제외했습니다.` : ''}`);
      })}>{result.errors.length && result.rows.length ? `정상 ${result.rows.length}행 등록 · 오류 ${result.errors.length}행 제외` : 'Forms 전체 확정'}</button>
        {commitBlock && <span className="fine" aria-live="polite">{commitBlock}</span>}</div>
      {outcome && <p role="status">등록 결과: 정상 {outcome.registered}행 등록{outcome.excluded ? ` · 오류 ${outcome.excluded}행 제외` : ''}</p>}
    </section>}
  </section>;
}
