import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { useEditBase } from './Editing';
import { sessionOf, type Case, type Run, type Video } from './types';

type ParentReceipt = { upload_id: string; filename: string; state: string; sha256: string | null; video_id: string | null; case_id: string | null; session_id: string | null };
type Registration = { request_id: string; expected_revision: number; camera_id: string; source_original_number: string | null; source_kind: 'original' | 'received_conversion'; parents: { upload_id: string; sha256: string; video_id: string | null }[]; conversion: { tool: string; tool_version: string; settings: Record<string, unknown> } | null };
type Props = { item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void> };
const originalNumbers: Record<string, string> = { CAM1: '1', CAM2: '3', CAM3: '2' };

export function PreservedMediaRegistration({ item, writable, run, refresh }: Props) {
  const session = sessionOf(item);
  const videos = session.videos.filter(video => !video.upload_id);
  const [parents, setParents] = useState<ParentReceipt[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    if (writable && videos.length) api<ParentReceipt[]>('/uploads').then(result => {
      if (active) { setParents(result.filter(receipt => receipt.state === 'linked' && receipt.case_id === item.case_id && receipt.session_id === session.session_id && receipt.sha256)); setError(''); }
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '부모 원본 조회 실패'); });
    return () => { active = false; };
  }, [item.case_id, item.input_revision, session.session_id, writable, videos.length]);
  if (!videos.length) return null;
  return <section className="panel" aria-label="보존 영상 출처 등록">
    <h2>보존 영상 출처 등록</h2>
    <p>기존 영상에 촬영 카메라와 원본·변환 정보를 등록합니다. 영상 파일과 식별자는 그대로 보존됩니다.</p>
    <p className="fine">원본 1 → CAM1 · 원본 3 → CAM2 · 원본 2 → CAM3. 시간 오프셋은 촬영 기록에서 별도로 확인합니다. 변환 MP4의 부모 원본을 먼저 같은 회차에 등록하세요.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {videos.map(video => <RegistrationCard key={`${item.case_id}-${session.session_id}-${video.video_id}`} item={item} video={video} writable={writable} run={run} refresh={refresh} parents={parents} />)}
  </section>;
}

function RegistrationCard({ item, video, writable, run, refresh, parents }: Props & { video: Video; parents: ParentReceipt[] }) {
  const editor = useEditBase(item);
  const [camera, setCamera] = useState('');
  const [original, setOriginal] = useState('');
  const [kind, setKind] = useState<'' | 'original' | 'received_conversion'>('');
  const [parentIds, setParentIds] = useState<string[]>([]);
  const [tool, setTool] = useState('');
  const [version, setVersion] = useState('');
  const [settings, setSettings] = useState('{}');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [locked, setLocked] = useState(false);
  const pending = useRef<Registration | null>(null);
  const session = sessionOf(item);
  const eligible = parents.filter(parent => parent.video_id !== video.video_id);
  async function register(retryLatest = false) {
    setError('');
    if (!pending.current) {
      if (!kind || !camera.trim()) { setError('카메라 식별자와 원본·변환 구분을 선택하세요.'); return; }
      let configuration: Record<string, unknown> = {};
      if (kind === 'received_conversion') {
        try { configuration = JSON.parse(settings); } catch { setError('변환 설정은 JSON 객체로 입력하세요.'); return; }
        if (!configuration || Array.isArray(configuration) || typeof configuration !== 'object' || !tool.trim() || !version.trim() || !parentIds.length) {
          setError('부모 원본과 변환 도구·버전·설정을 확인하세요.'); return;
        }
        if (parentIds.some(id => !eligible.some(parent => parent.upload_id === id))) { setError('선택한 부모 원본의 연결 상태가 변경되었습니다. 다시 선택하세요.'); return; }
      }
      pending.current = { request_id: crypto.randomUUID(), expected_revision: editor.view.input_revision,
        camera_id: camera.trim(), source_original_number: original.trim() || null, source_kind: kind,
        parents: kind === 'original' ? [] : eligible.filter(parent => parentIds.includes(parent.upload_id)).map(parent => ({ upload_id: parent.upload_id, sha256: parent.sha256!, video_id: parent.video_id })),
        conversion: kind === 'original' ? null : { tool: tool.trim(), tool_version: version.trim(), settings: configuration } };
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
    <p className="fine">영상 {video.video_id} · {(video.size_bytes / 1048576).toFixed(1)} MiB · SHA-256 {video.sha256}</p>
    <form onChange={editor.change} onSubmit={event => { event.preventDefault(); void run(() => register()); }}>
      <fieldset disabled={!writable || busy || locked}><legend>확인한 촬영 정보</legend>
        <div className="form-grid">
          <label>보존 영상 카메라<input required value={camera} onChange={event => setCamera(event.target.value)} placeholder="CAM1 / CAM2 / CAM3 / 직접 입력" pattern="[A-Za-z0-9_-]+" maxLength={100} /></label>
          <label>보존 영상 원본 번호<input value={original} onChange={event => setOriginal(event.target.value)} placeholder={originalNumbers[camera] ? `미입력 시 ${originalNumbers[camera]}` : '별도 원본 번호가 있으면 입력'} /></label>
          <label>보존 영상 자료 구분<select required value={kind} onChange={event => setKind(event.target.value as typeof kind)}>
            <option value="">확인 후 선택</option><option value="original">촬영 원본</option><option value="received_conversion" disabled={!video.original_name.toLowerCase().endsWith('.mp4')}>전달받은 변환 MP4</option>
          </select></label>
        </div>
        {kind === 'received_conversion' && <div className="form-grid">
          <label>보존 영상 변환 부모 원본<select required multiple value={parentIds} onChange={event => setParentIds(Array.from(event.target.selectedOptions).map(option => option.value))}>
            {eligible.map(parent => <option key={parent.upload_id} value={parent.upload_id}>{parent.filename} · {parent.video_id}</option>)}
          </select></label>
          <label>보존 영상 변환 도구<input required value={tool} onChange={event => setTool(event.target.value)} /></label>
          <label>보존 영상 변환 도구 버전<input required value={version} onChange={event => setVersion(event.target.value)} /></label>
          <label>보존 영상 변환 설정<textarea required value={settings} onChange={event => setSettings(event.target.value)} /></label>
        </div>}
      </fieldset>
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" className="primary" disabled={!writable || busy || conflict}>{busy ? '원본 확인 중…' : locked ? '같은 출처 등록 요청 재시도' : '보존 영상 출처 등록'}</button>
      {conflict && <button type="button" disabled={!writable || busy} onClick={() => void run(() => register(true))}>최신 버전 {item.input_revision}에 같은 출처 등록 재시도</button>}
      {conflict && <button type="button" disabled={!writable || busy} onClick={() => {
        pending.current = null; setLocked(false); setConflict(false); setError(''); editor.reset(); editor.change();
      }}>출처 입력 수정</button>}
    </form>
  </article>;
}
