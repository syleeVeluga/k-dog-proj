import { useEffect, useState } from 'react';
import { api } from '../api';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { SEGMENTS } from '../types';
import type { Case } from '../types';

type PlannedClip = { name: string; segment: string; start_sec: number; end_sec: number; fps: number };
type Status = { status: 'ready' | 'not_ready' | 'running' | 'interrupted' | 'failed' | 'complete'; message: string; readiness_message: string; planned_clips: PlannedClip[]; ready: boolean; outdated: boolean;
  rules_version: string; dense_fps: number; sparse_fps: number; input_revision: number; video_name: string | null;
  result: { input_revision: number; created_at: string; clips: { name: string; segment: string; start_sec: number; end_sec: number; fps: number; ref: string; hash: string }[] } | null };

export function Preprocessing({ cases, selected, select, filters, writable }: { cases: Case[]; selected: Case | null; select: (item: Case) => void; filters: CaseFilterProps; writable: boolean }) {
  return <section><h1>전처리</h1><p>기준 영상을 구간별로 잘라 분석용 파일을 만듭니다. 원본과 오디오는 보존됩니다. 실행·재시도는 운영자가 버튼을 눌러 시작합니다.</p>
    {selected ? <PreprocessPanel key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} writable={writable} /> : <>
      <CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>행사 / 참가자</th><th>반려견</th><th>작업</th></tr></thead><tbody>
        {cases.filter(c => matchesCase(c, filters.search, filters.eventFilter)).map(c => <tr key={c.case_id}><td>{c.event_id} / {c.participant_id}</td><td>{c.dog_name}</td><td><button onClick={() => select(c)} aria-label={`${c.participant_id} 전처리 열기`}>열기</button></td></tr>)}
      </tbody></table></div></>}
  </section>;
}

function PreprocessPanel({ item, writable }: { item: Case; writable: boolean }) {
  const [state, setState] = useState<Status | null>(null);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [starting, setStarting] = useState(false);
  const path = `/cases/${item.case_id}/sessions/${item.selected_session_id}/preprocess`;
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const value = await api<Status>(path); if (active) { setState(value); setLoadError(''); } }
      catch (e) { if (active) { setLoadError(e instanceof Error ? e.message : '상태를 조회하지 못했습니다.'); setState(null); } }
      if (active) timer = setTimeout(poll, 2000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [path, item.input_revision]);
  async function start() {
    if (!state) return;
    setStarting(true); setError('');
    try { setState(await api<Status>(path, 'POST', { expected_revision: state.input_revision })); }
    catch (e) { setError(e instanceof Error ? e.message : '실행에 실패했습니다. 상태를 확인하고 다시 시도하세요.'); }
    finally { setStarting(false); }
  }
  return <div className="panel" aria-label="전처리 상태">
    {error && <p role="alert">{error}</p>}
    {loadError && <p role="alert">{loadError}</p>}
    {state ? <><p>기준 파일: {state.video_name ?? '영상·구간 확인 필요'}</p><p className="fine">규칙 {state.rules_version} · 자극 순간 이후 최대 5초 {state.dense_fps} fps / 나머지 {state.sparse_fps} fps · 오디오 유지</p>
      <p className="fine">교수 회신 전 Excel 기준 임시 적용입니다. 각 창은 해당 구간 끝에서 자릅니다. 자극 시각 미지정·구간 밖이면 보완해야 실행할 수 있습니다.</p>
      <p role="status">{starting ? '처리 요청 중 · ' : ''}{state.message}</p>
      {!state.ready && <p role="status">{state.readiness_message}</p>}
      {state.planned_clips.length > 0 && <details open><summary>실행 전 처리 구간 확인</summary><ul>{state.planned_clips.map(clip => <li key={clip.name}>{SEGMENTS.find(([id]) => id === clip.segment)?.[1]} · {clip.start_sec}~{clip.end_sec}초 · {clip.fps} fps</li>)}</ul></details>}
      {state.outdated && <p role="status">이전 입력 기준 결과입니다. 현재 영상·구간·규칙으로 다시 전처리해야 합니다.</p>}
      {writable ? <button disabled={starting || state.status === 'running' || !state.ready} onClick={() => void start()}>{['failed', 'interrupted', 'complete'].includes(state.status) ? '이 촬영 전처리 다시 시작' : '이 촬영 전처리 시작'}</button> : <p className="fine">교수/검토자는 상태와 결과만 조회합니다.</p>}
      {state.result && <><h2>완료된 결과 {state.result.clips.length}개</h2><p className="fine">입력 버전 {state.result.input_revision} · {state.result.created_at}</p>
        <ul>{state.result.clips.map(clip => <li key={clip.name}>{SEGMENTS.find(([id]) => id === clip.segment)?.[1]} · {clip.start_sec}~{clip.end_sec}초 · {clip.fps} fps</li>)}</ul>
        <details><summary>관리 정보 · 파일 참조와 해시</summary><pre className="preprocess-manifest">{JSON.stringify(state.result, null, 2)}</pre></details></>}
    </> : !loadError && <p role="status">전처리 상태 조회 중…</p>}
    <details><summary>관리 정보 · 참가자 내부 ID</summary><p className="mono">{item.case_id}</p><p className="fine">CLI의 case_id입니다. 참가자 ID와 다릅니다.</p><button onClick={() => void navigator.clipboard.writeText(item.case_id).catch(() => setError('복사하지 못했습니다. 표시된 내부 ID를 선택해 복사하세요.'))}>내부 ID 복사</button></details>
  </div>;
}
