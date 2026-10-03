import { useEffect, useState } from 'react';
import { api } from '../api';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { SEGMENTS, SEGMENTS_V3, sessionOf } from '../types';
import type { Case, Run } from '../types';
import { PreprocessingPanelV4 } from '../PreprocessingPanelV4';

type PlannedClip = { name: string; segment: string; start_sec: number; end_sec: number; fps: number | string | null; audio_status?: string; audio_available_seconds?: number };
type ObservationWindow = { window_id: string; segment: string; status: string; reason: string | null; start_sec: number | null; end_sec: number | null; item_codes: string[] };
type Status = { status: 'ready' | 'not_ready' | 'running' | 'interrupted' | 'failed' | 'complete'; message: string; readiness_message: string; planned_clips: PlannedClip[]; ready: boolean; outdated: boolean;
  rules_version: string; dense_fps: number | null; sparse_fps: number | null; input_revision: number; video_name: string | null; observation_windows: ObservationWindow[]; provisional: boolean; provisional_reason: string | null;
  result: { input_revision: number; created_at: string; clips: PlannedClip[]; windows?: ObservationWindow[] } | null };

const windowLabels: Record<string, string> = { alone_initial: '분리 초기0~10초', alone_later: '분리 후기10~60초', reunion_first: '재회 전반0~15초', reunion_second: '재회 후반15~30초',
  separation_shake: '분리 직후5초', floor_shake: '바닥 첫 접촉 뒤5초', stranger_gate: '안전문 밖 대기', stranger_enter: '요원 입실', stranger_approach: '요원 접근', stranger_call: '실제 부름 뒤4초', stranger_exit: '요원 퇴장', stranger_wait: '요원 실제 대기',
  stranger_contact_plan: '예정 접촉 안내 (관찰 제외)', stranger_no_contact: '미접촉 실제 대기', reunion_contact: '재회 실제 접촉', stranger_contact: '요원 실제 접촉', entry_object: '입장 물건 관찰', exit_object: '퇴장 물건 관찰', entry_leash: '입장 이동 (물건 정지 제외)', exit_leash: '퇴장 이동 (물건 정지 제외)',
  before_separation: '분리 전 전환', walk_preparation: '걷기 전 준비', walk_seating_wait: '걷기 뒤 착석/대기', walk_start: '걷기 첫걸음 직전 거리',
  walk_phase_1: '이동1', walk_phase_2: '정지1', walk_phase_3: '이동2', walk_phase_4: '정지2', walk_phase_5: '이동3', walk_phase_6: '정지3' };

export function Preprocessing({ cases, selected, select, filters, writable, run, refresh }: { cases: Case[]; selected: Case | null; select: (item: Case) => void; filters: CaseFilterProps; writable: boolean; run: Run; refresh: (message?: string) => Promise<void> }) {
  return <section><h1>전처리</h1><p>기준 영상을 구간별로 잘라 분석용 파일을 만듭니다. 원본과 오디오는 보존됩니다. 실행·재시도는 운영자가 버튼을 눌러 시작합니다.</p>
    {selected ? selected.manifest.schema_version === 'intake-4.0' ? <PreprocessingPanelV4 key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} writable={writable} run={run} refresh={refresh} /> : <PreprocessPanel key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} writable={writable} /> : <>
      <CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>행사 / 참가자</th><th>반려견</th><th>작업</th></tr></thead><tbody>
        {cases.filter(c => matchesCase(c, filters.search, filters.eventFilter)).map(c => <tr key={c.case_id}><td>{c.event_id} / {c.participant_id}</td><td>{c.dog_name}</td><td><button onClick={() => select(c)} aria-label={`${c.participant_id} 전처리 열기`}>열기</button></td></tr>)}
      </tbody></table></div></>}
  </section>;
}

function PreprocessPanel({ item, writable }: { item: Case; writable: boolean }) {
  const current = sessionOf(item).protocol_version === 'protocol-20260929-v3';
  const segments = current ? SEGMENTS_V3 : SEGMENTS;
  const segmentName = (id: string) => segments.find(([key]) => key === id)?.[1] ?? '전환';
  const fpsName = (fps: PlannedClip['fps']) => fps === null ? '원본 프레임/속도' : `${fps} fps`;
  const [state, setState] = useState<Status | null>(null);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [starting, setStarting] = useState(false);
  const windows = state?.result?.windows && !state.outdated ? state.result.windows : state?.observation_windows ?? [];
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
    {state ? <><p>기준 파일: {state.video_name ?? '영상·구간 확인 필요'}</p><p className="fine">규칙 {state.rules_version} · {current ? '원본 프레임/속도 · 연속 영상·오디오 유지' : `자극 순간 이후 최대 5초 ${state.dense_fps} fps / 나머지 ${state.sparse_fps} fps · 오디오 유지`}</p>
      <p className="fine">{current ? '실제 구간·부름·접촉·6국면으로 처리합니다. 미실시/미접촉/불명확 창은 사유를 보존하며 다른 유효 창은 처리할 수 있습니다. 같은 원본 사건이 중첩 클립에 있어도 항목별 횟수를 중복 합산하지 않습니다.' : '교수 회신 전 Excel 기준 임시 적용입니다. 각 창은 해당 구간 끝에서 자릅니다. 자극 시각 미지정·구간 밖이면 보완해야 실행할 수 있습니다.'}</p>
      {current && state.provisional && <p className="fine">판독 충분성 확인 대기 · {state.provisional_reason}</p>}
      <p role="status">{starting ? '처리 요청 중 · ' : ''}{state.message}</p>
      {!state.ready && <p role="status">{state.readiness_message}</p>}
      {state.planned_clips.length > 0 && <details open><summary>실행 전 처리 구간 확인</summary><ul>{state.planned_clips.map(clip => <li key={clip.name}>{segmentName(clip.segment)} · {clip.start_sec}~{clip.end_sec}초 · {fpsName(clip.fps)}</li>)}</ul></details>}
      {current && windows.length > 0 && <details open><summary>항목별 관찰창과 제외 사유</summary><p className="fine">{state.result?.windows && !state.outdated ? '현재 완료 결과의 관찰창 상태입니다.' : '실행 전 계획입니다. 실제 프레임 유무는 처리 후 확인합니다.'}</p><ul>{windows.map(window => <li key={window.window_id}>{windowLabels[window.window_id] ?? (window.window_id.startsWith('transition-') ? '실제 전환 사건' : segmentName(window.segment))} · {window.start_sec === null ? '시각/클립 없음' : `${window.start_sec}~${window.end_sec}초`} · {({ available: '사용 가능', partial: '단축 창', not_performed: '미실시', no_opportunity: '기회 없음', unobserved: '미관찰/경계 미확인', guidance_only: '예정 안내 제외' })[window.status] ?? window.status}
        {window.reason && ` · ${window.reason}`}{window.item_codes.length > 0 && <small>해당 항목 {window.item_codes.join(', ')}</small>}</li>)}</ul></details>}
      {state.outdated && <p role="status">이전 입력 기준 결과입니다. 현재 영상·구간·규칙으로 다시 전처리해야 합니다.</p>}
      {writable ? <button disabled={starting || state.status === 'running' || !state.ready} onClick={() => void start()}>{['failed', 'interrupted', 'complete'].includes(state.status) ? '이 촬영 전처리 다시 시작' : '이 촬영 전처리 시작'}</button> : <p className="fine">교수/검토자는 상태와 결과만 조회합니다.</p>}
      {state.result && <><h2>완료된 결과 {state.result.clips.length}개</h2><p className="fine">입력 버전 {state.result.input_revision} · {state.result.created_at}</p>
        <ul>{state.result.clips.map(clip => <li key={clip.name}>{segmentName(clip.segment)} · {clip.start_sec}~{clip.end_sec}초 · {fpsName(clip.fps)}{current && ` · 오디오 ${clip.audio_status === 'present' ? '있음' : '없음'} · 사용 가능 ${clip.audio_available_seconds === undefined ? '미확인' : Number(clip.audio_available_seconds.toFixed(3))}초 · 청취/발성 미평가`}</li>)}</ul>
        <details><summary>관리 정보 · 파일 참조와 해시</summary><pre className="preprocess-manifest">{JSON.stringify(state.result, null, 2)}</pre></details></>}
    </> : !loadError && <p role="status">전처리 상태 조회 중…</p>}
    <details><summary>관리 정보 · 참가자 내부 ID</summary><p className="mono">{item.case_id}</p><p className="fine">CLI의 case_id입니다. 참가자 ID와 다릅니다.</p><button onClick={() => void navigator.clipboard.writeText(item.case_id).catch(() => setError('복사하지 못했습니다. 표시된 내부 ID를 선택해 복사하세요.'))}>내부 ID 복사</button></details>
  </div>;
}
