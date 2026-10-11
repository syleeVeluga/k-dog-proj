import { useState } from 'react';
import { api } from './api';

type Entry = { change_id: string; actor: string; happened_at: string; target: string; action: string; revision: number | null; format: string | null; session_id: string | null; clip_id: string | null };
type Page = { items: Entry[]; next_offset: number | null; before: number };
const labels: Record<string, string> = {
  'case.create': '참가자 등록', 'case.open': '참가자 자료 열기', 'case.identity': '참가자 정보 수정',
  'survey.save': '설문 저장', 'survey.update': '설문 저장', 'recording.open': '촬영 기록 열기',
  'video.open': '영상 열기', 'upload.open': '원본 파일 제공', 'upload.create': '영상 수신 시작', 'upload.complete': '영상 수신 완료', 'upload.link': '영상 연결',
  'sheet.assign': '채점 시트 생성', 'sheet.open': '채점 시트 열기', 'sheet.save': '채점 저장', 'sheet.submit': '채점 제출', 'sheet.reopen': '채점 수정 시작',
  'basic.open': '기본 결과 열기', 'basic.calculate': '기본 결과 계산', 'basic.judgement': '기본 판정 저장',
  'opinion.open': '의견 열기', 'opinion.s1.save': '의견 저장', 'final.open': '최종본 열기', 'final.s1.publish': '최종본 생성',
  'run_v4.create': '분석 실행 요청', 'run_v4.stop': '분석 중지', 'run_v4.retry': '분석 재시도',
  'report.s1.create': '리포트 생성 요청', 'report.s1.issue': '리포트 발급', 'report.s1.stop': '리포트 중지', 'report.s1.retry': '리포트 재시도', 'report.s1.open': '리포트 파일 제공',
  'export.open': '연구 파일 제공·열기', 'validation.open': '검수 참고 자료 열기', 'comparison.open': '비교집단 열기', 'comparison.external.open': '외부 비교 자료 열기',
};

export function ActivityLogV4({ path }: { path: string }) {
  const [rows, setRows] = useState<Entry[]>([]), [next, setNext] = useState<number | null>(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [before, setBefore] = useState<number | null>(null);
  async function load(offset = 0) {
    if (busy) return;
    setBusy(true); setError('');
    try { const page = await api<Page>(`${path}?offset=${offset}${offset && before !== null ? `&before=${before}` : ''}`); setRows(current => offset ? [...current, ...page.items] : page.items); setNext(page.next_offset); setBefore(page.before); }
    catch (value) { setError(value instanceof Error ? value.message : '기록을 읽을 수 없습니다.'); }
    finally { setBusy(false); }
  }
  return <details onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open) void load(); }}><summary>최근 열람·수정·실행 기록</summary>
    <p className="fine">서버의 자료 제공·저장 기록입니다. 실제 읽음이나 인쇄 완료를 뜻하지 않습니다.</p>
    {error && <p role="alert">{error}</p>}
    <ul aria-label="대상 활동 기록">{rows.map(row => <li key={row.change_id}>{new Date(row.happened_at).toLocaleString()} · {row.actor} · {labels[row.action] ?? '업무 기록'}{row.revision ? ` · r${row.revision}` : ''}{row.format ? ` · ${row.format.toUpperCase()}` : ''}<details><summary>대상 확인</summary>{row.target} · {row.action}{row.session_id && <p>회차: {row.session_id}</p>}{row.clip_id && <p>클립: {row.clip_id}</p>}</details></li>)}</ul>
    {!rows.length && !busy && !error && <p>기록이 없습니다.</p>}
    <button disabled={busy} onClick={() => void load()}>최근 기록 새로고침</button>
    {next !== null && <button disabled={busy} onClick={() => void load(next)}>이전 기록 더 보기</button>}
  </details>;
}
