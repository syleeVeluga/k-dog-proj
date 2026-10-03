import { useState } from 'react';
import { api } from './api';
import type { Case, Run } from './types';

type Target = { row_number: number; case_id: string; session_id: string; expected_revision: number };
type PreviewRow = { row_number: number; action: 'create' | 'update'; case_id: string; session_id: string; event_id: string; participant_id: string; dog_name: string; answers: Record<string, number | null>; previous_answers: Record<string, number | null>; blank_reasons: Record<string, string>; previous_blank_reasons: Record<string, string>; changed_questions: string[]; registration_status: string };
type Preview = { preview_id: string; preview_hash: string; source_hash: string; already_committed: boolean; rows: PreviewRow[]; errors: { row_number: number | null; message: string }[] };
const questions = Array.from({ length: 28 }, (_, i) => `s${String(i + 1).padStart(2, '0')}`);
const profileFields = [
  ['event_id', '행사 ID'], ['participant_id', '참가자 ID'], ['dog_name', '반려견 이름'], ['guardian_name', '보호자 이름'],
  ['reservation_at', '예약 시각'], ['sequence_no', '순번'], ['consent_confirmed', '기본 동의'],
  ['consent_analysis_feedback', '분석·피드백 동의'], ['consent_stranger_contact', '낯선 사람 접촉 동의'],
  ['dog_breed', '견종'], ['dog_sex', '성별'], ['dog_age_years', '나이'], ['dog_size', '크기'], ['years_together', '함께 산 기간'], ['adoption_route', '입양 경로'],
];

function encodedFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'));
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.readAsDataURL(file);
  });
}

export function FormsImporter({ cases, run, done }: { cases: Case[]; run: Run; done: (message: string) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [eventId, setEventId] = useState('');
  const [layout, setLayout] = useState('rows');
  const [sheet, setSheet] = useState('');
  const [sheets, setSheets] = useState<string[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState('google-forms');
  const [version, setVersion] = useState('forms-map-1');
  const [historical, setHistorical] = useState(false);
  const [historicalVersion, setHistoricalVersion] = useState('');
  const [targets, setTargets] = useState<Target[]>([]);
  const [result, setResult] = useState<Preview | null>(null);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [commitId, setCommitId] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const format = file?.name.toLowerCase().endsWith('.xlsx') ? 'xlsx' : 'csv';

  function invalidate() { setResult(null); setRequestId(crypto.randomUUID()); setCommitId(crypto.randomUUID()); }
  async function work(action: () => Promise<void>) {
    setBusy(true);
    try { await run(action); } finally { setBusy(false); }
  }
  async function loadColumns() {
    if (!file) return;
    if (file.size > 32 * 1024 * 1024) throw new Error('파일은 32 MiB 이하로 나누어 등록하세요.');
    const query = new URLSearchParams({ format, layout }); if (sheet) query.set('sheet', sheet);
    const found = await api<{ columns: { key: string }[]; sheets: string[]; selected_sheet: string | null }>(`/forms/columns?${query}`, 'POST', file);
    setColumns(found.columns.map(c => c.key)); setSheets(found.sheets); setSheet(found.selected_sheet ?? ''); setMapping({}); invalidate();
  }
  async function preview() {
    if (!file) return;
    const answerLabels: Record<string, Record<string, number>> = {};
    for (const [question, lines] of Object.entries(labels)) {
      if (!lines.trim()) continue;
      const values: Record<string, number> = {};
      for (const line of lines.split('\n').filter(l => l.trim())) {
        const split = line.lastIndexOf('=');
        const label = line.slice(0, split).trim(); const raw = line.slice(split + 1).trim();
        if (split < 1 || !/^[0-5]$/.test(raw) || label in values) throw new Error(`${question}: 원라벨=숫자 형식과 중복을 확인하세요.`);
        values[label] = Number(raw);
      }
      answerLabels[question] = values;
    }
    const config = { request_id: requestId, event_id: eventId, filename: file.name, format,
      mapping: { version, source_profile: profile, survey_version: historical ? historicalVersion : 'survey-20260929-v3',
        sheet: sheet || null, layout, historical_reference_only: historical, columns: mapping, answer_labels: answerLabels }, targets };
    setResult(await api<Preview>('/forms/preview', 'POST', { config, file_base64: await encodedFile(file) }));
  }
  function setTarget(index: number, caseId: string) {
    const item = cases.find(c => c.case_id === caseId);
    setTargets(targets.map((target, i) => i !== index ? target : { ...target, case_id: caseId, session_id: item?.selected_session_id ?? '', expected_revision: item?.input_revision ?? 1 })); invalidate();
  }
  function columnSelect(key: string, label: string) {
    return <label key={key}>{label}<select aria-label={`폼 열 ${key}`} value={mapping[key] ?? ''} onChange={e => {
      const next = { ...mapping }; if (e.target.value) next[key] = e.target.value; else delete next[key]; setMapping(next); invalidate();
    }}><option value="">연결 안 함</option>{columns.map(column => <option key={column} value={column}>{column}</option>)}</select></label>;
  }
  return <section aria-label="Forms 참가자와 설문 등록">
    <p className="fine">CSV·XLSX 한 파일에서 참가자와 설문을 함께 등록합니다. 이름으로 기존 참가자를 추정하지 않습니다. 원본 ID가 없으면 미리보기에서 ID를 발급합니다. 동의 열이 없으면 미확인으로 남깁니다.</p>
    <fieldset disabled={busy}><legend>원본 파일과 판본</legend><div className="form-grid">
      <label>Forms 파일<input aria-label="Forms 파일" type="file" accept=".csv,.xlsx" onChange={e => { setFile(e.target.files?.[0] ?? null); setColumns([]); setMapping({}); setLabels({}); setTargets([]); setSheets([]); setSheet(''); invalidate(); }} /></label>
      <label>등록 행사 ID<input aria-label="폼 행사 ID" value={eventId} onChange={e => { setEventId(e.target.value); invalidate(); }} /></label>
      <label>원자료 프로필<input value={profile} onChange={e => { setProfile(e.target.value); invalidate(); }} /></label>
      <label>매핑 버전<input value={version} onChange={e => { setVersion(e.target.value); invalidate(); }} /></label>
      <label>파일 배치<select aria-label="파일 배치" value={layout} onChange={e => { setLayout(e.target.value); setColumns([]); setMapping({}); setLabels({}); setTargets([]); invalidate(); }}><option value="rows">첫 행이 질문·항목, 이후 행이 참가자</option><option value="transposed">첫 열이 질문·항목, 이후 열이 참가자</option></select></label>
      {!!sheets.length && <label>원본 시트<select aria-label="원본 시트" value={sheet} onChange={e => { setSheet(e.target.value); setColumns([]); setMapping({}); setLabels({}); setTargets([]); invalidate(); }}>{sheets.map(s => <option key={s}>{s}</option>)}</select></label>}
      <label><input type="checkbox" checked={historical} onChange={e => { setHistorical(e.target.checked); invalidate(); }} />과거 판본 원자료 참고만 등록</label>
      {historical && <label>원문 설문 판본<input value={historicalVersion} onChange={e => { setHistoricalVersion(e.target.value); invalidate(); }} /></label>}
    </div><p className="fine">현재 반영 판본은 survey-20260929-v3입니다. 10~14번은 0~4, 나머지는 1~5입니다. 과거 척도는 자동 환산하지 않습니다.</p>
      <button disabled={!file} onClick={() => void work(loadColumns)}>Forms 열 확인</button>
    </fieldset>
    {!!columns.length && <fieldset disabled={busy}><legend>원본 열과 응답 라벨 연결</legend>
      <div className="form-grid">{profileFields.map(([key, label]) => columnSelect(key, label))}</div>
      <details><summary>28문항과 빈칸 사유 연결</summary><div className="form-grid">{questions.map((q, i) => <div key={q}>
        {columnSelect(q, `${i + 1}번 원응답`)}{columnSelect(`${q}_reason`, `${i + 1}번 빈칸 사유`)}
        {mapping[q] && <label>{i + 1}번 원라벨=원점수<textarea aria-label={`폼 라벨 ${q}`} placeholder="전혀 그렇지 않다=1" value={labels[q] ?? ''} onChange={e => { setLabels({ ...labels, [q]: e.target.value }); invalidate(); }} /><small>숫자 원응답은 그대로 읽습니다. 문장 응답은 줄마다 원라벨=숫자로 명시하세요.</small></label>}
      </div>)}</div></details>
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
      <button className="primary" disabled={!eventId || !version || !profile || (historical && !historicalVersion)} onClick={() => void work(preview)}>Forms 등록 미리보기</button>
    </fieldset>}
    {result && <section aria-label="Forms 등록 미리보기 결과"><h3>원행 {result.rows.length}개 · 오류 {result.errors.length}개</h3>
      {result.already_committed && <p role="status">이미 확정한 파일입니다. 재확정해도 참가자가 추가되지 않습니다.</p>}
      {!!result.errors.length && <div role="alert">{result.errors.map((error, i) => <p key={i}>{error.row_number ? `${error.row_number}행: ` : ''}{error.message}</p>)}<p>오류를 모두 해결한 후 파일 전체를 확정합니다.</p></div>}
      {result.rows.map(row => <details key={row.row_number}><summary>{row.row_number}행 · {row.action === 'create' ? '신규' : '기존 응답 변경'} · {row.event_id}/{row.participant_id} · {row.dog_name} · {row.registration_status === 'reference_only' ? '원자료 참고' : `응답 ${Object.values(row.answers).filter(v => v !== null).length}/28`}</summary>
        <div className="table-wrap"><table><thead><tr><th>문항</th><th>이전 원응답</th><th>반영 원응답</th><th>이전 빈칸 사유</th><th>반영 빈칸 사유</th></tr></thead><tbody>{questions.filter(q => row.changed_questions.includes(q) || row.answers[q] !== null || row.blank_reasons[q]).map(q => <tr key={q}><td>{q}</td><td>{row.previous_answers[q] ?? '빈칸'}</td><td>{row.answers[q] ?? '빈칸'}</td><td>{row.previous_blank_reasons[q] ?? '—'}</td><td>{row.blank_reasons[q] ?? '—'}</td></tr>)}</tbody></table></div>
      </details>)}
      <button className="primary" disabled={busy || !!result.errors.length || !result.rows.length} onClick={() => void work(async () => {
        const committed = await api<{ rows: { case_id: string }[] }>('/forms/commit', 'POST', { request_id: commitId, preview_id: result.preview_id, preview_hash: result.preview_hash });
        setResult({ ...result, already_committed: true }); await done(`${committed.rows.length}개 원행의 참가자·설문 등록을 확인했습니다.`);
      })}>Forms 전체 확정</button>
    </section>}
  </section>;
}
