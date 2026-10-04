import { useEffect, useState } from 'react';
import { api } from './api';
import { mayLeave, useEditBase } from './Editing';
import { SessionEditor } from './MetadataEditors';
import { SEGMENTS_V3, sessionOf } from './types';
import type { ActualEvent, CaptureState, Case, Run, SegmentId } from './types';
import { EVENT_CHOICES, WINDOW_NAMES } from './recordingTypesV4';
import type { CoverageV4, RecordingV4, RecordingViewV4, TailV4 } from './recordingTypesV4';

const states: Record<CaptureState, string> = { performed: '실시', shortened: '단축', not_performed: '미실시', welfare_stopped: '복지 중단' };
const phaseNames = ['이동1', '정지1', '이동2', '정지2', '이동3', '정지3'];
const phases = (videoId: string): RecordingV4['walk_phases'] => ['move_1', 'stop_1', 'move_2', 'stop_2', 'move_3', 'stop_3'].map(phase => ({
  phase, video_id: videoId, state: 'performed', start_sec: null, end_sec: null, reason: null, proximity_exception: 'unknown', proximity_note: null,
}));
const codes = (text: string) => text.split(',').map(value => value.trim()).filter(Boolean);
const statusNames: Record<string, string> = { confirmed: '시각 확정', partial: '일부 구간', unobserved: '미관찰·사건 확인 필요',
  not_performed: '미실시', no_opportunity: '접촉 기회 없음', policy_pending: '규칙 확정 대기', compatibility_pending: '절차 적합성 검토 필요', ready: '근거 준비됨' };

function initial(item: Case): RecordingV4 {
  const session = sessionOf(item);
  if (session.recording_s1) return structuredClone(session.recording_s1);
  const videoId = session.videos.find(video => video.media_status !== 'storage_only')?.video_id ?? '';
  return { procedure_edition: 'unconfirmed', procedure_note: '', video_id: videoId, confirmed: false,
    segments: SEGMENTS_V3.map(([segment]) => ({ segment, video_id: videoId, state: 'performed', start_sec: null, end_sec: null, reason: null })),
    walk_phases: phases(videoId), events: [], video_offsets: [], coverage: [], tail_selections: [], linked_memos: [], safe_base_sequence: null };
}

function Seconds({ label, value, change, disabled = false }: { label: string; value: number | null; change: (value: number | null) => void; disabled?: boolean }) {
  return <label>{label}<input type="number" min="0" step="any" aria-label={label} disabled={disabled} value={value ?? ''}
    onChange={event => change(event.target.value === '' ? null : Number(event.target.value))} /></label>;
}

function BooleanFact({ label, value, change }: { label: string; value: boolean | null; change: (value: boolean | null) => void }) {
  return <label>{label}<select value={value === null ? '' : value ? 'yes' : 'no'} onChange={event => change(event.target.value === '' ? null : event.target.value === 'yes')}>
    <option value="">미확인</option><option value="yes">확인됨</option><option value="no">아님·관찰 불가</option></select></label>;
}

function CodeList({ label, value, change }: { label: string; value: string[]; change: (value: string[]) => void }) {
  const [text, setText] = useState(value.join(','));
  useEffect(() => { if (codes(text).join(',') !== value.join(',')) setText(value.join(',')); }, [value.join(',')]);
  return <label>{label}<input value={text} onChange={event => { setText(event.target.value); change(codes(event.target.value)); }} /></label>;
}

export function RecordingPanelV4({ item, writable, run, refresh, close }: {
  item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; close: () => void;
}) {
  const session = sessionOf(item), edit = useEditBase(item);
  const [record, setRecord] = useState<RecordingV4>(() => initial(item));
  const [editing, setEditing] = useState(!session.recording_s1?.confirmed);
  const [view, setView] = useState<RecordingViewV4 | null>(null);
  const [viewError, setViewError] = useState('');
  const path = `/cases/${item.case_id}/sessions/${session.session_id}/recording-s1`;
  const videos = session.videos.filter(video => video.media_status !== 'storage_only');
  useEffect(() => {
    if (!edit.dirty) { setRecord(initial(item)); setEditing(!session.recording_s1?.confirmed); }
  }, [item.case_id, session.session_id, item.input_revision]);
  useEffect(() => {
    let active = true;
    void api<RecordingViewV4>(path).then(value => { if (active) { setView(value); setViewError(''); } })
      .catch(error => { if (active) { setView(null); setViewError(error.message); } });
    return () => { active = false; };
  }, [path, item.input_revision]);
  const change = (next: RecordingV4) => { edit.change(); setRecord({ ...next, confirmed: false }); };
  const eventChange = (id: string, patch: Partial<ActualEvent>) => change({ ...record, events: record.events.map(value => value.event_id === id ? { ...value, ...patch } : value) });
  const videoOptions = videos.map(video => <option key={video.video_id} value={video.video_id}>{video.camera_id ? `${video.camera_id} · ` : ''}{video.original_name}</option>);
  function save(confirmed: boolean) {
    void run(async () => {
      if (!record.procedure_note.trim()) throw new Error('실제 촬영 절차의 확인 근거를 기록하세요.');
      if (record.events.some(event => !event.note.trim() || event.status === 'observed' && event.seconds === null)) throw new Error('사건마다 실제 맥락·사유와 관찰 시각을 기록하세요.');
      if (record.coverage.some(value => !value.note.trim() || value.start_seconds === null || value.end_seconds === null || value.observed_seconds === null)) throw new Error('관찰 근거의 범위·실제 관찰 초·설명을 모두 기록하세요.');
      await api(path, 'PUT', { expected_revision: edit.view.input_revision, recording: { ...record, confirmed } });
      edit.reset(); setEditing(!confirmed); await refresh(confirmed ? 'S1 촬영 기록을 확정했습니다.' : 'S1 촬영 기록을 초안 저장했습니다.');
    });
  }
  function addEvent(kind: string) {
    change({ ...record, events: [...record.events, { event_id: crypto.randomUUID(), kind, video_id: record.video_id,
      segment: EVENT_CHOICES.find(value => value[0] === kind)![2], status: 'unobserved', seconds: null, end_seconds: null, note: '', affected_codes: [] }] });
  }
  function updateCoverage(id: string, patch: Partial<CoverageV4>) {
    change({ ...record, coverage: record.coverage.map(value => {
      if (value.evidence_id !== id) return value;
      const next = { ...value, ...patch };
      if (next.coverage === 'none') next.observed_seconds = 0;
      if (next.coverage === 'whole' && next.start_seconds !== null && next.end_seconds !== null) next.observed_seconds = next.end_seconds - next.start_seconds;
      return next;
    }) });
  }
  function tailChange(code: string, patch: Partial<TailV4>) {
    change({ ...record, tail_selections: record.tail_selections.map(value => value.code === code ? { ...value, ...patch } : value) });
  }
  return <section className="panel" aria-label="S1 촬영 기록">
    <div className="section-title"><h2>{item.dog_name} · {item.participant_id}</h2><button onClick={close}>닫기</button></div>
    <p>S1.1 촬영 · 입력 버전 {item.input_revision} · {session.recording_s1?.confirmed ? '확정' : '초안 / 미기록'}</p>
    {writable && <div className="toolbar recording-actions">{editing ? <><button disabled={!record.video_id} onClick={() => save(false)}>촬영 기록 초안 저장</button><button disabled={!record.video_id} onClick={() => save(true)}>촬영 기록 확정</button></> : <button onClick={() => setEditing(true)}>확정본 수정 시작</button>}
      {edit.dirty && <><span role="status">촬영 기록 · 저장 전</span><button onClick={() => { if (edit.discard()) { setRecord(initial(item)); setEditing(!session.recording_s1?.confirmed); } }}>촬영 입력 버리고 최신 값 보기</button></>}</div>}
    <p>입장 → 기준 → 혼자 → 재회 → 무시 → 걷기 → 낯선 사람 → 퇴장</p>
    <details><summary>S1 진행 안내</summary>
      <p>예정 길이는 30·20·60·30·20·30·30·30초이며 전환은 별도입니다. 실제 시작과 끝을 기록합니다. 분리 중 복지 중단 시 보호자가 즉시 돌아오고, 혼자 구간 끝과 재회 시작을 같은 실제 시각으로 기록합니다.</p>
      <p>분리 미실시는 재회도 미실시입니다. 걷기는 실제 이동과 정지 세 쌍을 기록하며 이동 시간을 균등 분할하지 않습니다. 중단·안전상 거리 예외는 사유와 함께 남깁니다.</p>
      <p>직원 신호, 실제 부름, 접촉 시작·끝, 미접촉을 구분합니다. 예정 시각으로 실제 사건을 대신하지 않습니다. 영상 가림·신체 미관찰·오디오 손상은 각각 기록하고 관찰되지 않은 반응을 0으로 채우지 않습니다.</p>
    </details>
    {session.recording && <details><summary>보존된 이전 촬영 원기록</summary><p>이전 기록은 원자료로 보존됩니다. 아래 S1 절차 확인은 실제 영상을 다시 확인하여 입력하세요.</p>
      <ul>{session.recording.segments.map(value => <li key={value.segment}>{SEGMENTS_V3.find(([id]) => id === value.segment)?.[1]} · {value.start_sec ?? '미확인'}~{value.end_sec ?? '미확인'}초 · {states[value.state]} · {value.reason}</li>)}</ul>
      <ul>{session.recording.walk_phases.map((value, index) => <li key={value.phase}>{phaseNames[index]} · {value.start_sec ?? '미확인'}~{value.end_sec ?? '미확인'}초 · {states[value.state]} · {value.reason}</li>)}</ul>
      <ul>{session.recording.events.map(value => <li key={value.event_id}>{EVENT_CHOICES.find(([id]) => id === value.kind)?.[1] ?? value.kind} · {session.videos.find(video => video.video_id === value.video_id)?.original_name} · {value.seconds ?? '미관찰'}~{value.end_seconds ?? '끝 미지정'}초 · {value.status === 'observed' ? '관찰됨' : value.status === 'not_occurred' ? '미발생' : '미관찰'} · {value.note} · {value.affected_codes.join(', ')}</li>)}</ul>
      <ul>{session.recording.video_offsets.map(value => <li key={value.video_id}>{session.videos.find(video => video.video_id === value.video_id)?.original_name} · 오프셋 {value.offset_seconds}초 · {value.confirmed ? '확인됨' : '미확인'} · {value.note}</li>)}</ul></details>}
    {writable && <><SessionEditor item={item} session={session} run={run} refresh={refresh} /><p>상단 영상 수신 보관함에서 원본·변환 파일을 수신하고 현재 회차와 카메라에 연결하세요.</p>
      <details><summary>재촬영 세션 추가</summary><button onClick={() => { if (!mayLeave()) return; void run(async () => { await api(`/cases/${item.case_id}/sessions`, 'POST', { expected_revision: item.input_revision }); await refresh('새 촬영 세션을 시작했습니다.'); }); }}>새 촬영 시작</button></details></>}
    {session.videos.some(video => video.media_status === 'storage_only') && <p>INSV 원본은 보관 중입니다. 변환 파일을 연결한 뒤 관찰 시각을 기록하세요.</p>}
    {edit.dirty && edit.view.input_revision !== item.input_revision && <p role="status">다른 변경이 저장되었습니다. 편집 시작 버전 {edit.view.input_revision}을 유지하며 현재 입력은 자동으로 덮어쓰지 않습니다.</p>}
    {record.video_id && <video src={`/api/cases/${item.case_id}/videos/${record.video_id}`} controls preload="metadata" />}
    <fieldset disabled={!writable || !editing}>
      <div className="form-grid"><label>실제 촬영 절차<select value={record.procedure_edition} onChange={event => change({ ...record, procedure_edition: event.target.value as RecordingV4['procedure_edition'] })}>
        <option value="unconfirmed">미확인</option><option value="s1_confirmed">S1 절차 확인</option><option value="legacy">이전·다른 절차</option></select></label>
        <label>절차 확인 근거<textarea value={record.procedure_note} onChange={event => change({ ...record, procedure_note: event.target.value })} /></label>
        <label>기준 영상<select value={record.video_id} onChange={event => { const id = event.target.value; change({ ...record, video_id: id,
          segments: record.segments.map(value => ({ ...value, video_id: id, start_sec: null, end_sec: null })), walk_phases: record.walk_phases.map(value => ({ ...value, video_id: id, start_sec: null, end_sec: null })),
          video_offsets: record.video_offsets.filter(value => value.video_id !== id).map(value => ({ ...value, confirmed: false })) }); }}><option value="">영상 선택</option>{videoOptions}</select></label></div>
      <p className="fine">시각은 선택 영상의 실제 초입니다. 기준 영상 변경 시 구간·국면 시각을 다시 기록하고 다른 영상의 동기화를 확인합니다. 원영상에 연결된 사건과 관찰 근거는 보존됩니다.</p>
      <details className="recording-section"><summary>실제 8구간</summary><div className="table-wrap"><table><thead><tr><th>구간·상태</th><th>실제 시작·끝</th><th>사유</th></tr></thead><tbody>{SEGMENTS_V3.map(([id, label]) => {
        const segment = record.segments.find(value => value.segment === id)!;
        const update = (patch: Partial<typeof segment>) => change({ ...record, segments: record.segments.map(value => value.segment === id ? { ...value, ...patch } : value),
          walk_phases: id === 'walk' && patch.state ? patch.state === 'not_performed' ? [] : record.walk_phases.length ? record.walk_phases : phases(record.video_id) : record.walk_phases });
        return <tr key={id}><td>{label}<select aria-label={`${label} 상태`} value={segment.state} onChange={event => { const state = event.target.value as CaptureState; update({ state, ...(state === 'not_performed' ? { start_sec: null, end_sec: null } : {}) }); }}>{Object.entries(states).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></td>
          <td><Seconds label={`${label} 시작`} value={segment.start_sec} disabled={segment.state === 'not_performed'} change={start_sec => update({ start_sec })} /><Seconds label={`${label} 끝`} value={segment.end_sec} disabled={segment.state === 'not_performed'} change={end_sec => update({ end_sec })} /></td>
          <td><input aria-label={`${label} 사유`} value={segment.reason ?? ''} onChange={event => update({ reason: event.target.value || null })} /></td></tr>;
      })}</tbody></table></div>
      </details>
      <details className="recording-section"><summary>걷기 실제 6국면</summary><p>출발 첫걸음부터 마지막 정지 끝까지 실제 경계를 입력합니다. 보호자 접근·안전상 예외를 거리값과 구분하여 기록합니다.</p>
      {record.walk_phases.map((phase, index) => { const update = (patch: Partial<typeof phase>) => change({ ...record, walk_phases: record.walk_phases.map(value => value.phase === phase.phase ? { ...value, ...patch } : value) });
        return <div className="form-grid" key={phase.phase}><label>{phaseNames[index]} 상태<select value={phase.state} onChange={event => { const state = event.target.value as CaptureState; update({ state, ...(state === 'not_performed' ? { start_sec: null, end_sec: null } : {}) }); }}>{Object.entries(states).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
          <Seconds label={`${phaseNames[index]} 시작`} value={phase.start_sec} disabled={phase.state === 'not_performed'} change={start_sec => update({ start_sec })} /><Seconds label={`${phaseNames[index]} 끝`} value={phase.end_sec} disabled={phase.state === 'not_performed'} change={end_sec => update({ end_sec })} />
          <label>{phaseNames[index]} 사유<input value={phase.reason ?? ''} onChange={event => update({ reason: event.target.value || null })} /></label>
          <label>{phaseNames[index]} 거리 예외<select value={phase.proximity_exception} onChange={event => update({ proximity_exception: event.target.value as typeof phase.proximity_exception })}><option value="unknown">미확인</option><option value="none">예외 없음</option><option value="guardian_approach">보호자가 접근</option><option value="recheck">안전상 재확인 필요</option></select></label>
          <label>{phaseNames[index]} 예외 근거<input value={phase.proximity_note ?? ''} onChange={event => update({ proximity_note: event.target.value || null })} /></label></div>;
      })}
      </details>
      <details className="recording-section"><summary>실제 사건·전환·기회</summary><label>추가할 사건<select value="" onChange={event => { if (event.target.value) addEvent(event.target.value); }}><option value="">사건 선택</option>{EVENT_CHOICES.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      {record.events.map(event => <article className="panel" key={event.event_id} aria-label={`${EVENT_CHOICES.find(([id]) => id === event.kind)?.[1]} 사건`}><h4>{EVENT_CHOICES.find(([id]) => id === event.kind)?.[1]}</h4><div className="form-grid">
        <label>사건 영상<select value={event.video_id} onChange={value => eventChange(event.event_id, { video_id: value.target.value })}>{videoOptions}</select></label>
        <label>사건 상태<select value={event.status} onChange={value => { const status = value.target.value as ActualEvent['status']; eventChange(event.event_id, { status, ...(status !== 'observed' ? { seconds: null, end_seconds: null } : {}) }); }}><option value="unobserved">미관찰·판독 불가</option><option value="observed">관찰됨</option><option value="not_occurred">미발생·미접촉</option></select></label>
        <label>해당 구간<select value={event.segment ?? ''} onChange={value => eventChange(event.event_id, { segment: value.target.value as SegmentId || null })}><option value="">전환·구간 밖</option>{SEGMENTS_V3.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <Seconds label="실제 사건 초" value={event.seconds} disabled={event.status !== 'observed'} change={seconds => eventChange(event.event_id, { seconds })} /><Seconds label="사건 끝 초" value={event.end_seconds} disabled={event.status !== 'observed'} change={end_seconds => eventChange(event.event_id, { end_seconds })} />
        <label>실제 맥락·사유<textarea value={event.note} onChange={value => eventChange(event.event_id, { note: value.target.value })} /></label>
        <CodeList key={`${event.event_id}-${edit.key}`} label="영향 항목 (쉼표로 구분)" value={event.affected_codes} change={affected_codes => eventChange(event.event_id, { affected_codes })} /></div>
        <button disabled={record.tail_selections.some(value => value.event_id === event.event_id) || record.linked_memos.some(value => value.event_ids.includes(event.event_id)) ||
          [record.safe_base_sequence?.approach_event_id, record.safe_base_sequence?.contact_event_id, record.safe_base_sequence?.exploration_event_id].includes(event.event_id)}
          onClick={() => change({ ...record, events: record.events.filter(value => value.event_id !== event.event_id) })}>사건 기록 삭제</button>
        <p className="fine">메모·꼬리·안전기지에 연결된 사건은 연결을 해제한 뒤 삭제할 수 있습니다.</p></article>)}
      </details>
      <details className="recording-section"><summary>다른 영상 수동 오프셋</summary><p>다른 영상 초 = 기준 영상 초 + 오프셋입니다. 확인 전에는 다른 영상의 사건을 공통 시각으로 사용하지 않습니다.</p>
      {videos.filter(video => video.video_id !== record.video_id).map(video => { const offset = record.video_offsets.find(value => value.video_id === video.video_id);
        const update = (patch: Partial<RecordingV4['video_offsets'][number]>) => change({ ...record, video_offsets: [...record.video_offsets.filter(value => value.video_id !== video.video_id), { video_id: video.video_id, offset_seconds: null, confirmed: false, note: '', ...offset, ...patch }] });
        return <div className="form-grid" key={video.video_id}><label>{video.original_name} 오프셋 초<input type="number" step="any" value={offset?.offset_seconds ?? ''} onChange={event => update({ offset_seconds: event.target.value === '' ? null : Number(event.target.value), confirmed: false })} /></label>
          <label>{video.original_name} 동기화 근거<input value={offset?.note ?? ''} onChange={event => update({ note: event.target.value, confirmed: false })} /></label><label className="check"><input type="checkbox" checked={offset?.confirmed ?? false} onChange={event => update({ confirmed: event.target.checked })} />{video.original_name} 수동 동기화 확인</label></div>;
      })}
      </details>
      <details className="recording-section"><summary>창별 실제 관찰 근거</summary><p>실제로 보거나 들은 범위와 초수를 기록합니다. 파일 길이나 다른 카메라의 겹친 시간을 관찰 초수로 더하지 않습니다.</p>
      <button onClick={() => change({ ...record, coverage: [...record.coverage, { evidence_id: crypto.randomUUID(), window_id: 'entry_whole', video_id: record.video_id, start_seconds: null, end_seconds: null, observed_seconds: null, coverage: 'partial', modality: 'visual', note: '' }] })}>관찰 근거 추가</button>
      {record.coverage.map(value => <article className="panel" key={value.evidence_id} aria-label="관찰 근거"><div className="form-grid">
        <label>관찰 창<select value={value.window_id} onChange={event => updateCoverage(value.evidence_id, { window_id: event.target.value })}>{Object.entries(WINDOW_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label>근거 영상<select value={value.video_id} onChange={event => updateCoverage(value.evidence_id, { video_id: event.target.value })}>{videoOptions}</select></label>
        <label>근거 종류<select value={value.modality} onChange={event => updateCoverage(value.evidence_id, { modality: event.target.value as CoverageV4['modality'] })}><option value="visual">영상 관찰</option><option value="audio">연속 오디오 청취</option></select></label>
        <Seconds label="관찰 근거 시작" value={value.start_seconds} change={start_seconds => updateCoverage(value.evidence_id, { start_seconds })} /><Seconds label="관찰 근거 끝" value={value.end_seconds} change={end_seconds => updateCoverage(value.evidence_id, { end_seconds })} />
        <label>관찰 범위<select value={value.coverage} onChange={event => updateCoverage(value.evidence_id, { coverage: event.target.value as CoverageV4['coverage'] })}><option value="partial">일부 관찰</option><option value="whole">위 범위 전체 관찰</option><option value="none">미관찰</option></select></label>
        <Seconds label="실제 관찰 초" value={value.observed_seconds} disabled={value.coverage !== 'partial'} change={observed_seconds => updateCoverage(value.evidence_id, { observed_seconds })} /><label>관찰 근거 설명<textarea value={value.note} onChange={event => updateCoverage(value.evidence_id, { note: event.target.value })} /></label></div>
        <button onClick={() => change({ ...record, coverage: record.coverage.filter(item => item.evidence_id !== value.evidence_id) })}>관찰 근거 삭제</button></article>)}
      </details>
      <details className="recording-section"><summary>선택 관찰 · 꼬리 변화</summary><p>첫 명확한 고개 전환 전 2초·후 3초와 같은 자세·움직임, 앞뒤 꼬리 가시성을 확인합니다. 가림·걷기 전환에서는 값을 만들지 않습니다.</p>
      {(['바54', '바55'] as const).map(code => { const selected = record.tail_selections.find(value => value.code === code), kind = code === '바54' ? 'reunion_head_turn' : 'stranger_head_turn';
        const matching = record.events.filter(event => event.kind === kind);
        return <article className="panel" key={code}><h4>{code} · {code === '바54' ? '재회' : '낯선 사람'} 꼬리 변화</h4>{!selected ? <button disabled={!matching.length} onClick={() => change({ ...record, tail_selections: [...record.tail_selections, { code, event_id: matching[0].event_id, first_clear_confirmed: false, same_posture: null, same_movement: null, tail_visible_before: null, tail_visible_after: null, note: '' }] })}>{code} 선택 관찰 기록</button> : <><div className="form-grid">
          <label>{code} 고개 전환 사건<select value={selected.event_id} onChange={event => tailChange(code, { event_id: event.target.value, first_clear_confirmed: false })}>{matching.map(event => <option key={event.event_id} value={event.event_id}>{event.seconds ?? '미관찰'}초 · {event.note}</option>)}</select></label>
          <label className="check"><input type="checkbox" checked={selected.first_clear_confirmed} onChange={event => tailChange(code, { first_clear_confirmed: event.target.checked })} />{code} 첫 명확한 전환 확인</label>
          {([['same_posture', '같은 자세'], ['same_movement', '같은 움직임'], ['tail_visible_before', '전 2초 꼬리 관찰'], ['tail_visible_after', '후 3초 꼬리 관찰']] as const).map(([key, label]) => <BooleanFact key={key} label={`${code} ${label}`} value={selected[key]} change={value => tailChange(code, { [key]: value })} />)}
          <label>{code} 선택 근거<textarea value={selected.note} onChange={event => tailChange(code, { note: event.target.value })} /></label></div><button onClick={() => change({ ...record, tail_selections: record.tail_selections.filter(value => value.code !== code) })}>{code} 선택 관찰 해제</button></>}</article>;
      })}
      </details>
      <details className="recording-section"><summary>개59 연결 메모</summary><button onClick={() => change({ ...record, linked_memos: [...record.linked_memos, { code: '개59', memo_id: crypto.randomUUID(), text: '', item_codes: [], event_ids: [] }] })}>연결 메모 추가</button>
      {record.linked_memos.map(memo => { const update = (patch: Partial<typeof memo>) => change({ ...record, linked_memos: record.linked_memos.map(value => value.memo_id === memo.memo_id ? { ...value, ...patch } : value) });
        return <article className="panel" key={memo.memo_id}><label>개59 메모<textarea value={memo.text} onChange={event => update({ text: event.target.value })} /></label><CodeList key={`${memo.memo_id}-${edit.key}`} label="메모 연결 항목" value={memo.item_codes} change={item_codes => update({ item_codes })} />
          <label>메모 연결 사건<select multiple value={memo.event_ids} onChange={event => update({ event_ids: Array.from(event.target.selectedOptions, value => value.value) })}>{record.events.map(event => <option key={event.event_id} value={event.event_id}>{EVENT_CHOICES.find(([id]) => id === event.kind)?.[1]} · {event.note}</option>)}</select></label>
          <button onClick={() => change({ ...record, linked_memos: record.linked_memos.filter(value => value.memo_id !== memo.memo_id) })}>연결 메모 삭제</button></article>;
      })}
      </details>
      <details className="recording-section"><summary>안전기지 실제 순서</summary><p>보호자 접근 → 접촉 → 탐색 재개의 실제 사건을 연결합니다. 탐색 분류만으로 순서를 만들지 않습니다.</p>
      {!record.safe_base_sequence ? <button onClick={() => change({ ...record, safe_base_sequence: { approach_event_id: null, contact_event_id: null, exploration_event_id: null, note: '' } })}>안전기지 사건 연결</button> : <><div className="form-grid">
        {([['approach_event_id', 'guardian_approach', '보호자 접근'], ['contact_event_id', 'guardian_contact', '보호자 접촉'], ['exploration_event_id', 'exploration_resumed', '탐색 재개']] as const).map(([key, kind, label]) => <label key={key}>안전기지 {label}<select value={record.safe_base_sequence![key] ?? ''} onChange={event => change({ ...record, safe_base_sequence: { ...record.safe_base_sequence!, [key]: event.target.value || null } })}><option value="">미확인</option>{record.events.filter(event => event.kind === kind).map(event => <option key={event.event_id} value={event.event_id}>{event.seconds ?? '미관찰'}초 · {event.note}</option>)}</select></label>)}
        <label>안전기지 순서 근거<textarea value={record.safe_base_sequence.note} onChange={event => change({ ...record, safe_base_sequence: { ...record.safe_base_sequence!, note: event.target.value } })} /></label></div><button onClick={() => change({ ...record, safe_base_sequence: null })}>안전기지 연결 해제</button></>}
      </details>
    </fieldset>
    {viewError && <p role="alert">{viewError}</p>}
    {view && <details><summary>저장된 실제 관찰창 확인</summary>{edit.dirty && <p>아래는 마지막 저장본의 창입니다. 현재 편집 내용을 저장하면 다시 계산합니다.</p>}<div className="table-wrap"><table><thead><tr><th>관찰창</th><th>기준 영상 초</th><th>상태</th><th>전체 관찰 근거</th></tr></thead><tbody>{view.windows.map(window => <tr key={window.window_id}><td>{WINDOW_NAMES[window.window_id]}</td><td>{window.start_seconds ?? '미확인'}~{window.end_seconds ?? '미확인'}</td><td>{statusNames[window.status] ?? '확인 필요'}</td><td>영상 {window.whole_visual_observed ? '확인' : '미확인'} · 오디오 {window.whole_audio_observed ? '확인' : '미확인'}</td></tr>)}</tbody></table></div></details>}
  </section>;
}
