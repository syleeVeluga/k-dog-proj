import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { CaseFilters, type CaseFilterProps } from './CaseFilters';
import type { Case, User } from './types';
import type { PreprocessExecutionPageV4, PreprocessExecutionV4 } from './preprocessTypesV4';

export const executionStatus: Record<string, string> = { running: '실행 중', complete: '완료', partial: '일부 완료', failed: '실패', interrupted: '중단됨' };

export function PreprocessExecutionsV4({ cases, user, filters, open, create }: {
  cases: Case[]; user: User; filters: CaseFilterProps; open: (item: PreprocessExecutionV4) => void; create: () => void;
}) {
  const [page, setPage] = useState<PreprocessExecutionPageV4 | null>(null), [state, setState] = useState('all');
  const [error, setError] = useState(''), [checked, setChecked] = useState('');
  const generation = useRef(0), inFlight = useRef(false), timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pageDepth = useRef(1);
  const query = new URLSearchParams({ search: filters.search, event_id: filters.eventFilter, status: state }).toString();
  useEffect(() => {
    let alive = true;
    const current = ++generation.current;
    setPage(null); setError(''); setChecked(''); inFlight.current = false; pageDepth.current = 1;
    async function load() {
      if (!alive || current !== generation.current) return;
      clearTimeout(timer.current);
      if (inFlight.current) { timer.current = setTimeout(() => void load(), 2000); return; }
      inFlight.current = true;
      let active = false;
      try {
        let value = await api<PreprocessExecutionPageV4>(`/preprocess-s1/executions?${query}`);
        for (let index = 1; index < pageDepth.current && value.next_cursor; index++) {
          const next = await api<PreprocessExecutionPageV4>(`/preprocess-s1/executions?${query}&cursor=${value.next_cursor}`);
          value = { items: [...value.items, ...next.items], next_cursor: next.next_cursor };
        }
        if (!alive || current !== generation.current) return;
        setPage(value); setError(''); setChecked(new Date().toLocaleTimeString());
        active = value.items.some(item => item.status === 'running');
      } catch (value) {
        if (!alive || current !== generation.current) return;
        setError(value instanceof Error ? value.message : '내 실행 목록을 불러오지 못했습니다.'); active = true;
      } finally {
        if (alive && current === generation.current) {
          inFlight.current = false;
          clearTimeout(timer.current);
          if (active) timer.current = setTimeout(() => void load(), 2000);
        }
      }
    }
    const visible = () => { if (!document.hidden) void load(); };
    const manual = () => void load();
    window.addEventListener('kdog-preprocess-refresh', manual);
    document.addEventListener('visibilitychange', visible);
    void load();
    return () => { alive = false; generation.current++; clearTimeout(timer.current); window.removeEventListener('kdog-preprocess-refresh', manual); document.removeEventListener('visibilitychange', visible); };
  }, [query, user.username]);
  async function more() {
    if (!page?.next_cursor || inFlight.current) return;
    const current = generation.current;
    inFlight.current = true;
    try {
      const value = await api<PreprocessExecutionPageV4>(`/preprocess-s1/executions?${query}&cursor=${page.next_cursor}`);
      if (current === generation.current) { pageDepth.current++; setPage({ items: [...page.items, ...value.items], next_cursor: value.next_cursor }); }
    } catch (value) { if (current === generation.current) setError(value instanceof Error ? value.message : '다음 목록을 불러오지 못했습니다.'); }
    finally { if (current === generation.current) { inFlight.current = false; window.dispatchEvent(new Event('kdog-preprocess-refresh')); } }
  }
  return <section aria-label="내가 실행한 전처리"><div className="section-head"><h2>내가 실행한 전처리</h2>
    <button onClick={() => window.dispatchEvent(new Event('kdog-preprocess-refresh'))}>내 실행 새로고침</button></div>
    <CaseFilters cases={cases} {...filters} />
    <label>전처리 상태<select value={state} onChange={event => setState(event.target.value)}><option value="all">전체</option><option value="running">실행 중</option><option value="complete">완료</option><option value="attention">확인 필요</option></select></label>
    {error && <p role="alert">상태 조회 연결 끊김 · {error} · 마지막 확인 {checked || '아직 없음'}</p>}
    {!page && !error && <p role="status">내 실행 목록 확인 중…</p>}
    {page && <div className="table-wrap"><table><thead><tr><th>참가자 / 반려견</th><th>촬영 회차</th><th>전처리 상태</th><th>실행 시각</th><th>작업</th></tr></thead>
      <tbody>{page.items.map(item => { const target = cases.find(value => value.case_id === item.case_id), index = target?.manifest.sessions.findIndex(value => value.session_id === item.session_id);
        return <tr key={item.execution_id}><td data-label="참가자 / 반려견">{item.participant_id}<small>{item.event_id} · {item.dog_name}</small></td>
          <td data-label="촬영 회차">{index !== undefined && index >= 0 ? `${index + 1}회차` : '보존 회차'}</td><td data-label="전처리 상태">{executionStatus[item.status]}{item.outdated && <small>현재 입력과 다름</small>}</td>
          <td data-label="실행 시각">{new Date(item.started_at).toLocaleString()}</td><td data-label="작업"><button onClick={() => open(item)}>{item.status === 'running' ? '상태 확인' : item.result_pointer ? '결과 보기' : '상세 보기'}</button></td></tr>; })}</tbody></table>
      {!page.items.length && <div className="empty"><h3>{filters.search || filters.eventFilter || state !== 'all' ? '조건에 맞는 전처리 작업이 없습니다.' : '아직 실행한 전처리가 없습니다.'}</h3><button onClick={create}>전처리 실행</button></div>}
      {page.next_cursor && <button onClick={() => void more()}>더 보기</button>}</div>}
  </section>;
}
