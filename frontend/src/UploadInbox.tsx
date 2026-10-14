import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { useUnsaved } from './Editing';
import { guessFromFilename } from './uploadGuess';
import type { Case, MediaSourceKind, Run, User } from './types';
import { cameraName } from './types';

type Receipt = { upload_id: string; request_id: string; creator: string; filename: string; state: 'receiving' | 'complete' | 'failed' | 'linked'; expected_size: number; size_bytes: number | null; sha256: string | null; media_status: 'pending_probe'; source_kind: MediaSourceKind; case_id: string | null; session_id: string | null; video_id: string | null; camera_id: string | null; linked_revision: number | null; failure_code: string | null };
type Parent = { upload_id: string; sha256: string; video_id: string | null };
type UploadRequest = { request_id: string; filename: string; expected_size: number; case_id: string | null; session_id: string | null; source_kind: MediaSourceKind; parents: Parent[]; conversion: { tool: string; tool_version: string; settings: Record<string, unknown> } | null };
type QueueEntry = { file: File; id: string; selection: Omit<UploadRequest, 'request_id' | 'filename' | 'expected_size'>; request?: UploadRequest; receipt?: Receipt; status: string; error: string };
const stateName = { receiving: '업로드 대기·진행 중', complete: '업로드 완료', failed: '업로드 실패·취소', linked: '등록됨' };
const failureText = (code: string) => code === 'cancelled' ? '업로드가 취소되었습니다.' : /interrupted/.test(code) ? '서버가 멈추거나 연결이 끊겨 업로드가 중단되었습니다.' : '업로드를 마치지 못했습니다.';
const CAMERA_ID = /^[A-Za-z0-9_-]+$/;
const sessionName = (item: Case | undefined, sessionId: string | null) => {
  const index = item && sessionId ? item.manifest.sessions.findIndex(value => value.session_id === sessionId) : -1;
  return index >= 0 ? `${index + 1}차 촬영` : '촬영 회차';
};

async function sendContent(receipt: Receipt, file: File, signal: AbortSignal): Promise<Receipt> {
  const response = await fetch(`/api/uploads/${receipt.upload_id}/content?request_id=${encodeURIComponent(receipt.request_id)}`, {
    method: 'PUT', credentials: 'same-origin', headers: { 'X-KDOG-Request': '1' }, body: file, signal,
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('kdog-session-expired'));
    throw new ApiError(typeof result.detail === 'string' ? result.detail : '영상 업로드에 실패했습니다.', response.status);
  }
  return result;
}

export function UploadInbox({ cases, selected, user, run, refresh }: { cases: Case[]; selected: Case | null; user: User; run: Run; refresh: (message?: string) => Promise<void> }) {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [linkedOpen, setLinkedOpen] = useState(false);
  const [error, setError] = useState('');
  const [kind, setKind] = useState<MediaSourceKind>('original');
  const [parents, setParents] = useState<string[]>([]);
  const [tool, setTool] = useState(''); const [toolVersion, setToolVersion] = useState('');
  const [settings, setSettings] = useState('{}');
  const controllers = useRef(new Map<string, AbortController>());
  useUnsaved(busy || queue.some(entry => !entry.receipt || !['complete', 'linked'].includes(entry.receipt.state)));
  const waiting = receipts.filter(receipt => receipt.state !== 'linked'), linked = receipts.filter(receipt => receipt.state === 'linked');
  async function load() { setReceipts(await api<Receipt[]>('/uploads')); }
  useEffect(() => { let active = true; api<Receipt[]>('/uploads').then(r => { if (active) setReceipts(r); }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, [selected?.case_id, selected?.selected_session_id]);

  async function upload() {
    setError('');
    setBusy(true);
    const pending = queue.map(entry => ({ ...entry }));
    const update = () => setQueue(pending.map(entry => ({ ...entry })));
    try {
      await Promise.all(pending.map(async entry => {
        if (entry.receipt && ['complete', 'linked'].includes(entry.receipt.state)) return;
        const controller = new AbortController(); controllers.current.set(entry.id, controller);
        entry.error = ''; entry.status = '업로드 중'; update();
        try {
          entry.request ??= { request_id: entry.id, filename: entry.file.name, expected_size: entry.file.size, ...entry.selection };
          entry.receipt = await api<Receipt>('/uploads', 'POST', entry.request);
          if (!['complete', 'linked'].includes(entry.receipt.state)) entry.receipt = await sendContent(entry.receipt, entry.file, controller.signal);
          entry.status = '업로드 완료';
        } catch (e) { entry.status = '업로드 확인 필요'; entry.error = e instanceof Error ? e.message : '영상 업로드 실패'; }
        finally { controllers.current.delete(entry.id); update(); }
      }));
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : '보관함을 조회하지 못했습니다.'); }
    finally { setBusy(false); }
  }

  return <section className="panel" aria-label="업로드 파일 목록"><div className="section-title"><h2>업로드 파일 목록</h2><button onClick={() => void run(load)}>목록 새로고침</button></div>
    <p className="fine">PC에 저장된 영상 파일을 선택해 업로드하세요. 업로드 후 각 파일의 참가자·촬영 회차·촬영 카메라 번호를 확인하고 영상 정보를 저장합니다. 모든 업무 계정이 같은 파일 목록을 사용합니다.</p>
    <fieldset disabled={busy}><legend>{selected ? `${selected.participant_id} · 현재 회차 영상 업로드` : '영상 파일 선택'}</legend>
      <label>영상 파일 구분<select aria-label="영상 파일 구분" value={kind} onChange={e => setKind(e.target.value as MediaSourceKind)}><option value="original">촬영 원본</option><option value="received_conversion">변환 MP4</option></select></label>
      {kind === 'received_conversion' && <div className="form-grid"><label>변환 부모 원본<select aria-label="변환 부모 원본" multiple value={parents} onChange={e => setParents(Array.from(e.target.selectedOptions).map(o => o.value))}>{receipts.filter(r => ['complete', 'linked'].includes(r.state)).map(r => <option key={r.upload_id} value={r.upload_id}>{r.filename}{r.camera_id ? ` · ${cameraName(r.camera_id)}` : ''}</option>)}</select></label>
        <label>변환 도구<input aria-label="변환 도구" value={tool} onChange={e => setTool(e.target.value)} /></label><label>변환 도구 버전<input value={toolVersion} onChange={e => setToolVersion(e.target.value)} /></label><label>변환 설정<textarea value={settings} onChange={e => setSettings(e.target.value)} /></label></div>}
      <label>영상 파일<input aria-label="영상 파일" type="file" multiple accept=".mp4,.mov,.m4v,.avi,.mkv,.webm" onChange={e => {
        const files = Array.from(e.target.files ?? []); e.target.value = ''; setError('');
        let configuration: Record<string, unknown> = {};
        if (kind === 'received_conversion') {
          try { configuration = JSON.parse(settings); } catch { setError('변환 설정은 JSON 객체로 입력하세요.'); return; }
          if (!configuration || Array.isArray(configuration) || typeof configuration !== 'object' || !tool.trim() || !toolVersion.trim() || !parents.length) { setError('파일 선택 전에 부모 원본과 변환 도구·버전·설정을 확인하세요.'); return; }
        }
        const selection = { case_id: selected?.case_id ?? null, session_id: selected?.selected_session_id ?? null, source_kind: kind,
          parents: kind === 'received_conversion' ? receipts.filter(r => parents.includes(r.upload_id)).map(r => ({ upload_id: r.upload_id, sha256: r.sha256!, video_id: r.video_id })) : [],
          conversion: kind === 'received_conversion' ? { tool: tool.trim(), tool_version: toolVersion.trim(), settings: configuration } : null };
        setQueue(previous => [...previous, ...files.map(file => ({ file, id: crypto.randomUUID(), selection, status: '대기', error: '' }))]);
      }} /></label>
      <p className="fine">파일 선택 시 구분과 참가자·회차를 고정합니다. 구분을 바꾸려면 대기 항목을 숨기고 다시 선택하세요.</p>
      <p className="fine">변환 MP4는 부모 원본과 도구·버전·설정을 기록합니다. 업로드 완료는 영상 판독 또는 채점 완료를 뜻하지 않습니다.</p>
      <button className="primary" disabled={!queue.some(entry => !entry.receipt || !['complete', 'linked'].includes(entry.receipt.state))} onClick={() => void upload()}>업로드 시작·재시도</button>
    </fieldset>
    <ol className="upload-queue">{queue.map(entry => <li key={entry.id}><strong>{entry.file.name}</strong> · {(entry.file.size / 1048576).toFixed(1)} MiB · <span role="status">{entry.status}</span>{entry.error && <p className="error">{entry.error}</p>}
      {controllers.current.has(entry.id) && <button onClick={() => controllers.current.get(entry.id)?.abort()}>이 전송 중단</button>}
      {!busy && <button onClick={() => setQueue(queue.filter(q => q.id !== entry.id))}>목록에서 숨기기</button>}
    </li>)}</ol>
    {error && <p role="alert" className="error">{error}</p>}
    <p className="fine">촬영 카메라 번호는 각 영상 파일을 촬영한 카메라를 구분하는 번호입니다. 파일명이 「원본1·원본2·원본3」이면 원본1 → 1번 · 원본3 → 2번 · 원본2 → 3번으로 미리 채웁니다. 실제 촬영 번호가 다르면 파일별로 고치세요.</p>
    {!!waiting.length && <h3>영상 정보 입력 대기 {waiting.length}건</h3>}
    {waiting.map(receipt => <ReceiptCard key={receipt.upload_id} receipt={receipt} cases={cases} selected={selected} user={user} run={run} changed={async message => { await load(); await refresh(message); }} />)}
    {!receipts.length && <p>업로드한 영상 파일이 없습니다.</p>}
    {!!receipts.length && !waiting.length && <p>영상 정보 입력을 기다리는 파일이 없습니다.</p>}
    {!!linked.length && <details onToggle={event => { if (event.currentTarget.open) setLinkedOpen(true); }}><summary>정보 저장 완료한 파일 ({linked.length})</summary>
      {linkedOpen && linked.map(receipt => <ReceiptCard key={receipt.upload_id} receipt={receipt} cases={cases} selected={selected} user={user} run={run} changed={async message => { await load(); await refresh(message); }} />)}</details>}
  </section>;
}

function ReceiptCard({ receipt, cases, selected, user, run, changed }: { receipt: Receipt; cases: Case[]; selected: Case | null; user: User; run: Run; changed: (message?: string) => Promise<void> }) {
  const guess = guessFromFilename(receipt.filename);
  const [caseId, setCaseId] = useState(receipt.case_id ?? selected?.case_id ?? '');
  const [camera, setCamera] = useState((receipt.camera_id ?? guess?.camera ?? '').replace(/^CAM(\d+)$/i, '$1'));
  // 원본 번호는 직접 입력하지 않으면 지금 카메라가 파일명 추정과 같을 때만 그 번호를 쓴다. 카메라를 고치면 비워 서버가 카메라에서 정하게 한다.
  const [typedOriginal, setTypedOriginal] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(false);
  const target = cases.find(c => c.case_id === caseId);
  const sessionId = receipt.session_id ?? target?.selected_session_id ?? null;
  const cameraId = /^\d+$/.test(camera.trim()) ? `CAM${camera.trim()}` : camera.trim();
  const original = typedOriginal ?? (guess && cameraId === guess.camera ? guess.original : '');
  const taken = cameraId && target && receipt.source_kind === 'original'
    ? target.manifest.sessions.find(value => value.session_id === sessionId)?.videos.find(video => video.camera_id?.toUpperCase() === cameraId.toUpperCase()) : undefined;
  const choices = cases.filter(c => c.manifest.schema_version === 'intake-4.0').filter(c => c.case_id === caseId
    || [c.sequence_no ?? '', c.participant_id, c.dog_name, c.event_id].join(' ').toLowerCase().includes(search.trim().toLowerCase()));
  const block = !target ? '참가자를 고르세요.' : !cameraId ? '촬영 카메라 번호를 입력하세요.' : !CAMERA_ID.test(cameraId) ? '촬영 카메라 번호는 숫자 또는 영문·숫자·밑줄·하이픈으로 입력하세요.' : '';
  const canCancel = true;
  async function link() {
    setError('');
    try {
      const latest = await api<Case>(`/cases/${caseId}`);
      const linkSession = receipt.session_id ?? target?.selected_session_id;
      if (!linkSession || latest.selected_session_id !== linkSession) throw new Error('선택 회차가 변경되었습니다. 대상의 촬영 회차를 확인하세요.');
      await api(`/uploads/${receipt.upload_id}/link`, 'POST', { case_id: caseId, session_id: linkSession,
        expected_revision: latest.input_revision, camera_id: cameraId, source_original_number: original || null });
      await changed('영상 파일의 참가자·촬영 회차·촬영 카메라 번호를 저장했습니다.');
    } catch (e) { setRetry(e instanceof ApiError && e.status === 409); setError(e instanceof Error ? e.message : '영상 정보 저장에 실패했습니다.'); }
  }
  const linkedCase = receipt.case_id ? cases.find(c => c.case_id === receipt.case_id) : undefined;
  return <article className="panel" aria-label={`업로드 파일 ${receipt.filename}`}><h3>{receipt.filename}</h3>
    <p><strong>{receipt.state === 'linked' ? '등록됨 · 영상 읽기 확인 대기' : stateName[receipt.state]}</strong> · 작성자 {receipt.creator}</p>
    {receipt.failure_code && <p className="warning">{failureText(receipt.failure_code)} 중단된 파일은 다시 선택하여 업로드할 수 있습니다.</p>}
    {['complete', 'linked'].includes(receipt.state) && <a href={`/api/uploads/${receipt.upload_id}/content`}>보관 원본 내려받기</a>}
    {receipt.state === 'complete' && <><div className="form-grid">
      <label>참가자 찾기<input aria-label="참가자 찾기" type="search" value={search} placeholder="순번·ID·반려견 이름" onChange={e => setSearch(e.target.value)} />
        {search.trim() && !choices.some(c => c.case_id !== caseId) && <small>찾는 참가자가 없습니다.</small>}</label>
      <label>참가자<select aria-label="참가자" disabled={!!receipt.case_id} value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">대상 선택</option>{choices.map(c => <option key={c.case_id} value={c.case_id}>{c.sequence_no ?? '—'}번 · {c.participant_id} · {c.dog_name} · {c.event_id}</option>)}</select></label>
      <label>촬영 카메라 번호<input aria-label="촬영 카메라 번호" value={camera} placeholder="예: 1, 2, 3" aria-invalid={taken ? true : undefined} aria-describedby={taken ? `taken-${receipt.upload_id}` : undefined} onChange={e => setCamera(e.target.value)} />
        {guess && cameraId === guess.camera && <small>파일명 「원본{guess.original}」에 맞춰 채웠습니다. 다르면 고치세요.</small>}
        {taken && <small className="field-error" id={`taken-${receipt.upload_id}`}>{sessionName(target, sessionId)}에 촬영 카메라 {camera} 번호의 영상이 이미 등록되어 있습니다({taken.original_name}). 이 파일의 촬영 카메라 번호를 확인하세요.</small>}</label>
      <label>원본 번호<input aria-label="원본 번호" value={original} placeholder={({ CAM1: '1', CAM2: '3', CAM3: '2' } as Record<string, string>)[cameraId] ?? '확인한 경우 입력'} onChange={e => setTypedOriginal(e.target.value)} /></label></div>
      <p className="fine">촬영 회차: {target ? sessionName(target, sessionId) : '참가자를 먼저 고르세요.'}</p>
      <div className="toolbar"><button className="primary" disabled={!!block} onClick={() => void link()}>{retry ? '다시 저장' : '영상 정보 저장'}</button>
        {block && <span className="fine" aria-live="polite">{block}</span>}</div></>}
    {receipt.state === 'linked' && <p>{linkedCase ? `${linkedCase.participant_id} ${linkedCase.dog_name} · ` : ''}{sessionName(linkedCase, receipt.session_id)} · {`촬영 카메라 번호 ${receipt.camera_id?.replace(/^CAM(\d+)$/i, '$1')}`}</p>}
    {(receipt.state === 'failed' || receipt.state === 'receiving') && <label>중단 파일 다시 선택<input aria-label="중단 파일 다시 선택" type="file" onChange={e => {
      const file = e.target.files?.[0]; if (!file) return;
      void run(async () => {
        if (file.name !== receipt.filename || file.size !== receipt.expected_size) throw new Error('같은 파일명·크기의 원본을 선택하세요.');
        await sendContent(receipt, file, new AbortController().signal); await changed('업로드를 완료했습니다.');
      }); e.target.value = '';
    }} /></label>}
    {receipt.state !== 'linked' && receipt.failure_code !== 'cancelled' && canCancel && <button onClick={() => {
      const warning = receipt.state === 'receiving' ? ' 다른 PC에서 전송 중이면 그 전송도 멈춥니다.' : '';
      if (!window.confirm(`‘${receipt.filename}’ 업로드를 취소할까요? 영상 정보를 저장하지 않은 파일의 업로드가 취소되고 파일은 유지보수 때 정리됩니다.${warning} 같은 파일을 다시 선택하면 업로드를 재시도할 수 있습니다.`)) return;
      void run(async () => { await api(`/uploads/${receipt.upload_id}`, 'DELETE'); await changed('업로드를 취소했습니다. 실제 파일 정리는 유지보수 때 적용됩니다.'); }); }}>업로드 취소</button>}
    {error && <p role="alert" className="error">{error} 업로드 완료 파일은 보관되어 있으므로 영상 정보 저장만 재시도하세요.</p>}
    <details><summary>기술 정보</summary><p className="fine mono">업로드 ID {receipt.upload_id} · {(receipt.expected_size / 1048576).toFixed(1)} MiB{receipt.sha256 && ` · SHA-256 ${receipt.sha256}`}{receipt.linked_revision !== null && ` · 연결 입력 버전 ${receipt.linked_revision}`}{receipt.session_id && ` · 회차 ${receipt.session_id}`}{receipt.failure_code && ` · 상태 코드 ${receipt.failure_code}`}</p></details>
  </article>;
}
