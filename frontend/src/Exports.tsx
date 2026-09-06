import { useEffect, useState } from 'react';
import { api, accessLost } from './api';
import { Notification } from './Notification';
import type { Case } from './types';

type Member = { case_id: string; event_id: string; participant_id: string; dog_name: string; input_revision: number;
  revision: number | null; run_id: string | null; status: string; explanation_status: string; correction_needed: boolean;
  deliveries: { actor: string; at: string; channel: string; note: string }[] };
type Export = { export_id: string; format: string; status: string; count: number; created_at: string; preview_hash: string; members: Member[] };
const channels: Record<string, string> = { email: '이메일', messenger: '메신저', other: '기타' };

export function Exports({ caseId, runId, cases = [], selectedIds = [], canRecord = false }: {
  caseId?: string; runId?: string; cases?: Case[]; selectedIds?: string[]; canRecord?: boolean;
}) {
  const [list, setList] = useState<Export[]>([]);
  const [preview, setPreview] = useState<Export | null>(null);
  const [previewKey, setPreviewKey] = useState('');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [format, setFormat] = useState('pdf');
  const [scope, setScope] = useState('selected');
  const [eventId, setEventId] = useState('');
  const url = '/exports' + (caseId ? `?case_id=${caseId}` : '');
  const request = { format, case_id: caseId ?? null, run_id: runId ?? null,
    case_ids: !caseId && scope === 'selected' ? selectedIds : null,
    event_id: !caseId && scope === 'event' ? eventId : null };
  const requestKey = JSON.stringify(request);
  const reload = () => api<Export[]>(url).then(setList);
  useEffect(() => { setPreview(null); }, [requestKey]);
  useEffect(() => {
    if (!open) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const next = await api<Export[]>(url); if (active) setList(next); }
      catch (e) { if (active) { if (accessLost(e)) setList([]); setError(e instanceof Error ? e.message : '파일 목록 조회 실패'); } }
      if (active) timer = setTimeout(poll, 5000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [url, open]);
  async function inspect() {
    setBusy(true); setError(''); setPreview(null);
    try { setPreview(await api<Export>('/exports/preview', 'POST', request)); setPreviewKey(requestKey); }
    catch (e) { setError(e instanceof Error ? e.message : '대상 확인 실패'); }
    finally { setBusy(false); }
  }
  async function generate(id?: string) {
    if (!id && (!preview || previewKey !== requestKey)) return;
    setBusy(true); setError('');
    try {
      const created = id ? null : await api<Export>('/exports', 'POST', { ...request, expected_preview_hash: preview!.preview_hash });
      setPreview(null);
      await reload();
      await api(`/exports/${id ?? created!.export_id}/generate`, 'POST');
      await reload();
    } catch (e) { setPreview(null); setError(e instanceof Error ? e.message : '파일 생성 실패'); }
    finally { setBusy(false); }
  }
  const valid = caseId || (scope === 'selected' ? selectedIds.length > 0 : scope === 'event' ? !!eventId : true);
  return <details className="panel" aria-label="파일 내보내기" onToggle={e => setOpen(e.currentTarget.open)}><summary>{caseId ? '개별 파일 내보내기' : '전체 내보내기 · 운영자·교수용'}</summary>
    <p className="fine">{caseId ? '개별 참가자용 파일입니다.' : '선택/전체 파일은 운영자·교수용입니다. 참가자에게는 개별 파일을 전달하세요.'} 현재 버전을 고정하며 이전 파일은 수정되지 않습니다. CSV와 전체 PDF는 ZIP 묶음입니다.</p>
    <fieldset disabled={busy}>
      {!caseId && <div className="toolbar"><label>내보낼 대상<select value={scope} onChange={e => setScope(e.target.value)}>
        <option value="selected">목록에서 선택한 {selectedIds.length}명</option><option value="event">지정 행사</option><option value="all">모든 행사 전체</option>
      </select></label>{scope === 'event' && <label>내보낼 행사<select value={eventId} onChange={e => setEventId(e.target.value)}><option value="">행사 선택</option>
        {[...new Set(cases.map(c => c.event_id))].map(id => <option key={id}>{id}</option>)}</select></label>}</div>}
      <div className="toolbar"><label>파일 형식<select aria-label="파일 형식" value={format} onChange={e => setFormat(e.target.value)}><option value="pdf">PDF</option><option value="xlsx">Excel · XLSX</option><option value="csv">CSV 묶음</option></select></label>
        <button disabled={!valid} onClick={() => void inspect()}>내보낼 대상 확인</button></div>
      {preview && previewKey === requestKey && <section aria-label="내보내기 대상 미리보기"><h3>{preview.count}명 · {format.toUpperCase()} · {caseId ? '참가자용' : '운영자·교수용'}</h3>
        <ul>{preview.members.map(m => <li key={m.case_id}>{m.event_id} / {m.participant_id} · {m.dog_name} · 입력 {m.input_revision} / 수정 {m.revision ?? '없음'}
          {m.status !== 'scored' || !['ready', 'manual'].includes(m.explanation_status) ? ' · 미완료/부분 결과 포함' : ' · 점수·설명 준비됨'}</li>)}</ul>
        <p className="warning">미관찰·규칙 미정은 파일에도 표시됩니다. 대상 또는 결과가 바뀌면 다시 확인해야 합니다.</p>
        <button className="primary" onClick={() => void generate()}>현재 버전으로 파일 생성</button>
      </section>}
    </fieldset>
    {busy && <p role="status">파일 처리 중… 점수 조회는 계속할 수 있습니다.</p>}
    <Notification message={error} kind="error" onClose={() => setError('')} />
    {list.map(e => <section className="export-entry" key={e.export_id}><div className="video-row"><div><strong>{e.format.toUpperCase()} · {e.count}명</strong><p>{new Date(e.created_at).toLocaleString()} · {e.export_id.slice(0, 8)}</p></div>
      {e.status === 'ready' ? <a href={`/api/exports/${e.export_id}/file`} download>파일 다운로드</a> : <button disabled={busy} onClick={() => void generate(e.export_id)}>고정 버전 파일 생성 재시도</button>}</div>
      <details><summary>대상·버전·전달 이력</summary>{e.members.map(m => <div key={m.case_id}>
        <p><strong>{m.event_id} / {m.participant_id} · {m.dog_name}</strong> · 입력 {m.input_revision} / 수정 {m.revision ?? '없음'}</p>
        <p className={m.correction_needed ? 'warning' : 'fine'}>{m.correction_needed ? '전달 이후 변경 · 이 파일은 최신 결과와 다릅니다. 최신 파일의 재전달 이력을 확인하세요.' : m.deliveries.length ? '전달 기록됨 · 배달/읽음 확인 아님' : '미전달'}</p>
        {m.deliveries.map((d, i) => <p className="fine" key={i}>{new Date(d.at).toLocaleString()} · {d.actor} · {channels[d.channel]} · {d.note}</p>)}
        {canRecord && e.status === 'ready' && <form onSubmit={event => { event.preventDefault(); const form = event.currentTarget; const f = new FormData(form); setBusy(true); setError('');
          void api(`/exports/${e.export_id}/deliveries`, 'POST', { case_id: m.case_id, channel: f.get('channel'), note: f.get('note') })
            .then(async () => { form.reset(); await reload(); }).catch(err => setError(err.message)).finally(() => setBusy(false));
        }}><fieldset disabled={busy}><div className="toolbar"><label>전달 방법<select name="channel">{Object.entries(channels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>전달 메모<input name="note" maxLength={1000} placeholder="수동 전달 내용" /></label><button>수동 전달 기록</button></div></fieldset></form>}
      </div>)}</details>
    </section>)}
  </details>;
}
