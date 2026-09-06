import { Notification } from './Notification';
import { useEffect, useState } from 'react';
import { api } from './api';
import { Scores } from './Scores';
import type { ScoreData } from './Scores';

type TextPart = { text: string; evidence_ids: string[] };
type Report = { cover: TextPart; domains: { slot: number; comment: string; evidence_ids: string[] }[];
  cross_type: { explanation: string; evidence_ids: string[] }; tips: TextPart[]; notice: string };
type Result = ScoreData & { evidence: { evidence_id: string; video_id: string; observation: string; candidate_item_ids: string[] }[];
  media: { video_id: string; duration_sec: number }[] };
type View = { revision: number; source_hash: string; status: string; report: Report | null;
  result: Result; image: { video_id: string; second: number } | null;
  history: { actor: string; at: string; revision: number; reason: string; kind: string }[] };
const states: Record<string, string> = { ready: '설명 준비됨', manual: '수동 설명 저장됨', stale: '설명 갱신 필요',
  running: '설명 생성 중', not_started: '설명 미준비', retry_wait: '설명 재시도 대기', failed: '설명 실패 · 설정과 시도 이력 확인' };
type Export = { export_id: string; format: string; status: string; count: number; created_at: string };

export function Exports({ caseId, runId }: { caseId?: string; runId?: string }) {
  const [list, setList] = useState<Export[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [format, setFormat] = useState('pdf');
  const [eventId, setEventId] = useState('');
  const url = '/exports' + (caseId ? `?case_id=${caseId}` : '');
  const reload = () => api<Export[]>(url).then(setList);
  useEffect(() => { void reload().catch(e => setError(e.message)); }, [url]);
  async function generate(id?: string) {
    setBusy(true); setError('');
    try {
      const created = id ? null : await api<Export>('/exports', 'POST', { format, case_id: caseId ?? null, run_id: runId ?? null, event_id: eventId || null });
      const exportId = id ?? created!.export_id;
      await reload();
      await api(`/exports/${exportId}/generate`, 'POST');
      await reload();
    } catch (e) { setError(e instanceof Error ? e.message : '파일 생성 실패'); }
    finally { setBusy(false); }
  }
  return <details className="panel" aria-label="파일 내보내기"><summary>{caseId ? '개별 파일 내보내기' : '전체 내보내기 · 운영자·교수용'}</summary>
    <p className="fine">현재 버전을 고정하며 이전 파일은 수정되지 않습니다. CSV와 전체 PDF는 ZIP 묶음입니다.</p>
    {!caseId && <label>내보낼 행사 ID (비우면 모든 행사)<input value={eventId} onChange={e => setEventId(e.target.value)} /></label>}
    <fieldset disabled={busy}><div className="toolbar"><label>파일 형식<select aria-label="파일 형식" value={format} onChange={e => setFormat(e.target.value)}><option value="pdf">PDF</option><option value="xlsx">Excel · XLSX</option><option value="csv">CSV 묶음</option></select></label>
      <button onClick={() => void generate()}>현재 버전으로 파일 생성</button></div></fieldset>
    {busy && <p role="status">파일 생성 중… 점수 조회는 계속할 수 있습니다.</p>}
    <Notification message={error} kind="error" onClose={() => setError('')} />
    {list.map(e => <div className="video-row" key={e.export_id}><div><strong>{e.format.toUpperCase()} · {e.count}명</strong><p>{new Date(e.created_at).toLocaleString()} · {e.export_id.slice(0, 8)}</p></div>
      {e.status === 'ready' ? <a href={`/api/exports/${e.export_id}/file`} download>파일 다운로드</a> : <button disabled={busy} onClick={() => void generate(e.export_id)}>고정 버전 파일 생성 재시도</button>}</div>)}
  </details>;
}

export function Reports({ caseId, runId, play }: { caseId: string; runId: string; play: (id: string) => void }) {
  const [data, setData] = useState<View | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [itemId, setItemId] = useState('BS-01');
  const [draftSource, setDraftSource] = useState({ score: '', text: '' });
  const [draftKey, setDraftKey] = useState(0);
  const base = `/cases/${caseId}/reports/${runId}`;
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const next = await api<View>(base); if (active) setData(next); }
      catch (e) { if (active) { setData(null); setError(e instanceof Error ? e.message : '리포트 조회 실패'); } }
      if (active) timer = setTimeout(poll, 3000);
    };
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [base]);
  async function act(path: string, body: object, method = 'PUT') {
    setBusy(true); setError(''); setMessage('');
    try { await api(path, method, body); setData(await api<View>(base)); setDraftSource({ score: '', text: '' }); setMessage('저장했습니다.'); }
    catch (e) { setError(e instanceof Error ? e.message : '저장 실패'); }
    finally { setBusy(false); }
  }
  const choices = data?.result.behavior_items.find(i => i.item_id === itemId);
  const current = data?.result.evaluations.flatMap(a => a.evaluation.items).find(i => i.item_id === itemId);
  return <div aria-label="리포트 검토">
    <Notification message={error} kind="error" onClose={() => setError('')} /><Notification message={message} onClose={() => setMessage('')} />
    {data && <>
      <Scores run={data.result} play={play} />
      <h3>점수 검토·수정</h3><p className="fine">AI 원결과를 보존하며 수정 사유를 기록합니다. 현재 수정 버전 {data.revision}</p>
      <button disabled={busy} onClick={() => { void api<View>(base).then(v => { setData(v); setDraftSource({ score: '', text: '' }); setDraftKey(k => k + 1); setError(''); }).catch(e => setError(e.message)); }}>최신 결과로 검토 입력 다시 열기</button>
      <details><summary>항목 선택지·미관찰 상태 수정</summary>
        <label>수정할 항목<select aria-label="수정할 항목" value={itemId} onChange={e => { setItemId(e.target.value); setDraftSource(s => ({ ...s, score: '' })); }}>{data.result.behavior_items.map(i => <option key={i.item_id} value={i.item_id}>{i.item_id} · {i.text}</option>)}</select></label>
        {current && <form key={`${itemId}-${data.revision}-${draftKey}`} onFocusCapture={() => setDraftSource(s => s.score ? s : { ...s, score: data.source_hash })} onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); const status = String(f.get('status'));
          void act(base, { expected_revision: data.revision, expected_source_hash: draftSource.score || data.source_hash, reason: f.get('reason'), item: { item_id: itemId, status,
            selected_option_id: status === 'scored' ? f.get('option') : null, evidence_ids: f.getAll('evidence'), reason: f.get('reason') } });
        }}><fieldset disabled={busy}><label>수정 상태<select aria-label="수정 상태" name="status" defaultValue={data.result.scores?.items.find(i => i.item_id === itemId)?.status}>
          <option value="scored">채점됨</option><option value="not_visible">가림</option><option value="audio_unusable">오디오 판별 불가</option><option value="not_performed">미실시</option>
          <option value="not_applicable">조건 불성립</option><option value="insufficient_evidence">근거 부족</option><option value="conflicting_evidence">근거 충돌</option><option value="rule_pending">규칙 미정</option>
        </select></label><label>허용 선택지<select aria-label="허용 선택지" name="option" defaultValue={current.selected_option_id ?? choices?.options[0]?.option_id}>{choices?.options.map(o => <option key={o.option_id} value={o.option_id}>{o.text}</option>)}</select></label>
          <p>수정 근거</p>{data.result.evidence.filter(e => e.candidate_item_ids.includes(itemId)).map(e => <label className="check" key={e.evidence_id}><input type="checkbox" name="evidence" value={e.evidence_id} defaultChecked={current.evidence_ids.includes(e.evidence_id)} />{e.observation}</label>)}
          <label>점수 수정 사유<textarea name="reason" required maxLength={2000} /></label><button>점수 수정 저장</button></fieldset></form>}
      </details>
      <section className="report-preview" aria-label="리포트 미리보기"><h3>리포트 미리보기</h3><p role="status">{states[data.status] ?? data.status}</p>
        <button disabled={busy} onClick={() => void act(`${base}/generate`, {}, 'POST')}>현재 점수로 설명 생성·재시도</button>
        {data.image ? <img className="report-image" src={`/api${base}/image?v=${data.revision}`} alt={`대표 프레임 · 원본 ${data.image.second.toFixed(2)}초`} /> : <p className="fine">대표 이미지 미선택</p>}
        <details><summary>대표 이미지 선택</summary><form onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget);
          void act(`${base}/image`, { expected_revision: data.revision, video_id: f.get('video'), second: Number(f.get('second')) });
        }}><fieldset disabled={busy}><label>대표 이미지 원본 영상<select aria-label="대표 이미지 원본 영상" name="video">{data.result.media.map(m => <option key={m.video_id} value={m.video_id}>{m.video_id.slice(0, 8)} · {m.duration_sec}초</option>)}</select></label>
          <label>원본 프레임 시간 (초)<input name="second" type="number" min="0" step="0.01" required defaultValue="1" /></label><button>대표 프레임 저장</button></fieldset></form></details>
        <h4>표지 요약</h4><p>{data.report?.cover.text ?? '현재 점수에 맞는 설명을 준비해 주세요. 오래된 설명은 내보내기에서 제외됩니다.'}</p>
        <h4>4영역 비교 · 매핑 미정</h4><div className="score-grid">{[1, 2, 3, 4].map(slot => <div className="score-card" key={slot}><strong>영역 {slot}</strong>
          <p>자기인식: 매핑 미정<br />AI관찰: 매핑 미정</p><p>{data.report?.domains.find(d => d.slot === slot)?.comment ?? '대응·통합·가중치 확정 전 수치 대조를 보류합니다.'}</p>
          {data.report?.domains.find(d => d.slot === slot)?.evidence_ids.map((id, i) => <button key={id} onClick={() => play(id)}>관찰 근거 {i + 1}</button>)}</div>)}</div>
        <h4>②④ 교차 해설</h4><p>{data.report?.cross_type.explanation ?? '경계·명칭 미정으로 관계 유형 분류를 보류합니다.'}</p>
        <h4>오늘의 팁</h4>{data.report ? data.report.tips.map((p, i) => <p key={i}>{p.text}</p>) : <p>근거 기반 설명 준비 후 제공됩니다.</p>}
        <p className="notice">진단이 아닌 관찰 기반 제안입니다. 어려움이 지속되면 관련 전문가와 상담해 보세요.</p>
      </section>
      <details><summary>설명 수동 수정</summary><form key={`text-${data.revision}-${data.status}-${draftKey}`} onFocusCapture={() => setDraftSource(s => s.text ? s : { ...s, text: data.source_hash })} onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget);
        const refs = f.getAll('text_evidence'); const part = (name: string) => ({ text: String(f.get(name)), evidence_ids: refs });
        const tips = [part('tip1')]; if (f.get('tip2')) tips.push(part('tip2'));
        void act(base, { expected_revision: data.revision, expected_source_hash: draftSource.text || data.source_hash, reason: f.get('reason'), narration: { cover: part('cover'), comments: [1, 2, 3, 4].map(i => part(`comment${i}`)), cross: part('cross'), tips } });
      }}><fieldset disabled={busy}><label>표지 관계 요약<textarea name="cover" required maxLength={4000} defaultValue={data.report?.cover.text} /></label>
        {[1, 2, 3, 4].map(i => <label key={i}>영역 {i} 코멘트<textarea name={`comment${i}`} required maxLength={4000} defaultValue={data.report?.domains.find(d => d.slot === i)?.comment ?? '영역 대응 미정으로 수치 해석을 보류합니다. 관찰 조건과 자료 한계를 확인하세요.'} /></label>)}
        <label>②④ 교차 해설<textarea name="cross" required maxLength={4000} defaultValue={data.report?.cross_type.explanation ?? '유형 경계와 명칭이 미정이므로 분류를 보류합니다.'} /></label>
        <label>오늘의 팁 1<textarea name="tip1" required maxLength={4000} defaultValue={data.report?.tips[0]?.text} /></label><label>오늘의 팁 2 (선택)<textarea name="tip2" maxLength={4000} defaultValue={data.report?.tips[1]?.text} /></label>
        <p>설명에 연결할 관찰 근거</p>{data.result.evidence.map(e => <label className="check" key={e.evidence_id}><input type="checkbox" name="text_evidence" value={e.evidence_id} />{e.observation}</label>)}
        <label>설명 수정 사유<textarea name="reason" required maxLength={2000} /></label><button>설명 수정 저장</button></fieldset></form></details>
      <details><summary>수정 이력 · {data.history.length}건</summary>{data.history.map(h => <p key={h.revision}>수정 {h.revision} · {h.actor} · {new Date(h.at).toLocaleString()} · {h.reason}</p>)}</details>
      <Exports caseId={caseId} runId={runId} />
    </>}
  </div>;
}

export function ReportSettings() {
  type Settings = { version: string; selection: { provider: string; model: string }; key_available: boolean };
  const [data, setData] = useState<Settings | null>(null); const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { void api<Settings>('/developer/report').then(setData).catch(e => setError(e.message)); }, []);
  return <section className="panel"><h2>리포트 설명 공급자</h2>{data && <form onSubmit={e => { e.preventDefault(); setMessage(''); setError('');
    void api<Settings>('/developer/report', 'PUT', { expected_version: data.version, selection: data.selection }).then(v => { setData(v); setMessage('새 실행에 설명 설정을 적용했습니다.'); }).catch(e => setError(e.message));
  }}><label>설명 공급자<select aria-label="설명 공급자" value={data.selection.provider} onChange={e => setData({ ...data, selection: { provider: e.target.value, model: '' } })}><option value="gemini">Gemini</option><option value="openai">GPT · OpenAI</option><option value="anthropic">Claude · Anthropic</option></select></label>
    <label>설명 모델 ID<input value={data.selection.model} maxLength={150} onChange={e => setData({ ...data, selection: { ...data.selection, model: e.target.value } })} /></label>
    <p className="fine">키 {data.key_available ? '등록됨' : '개발자 설정 필요'} · 신규 실행부터 고정합니다.</p><button>새 실행에 설명 설정 적용</button></form>}<Notification message={error} kind="error" onClose={() => setError('')} /><Notification message={message} onClose={() => setMessage('')} /></section>;
}
