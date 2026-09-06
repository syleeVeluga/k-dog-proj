import { useState } from 'react';
import { api } from './api';
import type { Case, Preview } from './types';

export function Importer({ run, done, catalogVersion, cases }: { run: (work: () => Promise<void>) => Promise<void>;
  done: (message: string) => Promise<void>; catalogVersion: string; cases: Case[] }) {
  const [kind, setKind] = useState('participants');
  const [mode, setMode] = useState('standard');
  const [sheet, setSheet] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [columns, setColumns] = useState<{ key: string; label: string }[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Preview | null>(null);
  const format = file?.name.toLowerCase().endsWith('.xlsx') ? 'xlsx' : 'csv';
  const canonical = kind === 'participants' ? ['event_id', 'participant_id', 'dog_name', 'reservation_at']
    : ['event_id', 'participant_id', ...Array.from({ length: 30 }, (_, i) => `q${String(i + 1).padStart(2, '0')}`)];
  const labels: Record<string, string> = { event_id: '행사 ID', participant_id: '참가자 ID', dog_name: '반려견 이름', reservation_at: '예약 시각 (선택)' };
  function clear() { setColumns([]); setMapping({}); setResult(null); }
  return <section><p className="eyebrow">자료 연결</p><h1>자료 가져오기</h1><p className="muted">CSV·Excel을 연결·검증한 뒤 정상 행을 저장합니다.</p>
    <div className="panel"><label>자료 종류<select value={kind} onChange={e => { setKind(e.target.value); setMode('standard'); clear(); }}><option value="participants">참가자</option><option value="survey">설문 원응답</option></select></label>
      <p className="links"><a href={`/api/templates/${kind}?format=csv`}>CSV 양식 다운로드</a><a href={`/api/templates/${kind}?format=xlsx`}>Excel 양식 다운로드</a></p>
      <p className="fine">ID는 텍스트로 입력하세요. 설문은 등록된 참가자의 현재 촬영 세션에 연결됩니다.</p>
      {kind === 'survey' && mode === 'standard' && <p className="fine">표준 양식 survey_version: <strong className="mono">{catalogVersion}</strong>. 열 연결·원본 가로 양식은 확정 버전을 자동 적용합니다.</p>}
      <label>입력 양식<select value={mode} onChange={e => { setMode(e.target.value); setSheet(e.target.value === 'horizontal' ? '데이터입력' : ''); clear(); }}>
        <option value="standard">표준 CSV·Excel</option><option value="mapped">다른 열 이름 연결</option>{kind === 'survey' && <option value="horizontal">원본 설문 가로 양식 · 참가자 열 연결</option>}
      </select></label>
      {mode !== 'standard' && <label>Excel 시트명 (비우면 활성 시트)<input value={sheet} onChange={e => { setSheet(e.target.value); clear(); }} /></label>}
      <form onSubmit={e => { e.preventDefault(); if (!file) return; void run(async () => {
        setResult(null);
        const query = new URLSearchParams({ kind, format });
        if (mode !== 'standard') query.set('mapping', JSON.stringify({ sheet: sheet || null, [mode === 'horizontal' ? 'horizontal' : 'columns']: mapping }));
        setResult(await api<Preview>(`/imports/preview?${query}`, 'POST', file));
      }); }}><label>입력 파일<input type="file" accept=".csv,.xlsx" required onChange={e => { setFile(e.target.files?.[0] ?? null); clear(); }} /></label>
        {mode !== 'standard' && <><button type="button" disabled={!file} onClick={() => void run(async () => {
          const query = new URLSearchParams({ format, horizontal: String(mode === 'horizontal') }); if (sheet) query.set('sheet', sheet);
          const found = await api<{ columns: { key: string; label: string }[] }>(`/imports/columns?${query}`, 'POST', file);
          setColumns(found.columns); setMapping({}); setResult(null);
        })}>연결할 열 불러오기</button>
          <div className="form-grid">{mode === 'horizontal' ? columns.map(c => <label key={c.key}>{c.key}열 · {c.label}<select value={mapping[c.key] ?? ''} onChange={e => { const next = { ...mapping }; if (e.target.value) next[c.key] = e.target.value; else delete next[c.key]; setMapping(next); setResult(null); }}>
            <option value="">가져오지 않음</option>{cases.map(c => <option key={c.case_id} value={c.case_id}>{c.event_id} / {c.participant_id} · {c.dog_name}</option>)}</select></label>)
            : columns.length > 0 && canonical.map(field => <label key={field}>{labels[field] ?? `${field} 문항`}<select value={mapping[field] ?? ''} required={field !== 'reservation_at'} onChange={e => { const next = { ...mapping }; if (e.target.value) next[field] = e.target.value; else delete next[field]; setMapping(next); setResult(null); }}>
              <option value="">원본 열 선택</option>{columns.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}</select></label>)}</div>
        </>}
        <button disabled={mode !== 'standard' && !Object.keys(mapping).length}>검증 미리보기</button>
      </form>
    </div>
    {result && <div className="panel"><h2>검증 결과 · 정상 {result.rows.length}행 / 오류 {result.errors.length}행</h2>
      {result.errors.length > 0 && <a download="kdog-import-errors.txt" href={`data:text/plain;charset=utf-8,${encodeURIComponent(result.errors.join('\n'))}`}>오류 행 안내 다운로드</a>}
      {result.errors.map((error, i) => <p className="error" key={i}>{error}</p>)}
      <ul>{result.rows.map(row => <li key={row.row_number}>{row.source_location || `${row.row_number}행`} · {row.event_id} / {row.participant_id} · {row.participant ? row.participant.dog_name : `설문 원응답 ${Object.values(row.survey!.answers).filter(v => v !== null).length}/30`}
        {row.survey && <><p>{row.session_label} · 입력 버전 {row.survey.expected_revision} · 변경 {row.changed_questions?.length ?? 0}문항</p>
          <details><summary>원응답·변경 문항 확인</summary><p>{row.changed_questions?.join(', ') || '동일 응답'}</p><p className="fine mono">{Object.entries(row.survey.answers).map(([q, answer]) => `${q}: ${answer ?? '미응답'}`).join(' · ')}</p></details></>}
      </li>)}</ul>
      <button className="primary" disabled={!result.rows.length} onClick={() => void run(async () => {
        const saved = await api<{ message: string }>('/imports/commit', 'POST', { rows: result.rows }); setResult(null); await done(saved.message);
      })}>정상 {result.rows.length}행 저장</button><p className="fine">오류 행은 저장되지 않습니다. 미리보기 이후 자료가 변경되면 새로 검증해야 합니다.</p>
    </div>}
  </section>;
}
