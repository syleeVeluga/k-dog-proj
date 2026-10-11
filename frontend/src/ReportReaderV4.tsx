import { useEffect, useRef, useState } from 'react';
import { accessLost, api } from './api';
import type { Case } from './types';
import type { SheetSummaryV4 } from './ScoringTypesV4';
import type { ReportPublicationV4, ReportRunV4 } from './reportTypesV4';

const message = (value: unknown) => value instanceof Error ? value.message : '리포트를 조회하지 못했습니다.';
const states: Record<string, string> = { available: '관찰됨', partial: '일부 관찰', insufficient: '관찰 부족', held: '판단 보류' };

// 교수/검토자용 리포트 조회. 발급·재발급·중지는 운영자·관리자만 하며, 내용은 기존 열람 규칙(독립 제출·공개 확인)을 그대로 거친다.
export function ReportReaderV4({ item }: { item: Case }) {
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const [runs, setRuns] = useState<ReportRunV4[]>([]), [sheets, setSheets] = useState<SheetSummaryV4[]>([]), [viewer, setViewer] = useState('');
  const [opened, setOpened] = useState<ReportPublicationV4 | null>(null), [error, setError] = useState(''), [loading, setLoading] = useState(true);
  const alive = useRef(true);
  const query = viewer ? `?viewer_sheet_id=${encodeURIComponent(viewer)}` : '';
  const own = sheets.filter(value => value.own && value.active && value.rater_kind === 'human' && value.state === 'submitted');
  const filePath = (runId: string, format: string, inline = false) => path + `/report-runs-s1/${runId}/files/${format}` + query + (inline ? `${query ? '&' : '?'}inline=true` : '');
  useEffect(() => {
    alive.current = true; setOpened(null); setLoading(true);
    void Promise.all([api<ReportRunV4[]>(path + '/report-runs-s1'), api<SheetSummaryV4[]>(path + '/sheets-s1')])
      .then(([list, assigned]) => { if (alive.current) { setRuns(list); setSheets(assigned); setError(''); } })
      .catch(value => { if (alive.current) { setError(message(value)); if (accessLost(value)) setRuns([]); } })
      .finally(() => { if (alive.current) setLoading(false); });
    return () => { alive.current = false; };
  }, [path, item.input_revision]);
  async function open(row: ReportRunV4) {
    setOpened(null); setError('');
    try { const value = await api<ReportPublicationV4>(filePath(row.run_id, 'manifest')); if (alive.current) setOpened(value); }
    catch (value) { if (alive.current) setError(message(value)); }
  }
  const issued = runs.filter(row => row.normal_publish_available);
  return <section aria-label="리포트 조회" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h3>발급된 리포트 조회</h3>
    <p>조회 전용입니다. 리포트 발급·재발급은 운영자가 합니다. 내용은 독립 채점 제출과 공개 확인 규칙을 거친 뒤에만 열립니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {!!own.length && <label>열람 맥락의 내 제출 시트<select aria-label="열람 맥락의 내 제출 시트" value={viewer} onChange={event => { setViewer(event.target.value); setOpened(null); }}>
      <option value="">내 원자료만 기준</option>{own.map(value => <option key={value.sheet_id} value={value.sheet_id}>{value.rater_name} · 제출 {value.revision}판</option>)}</select></label>}
    {loading && <p role="status">리포트 목록을 불러오는 중…</p>}
    {!loading && !issued.length && <p role="status">아직 발급된 리포트가 없습니다. 운영자가 발급하면 여기서 조회할 수 있습니다.</p>}
    {issued.map(row => <article className="panel" key={row.run_id} aria-label={`발급된 리포트 ${row.run_id}`}>
      <h4>{row.is_latest_issued ? '최신 발급본' : '이전 발급본'}{row.outdated ? ' · 이후 입력이 바뀜' : ''}</h4>
      <p>{new Date(row.updated_at).toLocaleString()} 발급</p>
      <button onClick={() => void open(row)}>리포트 열기</button></article>)}
    {opened && <section className="panel" aria-label="조회 중인 리포트"><div className="section-title"><h3>{opened.header.dog_name} · 리포트</h3><button onClick={() => setOpened(null)}>닫기</button></div>
      <div className="form-grid">{opened.profile.cards.map(card => <article className="panel" key={card.key}><h4>{card.title}</h4><p>{card.label ?? states[card.status] ?? card.status}</p>{card.claims.map(claim => <p key={claim.claim_id}>{claim.text}</p>)}</article>)}</div>
      <iframe title="발급된 리포트 미리보기" src={'/api' + filePath(opened.run_id, 'html', true)} sandbox="allow-same-origin allow-modals" style={{ width: '100%', height: 'min(80vh, 950px)', border: '1px solid #ccd8d2' }} />
    </section>}
  </section>;
}
