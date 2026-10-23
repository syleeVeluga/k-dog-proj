import { guessFromFilename } from './uploadGuess';
import { useRef, useState } from 'react';
import { api, ApiError } from './api';
import { useEditBase } from './Editing';
import { sessionOf, type Case, type MediaSourceKind, type Run, type Video } from './types';

type Registration = { request_id: string; expected_revision: number; camera_id: string; source_original_number: string | null; source_kind: MediaSourceKind; parents: { upload_id: string; sha256: string; video_id: string | null }[]; conversion: { tool: string; tool_version: string; settings: Record<string, unknown> } | null };
type Props = { item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void> };

export function PreservedMediaRegistration({ item, writable, run, refresh }: Props) {
  const session = sessionOf(item);
  const videos = session.videos.filter(video => !video.upload_id);
  if (!videos.length) return null;
  return <section className="panel" aria-label="기존 영상 카메라 연결">
    <h2>기존 영상 카메라 연결</h2>
    <p>이전 방식으로 등록되어 카메라 연결이 없는 파일만 표시합니다. CSV의 카메라 열과 한 번 연결하면 이 안내는 사라집니다. 파일을 다시 올릴 필요는 없습니다.</p>
    <p className="fine">파일명에서 확인되는 번호를 미리 채웠습니다. CSV의 CAM1_영상초는 카메라 1로 연결한 파일의 시각입니다. 모호한 파일만 직접 확인하세요.</p>
    {videos.map(video => <RegistrationCard key={`${item.case_id}-${session.session_id}-${video.video_id}`} item={item} video={video} writable={writable} run={run} refresh={refresh} />)}
  </section>;
}

function RegistrationCard({ item, video, writable, run, refresh }: Props & { video: Video }) {
  const editor = useEditBase(item);
  const [camera, setCamera] = useState((guessFromFilename(video.original_name)?.camera ?? '').replace(/^CAM(\d+)$/i, '$1'));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [locked, setLocked] = useState(false);
  const pending = useRef<Registration | null>(null);
  const session = sessionOf(item);
  async function register(retryLatest = false) {
    setError('');
    if (!pending.current) {
      if (!camera.trim()) { setError('촬영 카메라 식별자를 입력하세요.'); return; }
      pending.current = { request_id: crypto.randomUUID(), expected_revision: editor.view.input_revision,
        camera_id: /^\d+$/.test(camera.trim()) ? `CAM${camera.trim()}` : camera.trim(), source_original_number: null, source_kind: 'received_file', parents: [], conversion: null };
      setLocked(true);
    }
    if (retryLatest) pending.current.expected_revision = item.input_revision;
    setBusy(true);
    try {
      await api<Case>(`/cases/${item.case_id}/sessions/${session.session_id}/videos/${video.video_id}/registration`, 'PUT', pending.current);
      editor.reset();
      await refresh('보존 영상의 출처를 등록했습니다.');
    } catch (reason) {
      const isConflict = reason instanceof ApiError && reason.status === 409;
      setConflict(isConflict);
      setError(reason instanceof Error ? reason.message : '영상 출처를 등록하지 못했습니다. 같은 요청으로 다시 시도할 수 있습니다.');
      if (reason instanceof ApiError && reason.status === 422) { pending.current = null; setLocked(false); }
      if (isConflict) await refresh();
    } finally { setBusy(false); }
  }
  return <article className="receipt-card" aria-label={`${video.original_name} 출처 등록`}>
    <h3>{video.original_name}</h3>
    <p className="fine">영상 {(video.size_bytes / 1048576).toFixed(1)} MiB</p><details><summary>기술 정보</summary><p className="fine">영상 {video.video_id} · SHA-256 {video.sha256}</p></details>
    <form onChange={editor.change} onSubmit={event => { event.preventDefault(); void run(() => register()); }}>
      <fieldset disabled={!writable || busy || locked}><legend>확인한 촬영 정보</legend>
        <div className="form-grid">
          <label>보존 영상 카메라<input required value={camera} onChange={event => setCamera(event.target.value)} placeholder="필수: 예) CSV의 CAM1이면 1" pattern="[A-Za-z0-9_-]+" maxLength={100} /></label>
        </div>
      </fieldset>
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" className="primary" disabled={!writable || busy || conflict}>{busy ? '원본 확인 중…' : locked ? '같은 출처 등록 요청 재시도' : '기존 영상 카메라 연결'}</button>
      {conflict && <button type="button" disabled={!writable || busy} onClick={() => void run(() => register(true))}>최신 버전 {item.input_revision}에 같은 출처 등록 재시도</button>}
      {conflict && <button type="button" disabled={!writable || busy} onClick={() => {
        pending.current = null; setLocked(false); setConflict(false); setError(''); editor.reset(); editor.change();
      }}>출처 입력 수정</button>}
    </form>
  </article>;
}
