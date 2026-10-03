import { useEffect, useRef, useState } from 'react';
import { api, ApiError, accessLost } from './api';
import { sessionOf, type Case, type Run } from './types';
import { WINDOW_NAMES } from './recordingTypesV4';
import type { BatchV4, ClipFileV4, PhysicalClipV4, PreprocessStatusV4, TimeRangeV4, WindowV4 } from './preprocessTypesV4';

const states: Record<string, string> = {
  not_ready: '촬영 기록 확인 필요', ready: '실행 가능', running: '진행 중', interrupted: '중단됨', failed: '실패', complete: '완성', partial: '일부만 완성',
  available: '영상 있음', missing: '영상 없음', offset_unconfirmed: '오프셋 미확인', camera_unassigned: '카메라 미등록', conversion_required: 'MP4 변환 필요', no_frames: '실제 프레임 없음',
  unobserved: '관찰 미확인', whole_observed: '전체 관찰 기록', partial_observed: '일부 관찰 기록', occluded: '영상 가림', body_unobserved: '신체 미관찰',
  confirmed: '실제 창 확정', not_performed: '미수행', no_opportunity: '기회 없음', policy_pending: '규칙 미확정', compatibility_pending: '절차 확인 필요',
  operator_selected_audio: '운영자가 선택한 영상', operator_selected_audio_unavailable: '선택한 영상의 오디오를 사용할 수 없음',
  maximum_available_audio_then_camera_priority: '가용 시간이 긴 오디오 우선, 같으면 카메라 우선순위', no_usable_audio: '사용할 오디오 없음',
  audio_absent_or_unavailable: '오디오 없음 또는 사용 불가', ai_no_frames: 'AI용 실제 프레임 없음', no_actual_frames_in_window: '창 안에 실제 프레임 없음',
  ai_encoding_failed: 'AI용 클립 제작 실패', source_decode_failed: '영상 해독 실패',
};
const label = (value: string) => states[value] ?? value;
const seconds = (value: number | null) => value === null ? '미확인' : `${Number(value.toFixed(3))}초`;
const range = (start: number | null, end: number | null) => `${seconds(start)} ~ ${seconds(end)}`;
const ranges = (values: TimeRangeV4[]) => values.length ? values.map(value => range(value.start_seconds, value.end_seconds)).join(', ') : '없음';
const nameOf = (id: string) => WINDOW_NAMES[id] ?? id;

export function PreprocessingPanelV4({ item, writable, run, refresh }: {
  item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>;
}) {
  const session = sessionOf(item), path = `/cases/${item.case_id}/sessions/${session.session_id}/preprocess-s1`;
  const [status, setStatus] = useState<PreprocessStatusV4 | null>(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [loading, setLoading] = useState(false);
  const [priority, setPriority] = useState(() => [...new Set(['CAM1', 'CAM2', 'CAM3', ...session.videos.flatMap(video => video.camera_id ? [video.camera_id] : [])])]);
  const [audio, setAudio] = useState(''), [clipId, setClipId] = useState(''), [variant, setVariant] = useState<'original' | 'ai'>('original');
  const alive = useRef(true), running = useRef(false), sequence = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; sequence.current++; }; }, []);
  async function load(clearError = true) {
    const current = ++sequence.current;
    setLoading(true);
    try {
      const value = await api<PreprocessStatusV4>(path);
      if (alive.current && current === sequence.current) { setStatus(value); if (clearError) setError(''); }
    } catch (value) {
      if (alive.current && current === sequence.current) { setStatus(null); setError(value instanceof Error ? value.message : '전처리 상태를 불러오지 못했습니다.'); }
    } finally { if (alive.current && current === sequence.current) setLoading(false); }
  }
  useEffect(() => { void load(false); }, [path, item.input_revision]);
  const batch = status?.result;
  const stale = !!status && (status.outdated || status.input_revision !== item.input_revision);
  const blocked = busy || loading || !status?.ready || status.status === 'running' || status.input_revision !== item.input_revision;
  const sameSettings = !!batch && audio === (batch.request.audio_video_id ?? '') && priority.join('|') === batch.request.camera_priority.join('|');
  const clip = batch?.clips.find(value => value.clip_id === clipId) ?? batch?.clips[0];
  const videoName = (id: string | null) => {
    if (!id) return '없음';
    const video = batch?.source_metadata.find(value => value.video_id === id) ?? session.videos.find(value => value.video_id === id);
    return video ? `${video.camera_id ?? '카메라 미등록'} · ${video.original_name}` : id;
  };
  function move(camera: string, direction: number) {
    const next = [...priority], index = next.indexOf(camera), target = index + direction;
    if (target >= 0 && target < next.length) { [next[index], next[target]] = [next[target], next[index]]; setPriority(next); }
  }
  function start(reuse: boolean) {
    if (running.current || blocked || !writable || reuse && (!status?.result_pointer || stale || !sameSettings)) return;
    running.current = true; setBusy(true); setError('');
    const request = { request_id: crypto.randomUUID(), expected_revision: item.input_revision, camera_priority: priority,
      audio_video_id: audio || null, ai_frames_per_second: 1, reuse: reuse ? status!.result_pointer : null };
    void run(async () => {
      try {
        await api<BatchV4>(path, 'POST', request);
        if (alive.current) { await load(); await refresh(reuse ? '검증된 전처리 결과를 재사용했습니다.' : '새 전처리 결과를 만들었습니다.'); }
      } catch (value) {
        if (alive.current) {
          if (accessLost(value)) setStatus(null);
          const message = value instanceof Error ? value.message : '전처리 요청에 실패했습니다.';
          setError(value instanceof ApiError && value.status === 409 ? `${message} 상태와 최신 입력을 새로고침한 뒤 다시 실행하세요.` : message);
        }
      } finally { running.current = false; if (alive.current) setBusy(false); }
    });
  }
  return <section className="panel" aria-label="S1 다중 카메라 전처리" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <div className="section-head"><h2>다중 카메라 전처리</h2><button type="button" disabled={busy || loading} onClick={() => { void run(async () => { await refresh(); await load(); }); }}>전처리 상태 새로고침</button></div>
    <p>촬영 기록의 실제 창을 카메라별 클립으로 만듭니다. 겹치는 클립은 함께 제작하고, 항목별 관찰창과 가림·손실 근거는 각각 유지합니다.</p>
    <p className="fine">카메라 배치는 D01 확인 대기입니다. 오프셋이 확인되지 않은 카메라는 클립 제작에서 제외됩니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <p role="status">{busy ? '전처리 진행 중 · 완료 후 상태가 갱신됩니다.' : loading ? '전처리 상태 확인 중…' : status ? `${label(status.status)} · ${status.message}` : '전처리 상태를 확인하세요.'}</p>
    {stale && <p className="warning">이전 입력 기준 결과입니다. 결과 기준 {batch?.input_revision ?? '미확인'} / 최신 입력 {item.input_revision}. 새 입력으로 다시 제작해야 합니다.</p>}
    <fieldset disabled={!writable || busy || status?.status === 'running'}><legend>제작 설정</legend>
      <p>원본용 클립은 실제 원본 프레임을 보존합니다. AI용 클립은 매 1초의 실제 프레임 1장을 선택하고 연속 오디오를 보존합니다. 공급자 요청 FPS·리사이즈는 별도 단계입니다.</p>
      <div className="table-wrap"><table><caption>카메라 우선순위</caption><thead><tr><th>순서</th><th>카메라</th><th>변경</th></tr></thead><tbody>{priority.map((camera, index) => <tr key={camera}><td>{index + 1}</td><td>{camera}</td><td><button type="button" aria-label={`${camera} 우선순위 올리기`} disabled={index === 0} onClick={() => move(camera, -1)}>위로</button> <button type="button" aria-label={`${camera} 우선순위 내리기`} disabled={index === priority.length - 1} onClick={() => move(camera, 1)}>아래로</button></td></tr>)}</tbody></table></div>
      <label>대표 오디오 선택<select value={audio} onChange={event => setAudio(event.target.value)}><option value="">창별 가용 시간이 긴 영상, 같으면 카메라 우선순위</option>{session.videos.filter(video => video.media_status !== 'storage_only').map(video => <option key={video.video_id} value={video.video_id}>{video.camera_id ?? '카메라 미등록'} · {video.original_name}</option>)}</select></label>
      <p className="fine">여러 카메라의 같은 소리를 중복 합산하지 않습니다. 오디오 가용 초는 실제 청취 초나 발성 초를 뜻하지 않습니다.</p>
    </fieldset>
    {writable && <div className="actions"><button type="button" disabled={blocked} onClick={() => start(false)}>새 클립으로 전처리</button>
      <button type="button" disabled={blocked || stale || !status?.result_pointer || !sameSettings} onClick={() => start(true)}>검증된 결과 재사용</button>
      {batch && <button type="button" disabled={busy} onClick={() => { setPriority([...batch.request.camera_priority]); setAudio(batch.request.audio_video_id ?? ''); }}>이 결과의 설정 불러오기</button>}</div>}
    {batch && <>
      <h3>저장된 결과 · {label(batch.status)}</h3><p>입력 {batch.input_revision} · {new Date(batch.created_at).toLocaleString()} · 물리 클립 {batch.clips.length}개 · 항목 관찰창 {batch.windows.length}개</p>
      {batch.reuse_manifest && <p>해시를 검증한 기존 결과를 명시적으로 재사용했습니다.</p>}
      {!sameSettings && <p className="fine">현재 제작 설정이 저장된 결과와 다릅니다. 재사용하려면 이 결과의 설정을 불러오세요.</p>}
      <details><summary>입력·원본·제작 출처 확인</summary><p>결과 ID: {batch.batch_id}</p><p>입력: {batch.input.ref}<br />SHA-256: {batch.input.hash}</p>
        <p>제작기: {batch.encoder_version}</p><p>제작 호환성 SHA-256: {batch.compatibility_hash}</p>
        {batch.source_metadata.map(video => <p key={video.video_id}>{videoName(video.video_id)} · {video.source_kind === 'original' ? '촬영 원본' : video.source_kind === 'received_conversion' ? '전달받은 변환본' : '보존 영상'}<br />{video.storage_ref}<br />SHA-256: {video.sha256}</p>)}
        {batch.source_files.filter(file => !batch.source_metadata.some(video => video.storage_ref === file.ref)).map(file => <p key={file.ref}>변환 부모 원본: {file.ref}<br />SHA-256: {file.hash}</p>)}
        {Object.entries(batch.asset_hashes).map(([key, hash]) => <p key={key}>{key} SHA-256: {hash}</p>)}
        {batch.reuse_manifest && <p>재사용 출처: {batch.reuse_manifest.ref}<br />SHA-256: {batch.reuse_manifest.hash}</p>}
      </details>
      <h3>항목별 관찰창</h3><p className="fine">아래 시각·손실은 기준 영상의 초입니다. 파일 가용성과 실제 관찰 기록을 구분해 표시합니다.</p>
      {batch.windows.map(window => <WindowDetails key={window.window.window_id} value={window} batch={batch} videoName={videoName} choose={id => { setClipId(id); setVariant('original'); }} />)}
      <h3>물리 클립 미리보기</h3>
      {clip ? <><label>미리볼 클립<select value={clip.clip_id} onChange={event => setClipId(event.target.value)}>{batch.clips.map(value => <option key={value.clip_id} value={value.clip_id}>{value.camera_id} · 원본 {range(value.source_start_seconds, value.source_end_seconds)} · {label(value.status)}</option>)}</select></label>
        <label>클립 제작 방식<select value={variant} onChange={event => setVariant(event.target.value as 'original' | 'ai')}><option value="original">원본 FPS 클립</option><option value="ai">AI용 1초 1프레임 클립</option></select></label>
        <ClipPreview key={`${batch.batch_id}:${clip.clip_id}:${variant}`} clip={clip} file={clip[variant]} url={`/api${path}/${batch.batch_id}/clips/${clip.clip_id}/${variant}`} variant={variant} /></> : <p>제작된 물리 클립이 없습니다. 창별 사유를 확인하세요.</p>}
    </>}
  </section>;
}

function WindowDetails({ value, batch, videoName, choose }: { value: WindowV4; batch: BatchV4; videoName: (id: string | null) => string; choose: (id: string) => void }) {
  const window = value.window;
  return <details aria-label={`${nameOf(window.window_id)} 전처리 결과`}><summary>{nameOf(window.window_id)} · {label(window.status)} · {range(window.start_seconds, window.end_seconds)}</summary>
    <p>항목: {value.item_codes.join(', ') || '연결 항목 없음'}</p>
    <p>영상 가용 {seconds(value.media_available_seconds)} · 대표 오디오 가용 {seconds(value.audio_available_seconds)} · 실제 청취·발성 초: 아직 판정하지 않음</p>
    <p>대표 오디오: {videoName(value.representative_audio_video_id)} · {label(value.audio_selection_reason)}</p><p>오디오 손실: {ranges(value.audio_loss_ranges)}</p>
    {window.reasons.length > 0 && <p>창 근거: {window.reasons.map(label).join(', ')}</p>}
    <div className="table-wrap"><table><thead><tr><th>카메라·동기화</th><th>파일 가용성·관찰</th><th>기준 영상 시각</th><th>물리 클립</th></tr></thead><tbody>{value.views.map(view => <tr key={view.video_id}>
      <td>{videoName(view.video_id)}<br />오프셋 {seconds(view.offset_seconds)}<br />원본 = 기준 + 오프셋</td>
      <td>{label(view.availability)} / {label(view.visual_state)}{view.reasons.length > 0 && <p>{view.reasons.map(label).join(', ')}</p>}
        {view.quality_event_ids.map(id => { const event = batch.recording.events.find(row => row.event_id === id); return event ? <p key={id}>{event.kind === 'occlusion' ? '영상 가림' : event.kind === 'body_not_visible' ? '신체 미관찰' : '오디오 손실'}: {event.note} {event.affected_codes.join(', ')}</p> : null; })}</td>
      <td>영상 {ranges(view.visual_ranges)}<br />오디오 {ranges(view.audio_ranges)}</td>
      <td>{view.clip_ids.length ? view.clip_ids.map((id, index) => <button type="button" key={id} onClick={() => choose(id)}>{view.camera_id ?? '영상'} 클립 {index + 1} 보기</button>) : '제작 없음'}</td>
    </tr>)}</tbody></table></div>
  </details>;
}

function ClipPreview({ clip, file, url, variant }: { clip: PhysicalClipV4; file: ClipFileV4 | null; url: string; variant: 'original' | 'ai' }) {
  const video = useRef<HTMLVideoElement>(null), [frame, setFrame] = useState(0), [error, setError] = useState('');
  if (!file) return <p role="status">{variant === 'ai' ? 'AI용' : '원본 FPS'} 클립 없음 · {label(clip.reason ?? clip.status)}</p>;
  return <article aria-label="전처리 클립 미리보기"><p>{clip.camera_id} · 원본 범위 {range(clip.source_start_seconds, clip.source_end_seconds)} · 연결 창 {clip.window_ids.map(nameOf).join(', ')}</p>
    <video ref={video} controls preload="metadata" src={url} style={{ width: '100%', maxHeight: 420 }} onError={() => setError('클립을 재생할 수 없습니다. 접근 권한·원본 상태를 확인하고 전처리 상태를 새로고침하세요.')} />
    {error && <p role="alert">{error}</p>}
    <p>{variant === 'ai' ? 'AI용: 1초마다 실제 프레임 최대 1장' : '원본 FPS: 실제 원본 프레임 보존'} · {file.frame_times_seconds.length}프레임 · 길이 {seconds(file.duration_seconds)} · 연속 오디오 {ranges(file.audio_ranges)}</p>
    <label>확인할 실제 프레임 번호<input type="number" min={1} step={1} max={file.frame_times_seconds.length} value={frame + 1} onChange={event => { const index = Math.max(0, Math.min(file.frame_times_seconds.length - 1, Math.trunc(Number(event.target.value)) - 1)); setFrame(index); if (video.current) video.current.currentTime = file.frame_times_seconds[index]; }} /></label>
    <p>클립 {seconds(file.frame_times_seconds[frame])} → 원본 {seconds(file.source_frame_times_seconds[frame])} → 기준 영상 {seconds(file.source_frame_times_seconds[frame] - clip.offset_seconds)}</p>
    <details><summary>클립 해시·출처</summary><p>{file.ref}<br />SHA-256: {file.hash}<br />{file.size_bytes.toLocaleString()} bytes</p></details>
  </article>;
}
