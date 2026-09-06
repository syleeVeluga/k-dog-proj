import { useState } from 'react';
import { api } from './api';
import { useUnsaved } from './Editing';
import type { Case, Session } from './types';

type Upload = { file: File; camera: string; state: '대기' | '등록 중' | '저장됨' | '실패'; error: string };
export function VideoUpload({ item, session, refresh }: { item: Case; session: Session; refresh: (message?: string) => Promise<void> }) {
  const [camera, setCamera] = useState('CAM-1');
  const [queue, setQueue] = useState<Upload[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useUnsaved(queue.some(q => q.state !== '저장됨'));
  async function upload() {
    setBusy(true); setError('');
    const pending = queue.map(q => ({ ...q }));
    try {
      let current = await api<Case>(`/cases/${item.case_id}`);
      if (current.selected_session_id !== session.session_id) throw new Error('선택 세션이 변경되었습니다. 촬영 세션을 확인하세요.');
      for (const entry of pending) {
        if (entry.state === '저장됨') continue;
        entry.state = '등록 중'; entry.error = ''; setQueue(pending.map(q => ({ ...q })));
        try {
          const query = new URLSearchParams({ session_id: session.session_id, camera_id: entry.camera, filename: entry.file.name, expected_revision: String(current.input_revision) });
          current = await api<Case>(`/cases/${item.case_id}/videos?${query}`, 'POST', entry.file);
          entry.state = '저장됨';
        } catch (e) {
          entry.state = '실패'; entry.error = e instanceof Error ? e.message : '업로드 실패';
          break;
        } finally { setQueue(pending.map(q => ({ ...q }))); }
      }
      const saved = pending.filter(q => q.state === '저장됨').length;
      await refresh(`${saved}개 저장 · ${pending.filter(q => q.state === '실패').length}개 실패 · ${pending.filter(q => q.state === '대기').length}개 대기`);
    } catch (e) { setError(e instanceof Error ? e.message : '파일 등록 상태 확인 실패'); }
    finally { setBusy(false); }
  }
  return <form onSubmit={e => { e.preventDefault(); void upload(); }}><fieldset disabled={busy}>
    <div className="toolbar"><label>카메라 ID<input value={camera} pattern="[A-Za-z0-9_-]+" required onChange={e => setCamera(e.target.value)} /></label>
      <label>영상 파일<input type="file" accept=".mp4,.mov,.m4v,.avi,.mkv,.webm" multiple onChange={e => {
        const chosen = Array.from(e.target.files ?? []).map(file => ({ file, camera, state: '대기' as const, error: '' }));
        setQueue(previous => [...previous.filter(q => q.state !== '저장됨'), ...chosen]);
        e.target.value = '';
      }} /></label><button className="primary" disabled={!queue.some(q => q.state !== '저장됨')}>영상 등록</button></div>
    <p className="fine">{item.participant_id} · {item.dog_name} · {item.manifest.sessions.findIndex(s => s.session_id === session.session_id) + 1}차 촬영. 파일별 카메라를 확인하세요. 실패 이후 파일은 대기하며 저장된 파일은 다시 보내지 않습니다.</p>
    <ol className="upload-queue">{queue.map((q, i) => <li key={i}><strong>{q.file.name}</strong> · {(q.file.size / 1048576).toFixed(1)} MiB
      <label>파일 {i + 1} 카메라<input value={q.camera} disabled={q.state === '저장됨'} pattern="[A-Za-z0-9_-]+" required onChange={e => setQueue(queue.map((row, index) => index === i ? { ...row, camera: e.target.value } : row))} /></label>
      <p role="status">{q.state}{q.error && ` · ${q.error}`}</p>
      {q.state !== '저장됨' && <button type="button" onClick={() => setQueue(queue.filter((_, index) => index !== i))}>대기 목록에서 제거</button>}
    </li>)}</ol>
    {queue.some(q => q.state === '실패') && <p className="warning">실패 원인을 해결한 뒤 영상 등록을 다시 누르세요. 연결이 끊긴 경우 기존 영상 목록에서 저장 여부를 확인하세요.</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {busy && <p role="status">파일 등록 중입니다. 이 화면을 유지하세요.</p>}
  </fieldset></form>;
}
