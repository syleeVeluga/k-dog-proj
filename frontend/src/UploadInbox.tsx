import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { useUnsaved } from './Editing';
import { guessFromFilename } from './uploadGuess';
import type { Case, Run, User } from './types';

type Receipt = { upload_id: string; request_id: string; creator: string; filename: string; state: 'receiving' | 'complete' | 'failed' | 'linked'; expected_size: number; size_bytes: number | null; sha256: string | null; media_status: 'pending_probe' | 'storage_only'; source_kind: 'original' | 'received_conversion'; case_id: string | null; session_id: string | null; video_id: string | null; camera_id: string | null; linked_revision: number | null; failure_code: string | null };
type Parent = { upload_id: string; sha256: string; video_id: string | null };
type UploadRequest = { request_id: string; filename: string; expected_size: number; case_id: string | null; session_id: string | null; source_kind: 'original' | 'received_conversion'; parents: Parent[]; conversion: { tool: string; tool_version: string; settings: Record<string, unknown> } | null };
type QueueEntry = { file: File; id: string; request?: UploadRequest; receipt?: Receipt; status: string; error: string };
const stateName = { receiving: '수신 대기·진행 중', complete: '수신 완료', failed: '수신 실패·취소', linked: '연결됨' };
const failureText = (code: string) => code === 'cancelled' ? '수신이 취소되었습니다.' : /interrupted/.test(code) ? '서버가 멈추거나 연결이 끊겨 수신이 중단되었습니다.' : '수신을 마치지 못했습니다.';
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
    throw new ApiError(typeof result.detail === 'string' ? result.detail : '영상 수신에 실패했습니다.', response.status);
  }
  return result;
}

export function UploadInbox({ cases, selected, user, run, refresh }: { cases: Case[]; selected: Case | null; user: User; run: Run; refresh: (message?: string) => Promise<void> }) {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [linkedOpen, setLinkedOpen] = useState(false);
  const [error, setError] = useState('');
  const [kind, setKind] = useState<'original' | 'received_conversion'>('original');
  const [parents, setParents] = useState<string[]>([]);
  const [tool, setTool] = useState(''); const [toolVersion, setToolVersion] = useState('');
  const [settings, setSettings] = useState('{}');
  const controllers = useRef(new Map<string, AbortController>());
  useUnsaved(busy);
  const waiting = receipts.filter(receipt => receipt.state !== 'linked'), linked = receipts.filter(receipt => receipt.state === 'linked');
  async function load() { setReceipts(await api<Receipt[]>('/uploads')); }
  useEffect(() => { let active = true; api<Receipt[]>('/uploads').then(r => { if (active) setReceipts(r); }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, [selected?.case_id, selected?.selected_session_id]);

  async function upload() {
    setError('');
    let configuration: Record<string, unknown> = {};
    if (kind === 'received_conversion') {
      try { configuration = JSON.parse(settings); } catch { setError('변환 설정은 JSON 객체로 입력하세요.'); return; }
      if (!configuration || Array.isArray(configuration) || typeof configuration !== 'object' || !tool.trim() || !toolVersion.trim() || !parents.length) {
        setError('부모 원본과 변환 도구·버전·설정을 확인하세요.'); return;
      }
    }
    setBusy(true);
    const pending = queue.map(entry => ({ ...entry }));
    const update = () => setQueue(pending.map(entry => ({ ...entry })));
    try {
      await Promise.all(pending.map(async entry => {
        if (entry.receipt && ['complete', 'linked'].includes(entry.receipt.state)) return;
        const controller = new AbortController(); controllers.current.set(entry.id, controller);
        entry.error = ''; entry.status = '수신 중'; update();
        try {
          entry.request ??= { request_id: entry.id, filename: entry.file.name, expected_size: entry.file.size,
            case_id: selected?.case_id ?? null, session_id: selected?.selected_session_id ?? null, source_kind: kind,
            parents: kind === 'original' ? [] : receipts.filter(r => parents.includes(r.upload_id)).map(r => ({ upload_id: r.upload_id, sha256: r.sha256!, video_id: r.video_id })),
            conversion: kind === 'original' ? null : { tool: tool.trim(), tool_version: toolVersion.trim(), settings: configuration } };
          entry.receipt = await api<Receipt>('/uploads', 'POST', entry.request);
          if (!['complete', 'linked'].includes(entry.receipt.state)) entry.receipt = await sendContent(entry.receipt, entry.file, controller.signal);
          entry.status = '수신 완료';
        } catch (e) { entry.status = '수신 확인 필요'; entry.error = e instanceof Error ? e.message : '영상 수신 실패'; }
        finally { controllers.current.delete(entry.id); update(); }
      }));
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : '보관함을 조회하지 못했습니다.'); }
    finally { setBusy(false); }
  }

  return <section className="panel" aria-label="영상 수신 보관함"><div className="section-title"><h2>영상 수신 보관함</h2><button onClick={() => void run(load)}>보관함 새로고침</button></div>
    <p className="fine">파일을 먼저 수신하고 참가자·회차·카메라에 연결합니다. 수신 완료 파일은 연결 충돌 후에도 남으며 연결만 다시 시도합니다. 모든 업무 계정이 현장 보관함을 공유하고 미연결 수신물을 정리합니다.</p>
    <fieldset disabled={busy}><legend>{selected ? `${selected.participant_id} · 현재 회차에 수신` : '참가자 미등록 영상도 먼저 수신'}</legend>
      <div className="form-grid"><label>수신 파일<input aria-label="수신 파일" type="file" multiple accept=".mp4,.mov,.m4v,.avi,.mkv,.webm,.insv" onChange={e => {
        const chosen = Array.from(e.target.files ?? []).map(file => ({ file, id: crypto.randomUUID(), status: '대기', error: '' }));
        setQueue(previous => [...previous, ...chosen]); e.target.value = '';
      }} /></label><label>수신 자료 구분<select aria-label="수신 자료 구분" value={kind} onChange={e => setKind(e.target.value as typeof kind)}><option value="original">촬영 원본</option><option value="received_conversion">전달받은 변환 MP4</option></select></label></div>
      {kind === 'received_conversion' && <div className="form-grid"><label>변환 부모 원본<select aria-label="변환 부모 원본" multiple value={parents} onChange={e => setParents(Array.from(e.target.selectedOptions).map(o => o.value))}>{receipts.filter(r => ['complete', 'linked'].includes(r.state)).map(r => <option key={r.upload_id} value={r.upload_id}>{r.filename}{r.camera_id ? ` · ${r.camera_id}` : ''}</option>)}</select></label>
        <label>변환 도구<input aria-label="변환 도구" value={tool} onChange={e => setTool(e.target.value)} /></label><label>변환 도구 버전<input value={toolVersion} onChange={e => setToolVersion(e.target.value)} /></label><label>변환 설정<textarea value={settings} onChange={e => setSettings(e.target.value)} /></label></div>}
      <p className="fine">INSV는 원본 보관만 지원합니다. 변환 MP4는 부모 원본과 도구·버전·설정을 기록합니다. 수신 완료는 영상 판독 또는 채점 완료를 뜻하지 않습니다.</p>
      <button className="primary" disabled={!queue.some(entry => !entry.receipt || !['complete', 'linked'].includes(entry.receipt.state))} onClick={() => void upload()}>파일 수신 시작·재시도</button>
    </fieldset>
    <ol className="upload-queue">{queue.map(entry => <li key={entry.id}><strong>{entry.file.name}</strong> · {(entry.file.size / 1048576).toFixed(1)} MiB · <span role="status">{entry.status}</span>{entry.error && <p className="error">{entry.error}</p>}
      {controllers.current.has(entry.id) && <button onClick={() => controllers.current.get(entry.id)?.abort()}>이 전송 중단</button>}
      {!busy && <button onClick={() => setQueue(queue.filter(q => q.id !== entry.id))}>목록에서 숨기기</button>}
    </li>)}</ol>
    {error && <p role="alert" className="error">{error}</p>}
    <p className="fine">파일명이 「원본1·원본2·원본3」이면 원본1 → CAM1 · 원본3 → CAM2 · 원본2 → CAM3으로 미리 채웁니다. 그 밖의 파일은 카메라 ID를 직접 입력하세요. 자동 동기화나 임의 보관기간은 적용하지 않습니다.</p>
    {!!waiting.length && <h3>연결 대기 {waiting.length}건</h3>}
    {waiting.map(receipt => <ReceiptCard key={receipt.upload_id} receipt={receipt} cases={cases} selected={selected} user={user} run={run} changed={async message => { await load(); await refresh(message); }} />)}
    {!receipts.length && <p>수신물이 없습니다.</p>}
    {!!receipts.length && !waiting.length && <p>연결을 기다리는 수신물이 없습니다.</p>}
    {!!linked.length && <details onToggle={event => setLinkedOpen(event.currentTarget.open)}><summary>연결 완료한 파일 ({linked.length})</summary>
      {linkedOpen && linked.map(receipt => <ReceiptCard key={receipt.upload_id} receipt={receipt} cases={cases} selected={selected} user={user} run={run} changed={async message => { await load(); await refresh(message); }} />)}</details>}
  </section>;
}

function ReceiptCard({ receipt, cases, selected, user, run, changed }: { receipt: Receipt; cases: Case[]; selected: Case | null; user: User; run: Run; changed: (message?: string) => Promise<void> }) {
  const guess = guessFromFilename(receipt.filename);
  const [caseId, setCaseId] = useState(receipt.case_id ?? selected?.case_id ?? '');
  const [camera, setCamera] = useState(receipt.camera_id ?? guess?.camera ?? '');
  // 원본 번호는 직접 입력하지 않으면 지금 카메라가 파일명 추정과 같을 때만 그 번호를 쓴다. 카메라를 고치면 비워 서버가 카메라에서 정하게 한다.
  const [typedOriginal, setTypedOriginal] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(false);
  const target = cases.find(c => c.case_id === caseId);
  const sessionId = receipt.session_id ?? target?.selected_session_id ?? null;
  const original = typedOriginal ?? (guess && camera.trim() === guess.camera ? guess.original : '');
  const cameraId = camera.trim();
  const taken = cameraId && target && receipt.source_kind === 'original'
    ? target.manifest.sessions.find(value => value.session_id === sessionId)?.videos.find(video => video.camera_id?.toUpperCase() === cameraId.toUpperCase()) : undefined;
  const choices = cases.filter(c => c.manifest.schema_version === 'intake-4.0').filter(c => c.case_id === caseId
    || [c.sequence_no ?? '', c.participant_id, c.dog_name, c.event_id].join(' ').toLowerCase().includes(search.trim().toLowerCase()));
  const block = !target ? '연결할 참가자를 고르세요.' : !cameraId ? '카메라 ID를 입력하세요.' : !CAMERA_ID.test(cameraId) ? '카메라 ID는 CAM1처럼 영문·숫자·밑줄·하이픈만 쓸 수 있습니다.' : '';
  const canCancel = true;
  async function link() {
    setError('');
    try {
      const latest = await api<Case>(`/cases/${caseId}`);
      const linkSession = receipt.session_id ?? target?.selected_session_id;
      if (!linkSession || latest.selected_session_id !== linkSession) throw new Error('선택 회차가 변경되었습니다. 대상의 촬영 회차를 확인하세요.');
      await api(`/uploads/${receipt.upload_id}/link`, 'POST', { case_id: caseId, session_id: linkSession,
        expected_revision: latest.input_revision, camera_id: cameraId, source_original_number: original || null });
      await changed('수신 완료 파일을 참가자·회차에 연결했습니다.');
    } catch (e) { setRetry(e instanceof ApiError && e.status === 409); setError(e instanceof Error ? e.message : '연결에 실패했습니다.'); }
  }
  const linkedCase = receipt.case_id ? cases.find(c => c.case_id === receipt.case_id) : undefined;
  return <article className="panel" aria-label={`수신물 ${receipt.filename}`}><h3>{receipt.filename}</h3>
    <p><strong>{receipt.state === 'linked' ? (receipt.media_status === 'storage_only' ? '연결됨 · 원본 보관 전용' : '연결됨 · 영상 읽기 확인 대기') : stateName[receipt.state]}</strong>
      {receipt.media_status === 'storage_only' && <> · <span className="tag">INSV 원본 보관 전용</span></>} · 작성자 {receipt.creator}</p>
    {receipt.failure_code && <p className="warning">{failureText(receipt.failure_code)} 중단된 수신은 파일 전체를 다시 선택하여 이어서 받을 수 있습니다.</p>}
    {['complete', 'linked'].includes(receipt.state) && <a href={`/api/uploads/${receipt.upload_id}/content`}>보관 원본 내려받기</a>}
    {receipt.state === 'complete' && <><div className="form-grid">
      <label>참가자 찾기<input aria-label="참가자 찾기" type="search" value={search} placeholder="순번·ID·반려견 이름" onChange={e => setSearch(e.target.value)} />
        {search.trim() && !choices.some(c => c.case_id !== caseId) && <small>찾는 참가자가 없습니다.</small>}</label>
      <label>연결 참가자<select aria-label="연결 참가자" disabled={!!receipt.case_id} value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">대상 선택</option>{choices.map(c => <option key={c.case_id} value={c.case_id}>{c.sequence_no ?? '—'}번 · {c.participant_id} · {c.dog_name} · {c.event_id}</option>)}</select></label>
      <label>카메라 ID<input aria-label="카메라 ID" value={camera} aria-invalid={taken ? true : undefined} aria-describedby={taken ? `taken-${receipt.upload_id}` : undefined} onChange={e => setCamera(e.target.value)} />
        {guess && camera === guess.camera && <small>파일명 「원본{guess.original}」에 맞춰 채웠습니다. 다르면 고치세요.</small>}
        {taken && <small className="field-error" id={`taken-${receipt.upload_id}`}>{sessionName(target, sessionId)}에 카메라 {camera}이(가) 이미 연결되어 있습니다({taken.original_name}). 다른 카메라 ID인지 확인하세요.</small>}</label>
      <label>원본 번호<input aria-label="원본 번호" value={original} placeholder={({ CAM1: '1', CAM2: '3', CAM3: '2' } as Record<string, string>)[cameraId] ?? '확인한 경우 입력'} onChange={e => setTypedOriginal(e.target.value)} /></label></div>
      <p className="fine">연결 회차: {target ? sessionName(target, sessionId) : '참가자를 먼저 고르세요.'}</p>
      <div className="toolbar"><button className="primary" disabled={!!block} onClick={() => void link()}>{retry ? '다시 연결' : '연결'}</button>
        {block && <span className="fine" aria-live="polite">{block}</span>}</div></>}
    {receipt.state === 'linked' && <p>{linkedCase ? `${linkedCase.participant_id} ${linkedCase.dog_name} · ` : ''}{sessionName(linkedCase, receipt.session_id)} · 카메라 {receipt.camera_id}</p>}
    {(receipt.state === 'failed' || receipt.state === 'receiving') && <label>중단 파일 다시 선택<input aria-label="중단 파일 다시 선택" type="file" onChange={e => {
      const file = e.target.files?.[0]; if (!file) return;
      void run(async () => {
        if (file.name !== receipt.filename || file.size !== receipt.expected_size) throw new Error('같은 파일명·크기의 원본을 선택하세요.');
        await sendContent(receipt, file, new AbortController().signal); await changed('수신을 완료했습니다.');
      }); e.target.value = '';
    }} /></label>}
    {receipt.state !== 'linked' && receipt.failure_code !== 'cancelled' && canCancel && <button onClick={() => {
      const warning = receipt.state === 'receiving' ? ' 다른 PC에서 전송 중이면 그 전송도 멈춥니다.' : '';
      if (!window.confirm(`‘${receipt.filename}’ 수신을 취소할까요? 연결하지 않은 파일의 수신이 취소되고 파일은 유지보수 때 정리됩니다.${warning} 같은 파일을 다시 선택하면 수신을 이어서 할 수 있습니다.`)) return;
      void run(async () => { await api(`/uploads/${receipt.upload_id}`, 'DELETE'); await changed('수신을 취소했습니다. 실제 파일 정리는 유지보수 때 적용됩니다.'); }); }}>수신 취소</button>}
    {error && <p role="alert" className="error">{error} 수신 완료 파일은 보관되어 있으므로 연결만 재시도하세요.</p>}
    <details><summary>기술 정보</summary><p className="fine mono">수신 ID {receipt.upload_id} · {(receipt.expected_size / 1048576).toFixed(1)} MiB{receipt.sha256 && ` · SHA-256 ${receipt.sha256}`}{receipt.linked_revision !== null && ` · 연결 입력 버전 ${receipt.linked_revision}`}{receipt.session_id && ` · 회차 ${receipt.session_id}`}{receipt.failure_code && ` · 상태 코드 ${receipt.failure_code}`}</p></details>
  </article>;
}
