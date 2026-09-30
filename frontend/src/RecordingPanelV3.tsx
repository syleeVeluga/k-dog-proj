import { useEffect, useState } from 'react';
import { api } from './api';
import { mayLeave, useEditBase } from './Editing';
import { SessionEditor } from './MetadataEditors';
import { VideoUpload } from './VideoUpload';
import { SEGMENTS_V3, sessionOf } from './types';
import type { ActualEvent, CaptureState, Case, RecordingV3, Run, SegmentId } from './types';

const states: Record<CaptureState, string> = { performed: '정상 실시', shortened: '단축', not_performed: '미실시', welfare_stopped: '복지 중단' };
const phaseNames = ['이동1', '정지1', '이동2', '정지2', '이동3', '정지3'];
const phaseIds = ['move_1', 'stop_1', 'move_2', 'stop_2', 'move_3', 'stop_3'];
const events: [string, string, SegmentId | null][] = [
  ['floor_contact', '바닥 첫 접촉', 'entry'], ['object_near', '물건1m 진입', 'entry'], ['object_stop', '물건 앞 정지 (끝도 기록)', 'entry'], ['object_contact', '첫 코 접촉', 'entry'],
  ['object_removed', '물건 제거', null], ['guardian_speech', '보호자 말', null], ['guardian_gesture', '보호자 손짓', null],
  ['staff_signal', '직원 신호 (예정 접촉 신호 포함)', null], ['staff_stop', '직원 중단 신호', null], ['food', '먹이', null], ['route_deviation', '경로 이탈', null],
  ['occlusion', '가림', null], ['audio_loss', '녹음 손상 (실제 범위)', null], ['welfare_stop', '중단', null], ['welfare_action', '중단 뒤 조치', null],
  ['reunion_name', '재회 실제 부름', 'reunion'], ['reunion_contact_start', '재회 실제 접촉 시작', 'reunion'], ['reunion_contact_end', '재회 실제 접촉 끝', 'reunion'],
  ['stranger_gate_wait', '안전문 밖 대기', 'stranger'], ['stranger_enter', '요원 입실', 'stranger'], ['stranger_approach', '요원 접근', 'stranger'],
  ['stranger_name', '요원 실제 부름', 'stranger'], ['stranger_contact_start', '요원 실제 접촉 시작', 'stranger'], ['stranger_contact_end', '요원 실제 접촉 끝', 'stranger'], ['stranger_wait', '요원 대기 (실제 시작/끝)', 'stranger'], ['stranger_exit', '요원 퇴장', 'stranger'],
  ['walk_name', '걷기 전 이름', null], ['walk_to_s_start', 'S로 이동 시작', null], ['walk_to_s_end', 'S로 이동 끝', null],
  ['walk_seated', '걷기 뒤 착석', null], ['transition_wait_start', '전환 대기 시작', null], ['transition_wait_end', '전환 대기 끝', null], ['leash_attach', '목줄 채우기', null],
];
const phases = (videoId: string) => phaseIds.map(phase => ({ phase, video_id: videoId, state: 'performed' as CaptureState, start_sec: null, end_sec: null, reason: null }));
function initial(item: Case): RecordingV3 {
  const session = sessionOf(item); const videoId = session.videos[0]?.video_id ?? '';
  return session.recording ? { ...session.recording, confirmed: false } : { video_id: videoId, confirmed: false,
    segments: SEGMENTS_V3.map(([segment]) => ({ segment, video_id: videoId, state: 'performed', start_sec: null, end_sec: null, reason: null })),
    walk_phases: phases(videoId), events: [], video_offsets: [] };
}
const number = (value: string) => value.trim() === '' ? null : Number(value);

export function RecordingPanelV3({ item, writable, run, refresh, close }: { item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; close: () => void }) {
  const session = sessionOf(item);
  const edit = useEditBase(item);
  const [record, setRecord] = useState<RecordingV3>(() => initial(item));
  const [loadedRevision, setLoadedRevision] = useState(item.input_revision);
  const [editing, setEditing] = useState(!session.recording?.confirmed);
  useEffect(() => { if (!edit.dirty) { setRecord(initial(item)); setLoadedRevision(item.input_revision); setEditing(!session.recording?.confirmed); } }, [item.input_revision]);
  const change = (next: RecordingV3) => { edit.change(); setRecord({ ...next, confirmed: false }); };
  function save(confirm: boolean) {
    void run(async () => {
      await api(`/cases/${item.case_id}/sessions/${session.session_id}/recording`, 'PUT', { expected_revision: edit.view.input_revision, recording: record, confirm });
      edit.reset(); setEditing(!confirm); await refresh(confirm ? '실제 촬영 기록을 확정했습니다.' : '실제 촬영 기록을 초안 저장했습니다.');
    });
  }
  function addEvent(kind: string) {
    const [, , segment] = events.find(event => event[0] === kind)!;
    change({ ...record, events: [...record.events, { event_id: crypto.randomUUID(), kind, segment, video_id: record.video_id,
      status: 'observed', seconds: null, end_seconds: null, note: '', affected_codes: [] }] });
  }
  const eventChange = (id: string, patch: Partial<ActualEvent>) => change({ ...record, events: record.events.map(event => event.event_id === id ? { ...event, ...patch } : event) });
  return <section className="panel" aria-label="신판 촬영 기록">
    <div className="section-title"><h2>{item.dog_name} · {item.participant_id}</h2><button onClick={close}>닫기</button></div>
    <p className="fine">9월 29일 촬영 · 입력 버전 {item.input_revision} · {session.recording?.confirmed ? '확정' : '초안 / 미기록'}</p>
    <p>입장 → 기준 → 분리 → 재회 → 무시 → 걷기 → 낯선 사람 → 퇴장</p>
    <details><summary>진행 안내 (04 절차 기준)</summary>
      <p>구간은 약30·20·60·30·20·30·30·30초, 합계 약250초이며 전환 시간은 별도입니다. 실제 경계를 기록하고 예정값으로 채우지 않습니다. 복지 중단을 우선하며 분리 중 중단하면 보호자가 즉시 돌아옵니다.</p>
      <p>재회 전반0~15초는 착석·대기, 15초 직원 신호 뒤 이름1회·평소 접촉입니다. 신호와 실제 접촉은 별도 사건입니다. 후반15초 몸 상태는 접촉창과 다릅니다.</p>
      <p>분리 초기0~10초·이후10~60초·전체 창과 재회 전반0~15초·후반15~30초·실제 접촉창·전체 발성창은 따로 사용합니다. 단축 시 개10은 원본 빈칸 규칙을 따르며 후기50초 문턱을 비례 축소하지 않습니다. 개18은 후반15초 전체 몸 상태입니다.</p>
      <p>걷기 전 이름·S로 이동과 종료 뒤 착석은 전환입니다. S 첫걸음 이후 이동/정지3쌍을 기록합니다. 각 정지 약5초, A–S와S–C는2.75m입니다.</p>
      <p>착석 뒤 전환 대기5초 후 요원 안전문 밖0~10초, 입실10~12초, 접근12~16초, 이름16초·20초까지 대기, 접촉20~23초 뒤25초까지 대기 또는 미접촉20~25초, 퇴장25~30초가 안내입니다. 실제 사건을 따로 기록합니다. 간식·장난감은 사용하지 않습니다.</p>
      <p>06 별도 보호자 안내문은 제공되지 않았습니다. 현장 대본은04와 일치시켜 읽고 임의 격려·추가 신호를 하지 않습니다. 한 사건으로 공격성·보호자 성격을 단정하지 않습니다.</p>
    </details>
    {writable && <><SessionEditor item={item} session={session} run={run} refresh={refresh} /><VideoUpload item={item} session={session} refresh={refresh} />
      <details><summary>재촬영 세션 추가</summary><button onClick={() => { if (!mayLeave()) return; void run(async () => { await api(`/cases/${item.case_id}/sessions`, 'POST', { expected_revision: item.input_revision }); await refresh('새 촬영 세션을 시작했습니다.'); }); }}>새 촬영 시작</button></details></>}
    <p className="mono">{session.videos.length} FILES</p>
    {edit.dirty && edit.view.input_revision !== item.input_revision && <p role="status">다른 변경이 저장되었습니다. 편집 시작 버전 {edit.view.input_revision}을 유지하며 저장 시409로 거절됩니다.</p>}
    {record.video_id && <video src={`/api/cases/${item.case_id}/videos/${record.video_id}`} controls preload="metadata" />}
    <fieldset disabled={!writable || !editing}>
      <label>기준 영상<select aria-label="기준 영상" value={record.video_id} onChange={e => change({ ...record, video_id: e.target.value,
        segments: record.segments.map(window => ({ ...window, video_id: e.target.value })), walk_phases: record.walk_phases.map(phase => ({ ...phase, video_id: e.target.value })),
        video_offsets: record.video_offsets.filter(offset => offset.video_id !== e.target.value).map(offset => ({ ...offset, confirmed: false })) })}>
        <option value="">영상 선택</option>{session.videos.map(video => <option key={video.video_id} value={video.video_id}>{video.original_name}</option>)}</select></label>
      <p className="fine">시각은 선택 영상의 실제 초입니다. 기준 영상을 바꾸면 모든 경계를 재검토하세요. 미실시는 시작/끝을 비우고 사유를 적습니다. 분리 미실시면 재회도 미실시입니다. 실제 분리 중 중단은 분리 끝과 즉시 재회 시작을 기록합니다.</p>
      <div className="table-wrap"><table><thead><tr><th>구간 / 상태</th><th>시작·끝 초</th><th>사유</th></tr></thead><tbody>{SEGMENTS_V3.map(([id, label]) => {
        const window = record.segments.find(window => window.segment === id)!;
        const update = (patch: Partial<typeof window>) => change({ ...record, segments: record.segments.map(value => value.segment === id ? { ...value, ...patch } : value),
          walk_phases: id === 'walk' && patch.state ? patch.state === 'not_performed' ? [] : record.walk_phases.length ? record.walk_phases : phases(record.video_id) : record.walk_phases });
        return <tr key={id}><td>{label}<select aria-label={`${label} 상태`} value={window.state} onChange={e => { const state = e.target.value as CaptureState; update({ state, ...(state === 'not_performed' ? { start_sec: null, end_sec: null } : {}) }); }}>{Object.entries(states).map(([state, name]) => <option key={state} value={state}>{name}</option>)}</select></td>
          <td>{(['start_sec', 'end_sec'] as const).map((key, index) => <input key={key} type="number" min="0" step="any" disabled={window.state === 'not_performed'} aria-label={`${label} ${index ? '끝' : '시작'}`} value={window[key] ?? ''} onChange={e => update({ [key]: number(e.target.value) })} />)}</td>
          <td><input aria-label={`${label} 사유`} value={window.reason ?? ''} maxLength={2000} onChange={e => update({ reason: e.target.value || null })} /></td></tr>;
      })}</tbody></table></div>
      <h3>걷기 실제6국면</h3><p className="fine">출발 거리 개37은 걷기 첫걸음의 근거를 사용합니다. 몸길이 보정 Q08은 미확정입니다.</p>
      {record.walk_phases.map((phase, i) => { const update = (patch: Partial<typeof phase>) => change({ ...record, walk_phases: record.walk_phases.map(value => value.phase === phase.phase ? { ...value, ...patch } : value) });
        return <div className="form-grid" key={phase.phase}><label>{phaseNames[i]} 상태<select value={phase.state} onChange={e => { const state = e.target.value as CaptureState; update({ state, ...(state === 'not_performed' ? { start_sec: null, end_sec: null } : {}) }); }}>{Object.entries(states).map(([state, name]) => <option key={state} value={state}>{name}</option>)}</select></label>
          {(['start_sec', 'end_sec'] as const).map((key, index) => <label key={key}>{phaseNames[i]} {index ? '끝' : '시작'}<input type="number" min="0" step="any" disabled={phase.state === 'not_performed'} value={phase[key] ?? ''} onChange={e => update({ [key]: number(e.target.value) })} /></label>)}
          <label>{phaseNames[i]} 사유<input value={phase.reason ?? ''} onChange={e => update({ reason: e.target.value || null })} /></label></div>;
      })}
      <h3>실제 사건·전환·기회</h3><p className="fine">예정 신호는 직원 신호로, 실제 부름/접촉은 각각 기록합니다. 미접촉·판독 불가는 시각 없이 명시합니다. 중단 사건을 추가해도 이미 관찰한 접촉은 삭제하지 않습니다.</p>
      <label>추가할 사건<select aria-label="추가할 사건" value="" onChange={e => { if (e.target.value) addEvent(e.target.value); }}><option value="">사건 선택</option>{events.map(([kind, name]) => <option key={kind} value={kind}>{name}</option>)}</select></label>
      {record.events.map(event => <div className="panel" key={`${event.event_id}-${edit.key}-${loadedRevision}`}><h4>{events.find(value => value[0] === event.kind)?.[1]}</h4><div className="form-grid">
        <label>사건 영상<select aria-label="사건 영상" value={event.video_id} onChange={e => eventChange(event.event_id, { video_id: e.target.value })}>{session.videos.map(video => <option key={video.video_id} value={video.video_id}>{video.original_name}</option>)}</select></label>
        <label>사건 상태<select aria-label="사건 상태" value={event.status} onChange={e => { const status = e.target.value as ActualEvent['status']; eventChange(event.event_id, { status, ...(status !== 'observed' ? { seconds: null, end_seconds: null } : {}) }); }}><option value="observed">관찰됨</option><option value="not_occurred">미발생·미접촉</option><option value="unobserved">판독 불가·미관찰</option></select></label>
        <label>해당 구간<select aria-label="해당 구간" value={event.segment ?? ''} onChange={e => eventChange(event.event_id, { segment: (e.target.value || null) as SegmentId | null })}><option value="">전환 (본 구간 제외)</option>{SEGMENTS_V3.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label>실제 사건 초<input type="number" min="0" step="any" disabled={event.status !== 'observed'} value={event.seconds ?? ''} onChange={e => eventChange(event.event_id, { seconds: number(e.target.value) })} /></label>
        <label>사건 끝 초 (지속 사건만)<input type="number" min="0" step="any" disabled={event.status !== 'observed'} value={event.end_seconds ?? ''} onChange={e => eventChange(event.event_id, { end_seconds: number(e.target.value) })} /></label>
        <label>실제 맥락·사유<textarea value={event.note} maxLength={2000} onChange={e => eventChange(event.event_id, { note: e.target.value })} /></label>
        <label>영향 항목 (예: 개10,보22)<input defaultValue={event.affected_codes.join(',')} onChange={e => eventChange(event.event_id, { affected_codes: e.target.value.split(',').map(code => code.trim()).filter(Boolean) })} /></label>
      </div><button onClick={() => change({ ...record, events: record.events.filter(value => value.event_id !== event.event_id) })}>사건 기록 삭제</button></div>)}
      <h3>다른 영상 수동 오프셋</h3><p className="fine">다른 영상 초 = 기준 영상 초 + 오프셋입니다. 확인 전 사건 시각은 원기록 초안으로만 보존하고 확정에 사용하지 않습니다.</p>
      {session.videos.filter(video => video.video_id !== record.video_id).map(video => { const offset = record.video_offsets.find(value => value.video_id === video.video_id);
        const update = (patch: Partial<NonNullable<typeof offset>>) => change({ ...record, video_offsets: [...record.video_offsets.filter(value => value.video_id !== video.video_id), { video_id: video.video_id, offset_seconds: 0, confirmed: false, note: '', ...offset, ...patch }] });
        return <div className="form-grid" key={video.video_id}><label>{video.original_name} 오프셋 초<input type="number" step="any" value={offset?.offset_seconds ?? ''} onChange={e => update({ offset_seconds: Number(e.target.value), confirmed: false })} /></label>
          <label>오프셋 근거<input value={offset?.note ?? ''} onChange={e => update({ note: e.target.value })} /></label><label className="check"><input type="checkbox" checked={offset?.confirmed ?? false} onChange={e => update({ confirmed: e.target.checked })} />수동 동기화 확인</label></div>;
      })}
    </fieldset>
    {writable && <div className="toolbar">{editing ? <><button disabled={!record.video_id} onClick={() => save(false)}>촬영 기록 초안 저장</button><button disabled={!record.video_id} onClick={() => save(true)}>촬영 기록 확정</button></> : <button onClick={() => setEditing(true)}>확정본 수정 시작</button>}
      {edit.dirty && <><span role="status">촬영 기록 · 저장 전</span><button onClick={() => { if (edit.discard()) { setRecord(initial(item)); setEditing(!session.recording?.confirmed); } }}>촬영 입력 버리고 최신 값 보기</button></>}</div>}
  </section>;
}
