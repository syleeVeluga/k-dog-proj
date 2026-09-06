import { Notification } from './Notification';
import { useEffect, useRef, useState } from 'react';
import { api, accessLost } from './api';
import { Scores, statusNames } from './Scores';
import type { ScoreData } from './Scores';
import type { Video } from './types';
import { mayLeave, useEditBase } from './Editing';
import { Exports } from './Exports';
export { Exports } from './Exports';

type TextPart = { text: string; evidence_ids: string[] };
type Report = { cover: TextPart; domains: { slot: number; comment: string; evidence_ids: string[] }[];
  cross_type: { explanation: string; evidence_ids: string[] }; tips: TextPart[]; notice: string };
type Result = ScoreData & { evidence: { evidence_id: string; video_id: string; observation: string; candidate_item_ids: string[] }[];
  media: { video_id: string; duration_sec: number }[] };
type View = { revision: number; source_hash: string; status: string; report: Report | null;
  result: Result; image: { video_id: string; second: number } | null;
  history: { actor: string; at: string; revision: number; reason: string; kind: string; before?: unknown; after?: unknown }[] };
const states: Record<string, string> = { ready: '설명 준비됨', manual: '수동 설명 저장됨', stale: '설명 갱신 필요',
  running: '설명 생성 중', not_started: '설명 미준비', retry_wait: '설명 재시도 대기', failed: '설명 실패 · 실패 단계와 연결 설정을 확인하세요' };
type Save = (body: object, suffix?: string, method?: string) => Promise<boolean>;

function HistoryValue({ value, kind, result }: { value: unknown; kind: string; result: Result }) {
  if (!value) return <p className="fine">이전 기록 없음</p>;
  const evidence = (ids: string[]) => <ul>{ids.map(id => <li key={id}>{result.evidence.find(e => e.evidence_id === id)?.observation ?? id}</li>)}</ul>;
  if (kind === 'score') {
    const item = value as { item_id: string; status: string; selected_option_id: string | null; reason: string; evidence_ids: string[] };
    const catalog = result.behavior_items.find(i => i.item_id === item.item_id);
    return <><p>{item.item_id} · {catalog?.text}</p><p>{statusNames[item.status] ?? item.status} · {catalog?.options.find(o => o.option_id === item.selected_option_id)?.text ?? '선택지 없음'}</p><p>{item.reason}</p>{evidence(item.evidence_ids)}</>;
  }
  if (kind === 'text') {
    const report = value as Report;
    const parts = [{ label: '표지 요약', ...report.cover }, ...report.domains.map(d => ({ label: `영역 ${d.slot}`, text: d.comment, evidence_ids: d.evidence_ids })),
      { label: '②④ 교차 해설', text: report.cross_type.explanation, evidence_ids: report.cross_type.evidence_ids }, ...report.tips.map((p, i) => ({ label: `오늘의 팁 ${i + 1}`, ...p }))];
    return <>{parts.map(p => <div key={p.label}><h4>{p.label}</h4><p>{p.text}</p>{evidence(p.evidence_ids)}</div>)}</>;
  }
  return <p className="fine">상세 기록은 내보낸 파일에서 확인하세요.</p>;
}

function ScoreEditor({ data, itemId, setItemId, save, busy, play }: {
  data: View; itemId: string; setItemId: (id: string) => void; save: Save; busy: boolean; play: (id: string) => void;
}) {
  const edit = useEditBase(data);
  const view = edit.view;
  const choices = view.result.behavior_items.find(i => i.item_id === itemId);
  const current = view.result.evaluations.flatMap(a => a.evaluation.items).find(i => i.item_id === itemId);
  const changed = view.source_hash !== data.source_hash || view.revision !== data.revision;
  return <details className="review-editor" open><summary>항목 선택지·미관찰 상태 수정</summary>
    <label>수정할 항목<select aria-label="수정할 항목" value={itemId} onChange={e => { if (edit.discard()) setItemId(e.target.value); }}>{data.result.behavior_items.map(i => <option key={i.item_id} value={i.item_id}>{i.item_id} · {i.text}</option>)}</select></label>
    {edit.dirty && <p role="status">점수 수정 입력 · 저장 전</p>}
    {changed && <p className="warning">새 결과가 도착했습니다. 입력은 보존되었습니다. 최신 결과와 비교한 뒤 다시 입력하거나 저장하세요.</p>}
    <button disabled={busy} onClick={edit.discard}>최신 결과로 검토 입력 다시 열기</button>
    {current ? <form key={`${itemId}-${view.revision}-${edit.key}`} onFocusCapture={edit.capture} onChange={edit.change} onSubmit={e => {
      e.preventDefault(); const f = new FormData(e.currentTarget); const status = String(f.get('status'));
      void save({ expected_revision: view.revision, expected_source_hash: view.source_hash, reason: f.get('reason'), item: { item_id: itemId, status,
        selected_option_id: status === 'scored' ? f.get('option') : null, evidence_ids: f.getAll('evidence'), reason: f.get('reason') } }).then(ok => { if (ok) edit.reset(); });
    }}><fieldset disabled={busy}>
      <p className="fine">현재 저장값: {choices?.options.find(o => o.option_id === current.selected_option_id)?.text ?? '미채점'} · 수정 버전 {view.revision}</p>
      <label>수정 상태<select aria-label="수정 상태" name="status" defaultValue={view.result.scores?.items.find(i => i.item_id === itemId)?.status}>
        <option value="scored">채점됨</option><option value="not_visible">가림</option><option value="audio_unusable">오디오 판별 불가</option><option value="not_performed">미실시</option>
        <option value="not_applicable">조건 불성립</option><option value="insufficient_evidence">근거 부족</option><option value="conflicting_evidence">근거 충돌</option><option value="rule_pending">규칙 미정</option>
      </select></label><label>허용 선택지<select aria-label="허용 선택지" name="option" defaultValue={current.selected_option_id ?? choices?.options[0]?.option_id}>{choices?.options.map(o => <option key={o.option_id} value={o.option_id}>{o.text}</option>)}</select></label>
      <p>수정 근거</p>{view.result.evidence.filter(e => e.candidate_item_ids.includes(itemId)).map(e => <div key={e.evidence_id}><label className="check"><input type="checkbox" name="evidence" value={e.evidence_id} defaultChecked={current.evidence_ids.includes(e.evidence_id)} />{e.observation}</label><button type="button" onClick={() => play(e.evidence_id)}>수정 근거 재생</button></div>)}
      <label>점수 수정 사유<textarea name="reason" required maxLength={2000} /></label><button>점수 수정 저장</button>
    </fieldset></form> : <p>이 항목의 평가가 준비되지 않았습니다. 완료된 항목을 선택하세요.</p>}
  </details>;
}

function NarrationEditor({ data, save, busy, play }: { data: View; save: Save; busy: boolean; play: (id: string) => void }) {
  const edit = useEditBase(data); const view = edit.view;
  const parts = [{ name: 'cover', label: '표지 관계 요약', part: view.report?.cover },
    ...[1, 2, 3, 4].map(i => { const d = view.report?.domains.find(d => d.slot === i); return { name: `comment${i}`, label: `영역 ${i} 코멘트`, part: d ? { text: d.comment, evidence_ids: d.evidence_ids } : undefined }; }),
    { name: 'cross', label: '②④ 교차 해설', part: view.report ? { text: view.report.cross_type.explanation, evidence_ids: view.report.cross_type.evidence_ids } : undefined },
    { name: 'tip1', label: '오늘의 팁 1', part: view.report?.tips[0] }, { name: 'tip2', label: '오늘의 팁 2 (선택)', part: view.report?.tips[1] }];
  return <details><summary>설명 수동 수정</summary>
    {edit.dirty && <p role="status">설명 수정 입력 · 저장 전</p>}
    {(view.source_hash !== data.source_hash || view.revision !== data.revision || view.status !== data.status) && <p className="warning">새 결과가 도착했습니다. 작성 중인 설명은 유지합니다.</p>}
    <button disabled={busy} onClick={edit.discard}>최신 설명 불러오기 · 미저장 입력 초기화</button>
    <form key={`${view.revision}-${view.status}-${edit.key}`} onFocusCapture={edit.capture} onChange={edit.change} onSubmit={e => {
      e.preventDefault(); const f = new FormData(e.currentTarget);
      const part = (name: string) => ({ text: String(f.get(name)), evidence_ids: f.getAll(`${name}_evidence`) });
      const tips = [part('tip1')]; if (f.get('tip2')) tips.push(part('tip2'));
      void save({ expected_revision: view.revision, expected_source_hash: view.source_hash, reason: f.get('reason'), narration: { cover: part('cover'), comments: [1, 2, 3, 4].map(i => part(`comment${i}`)), cross: part('cross'), tips } }).then(ok => { if (ok) edit.reset(); });
    }}><fieldset disabled={busy}>{parts.map(p => <section className="narration-part" key={p.name}>
      <label>{p.label}<textarea name={p.name} required={p.name !== 'tip2'} maxLength={4000} defaultValue={p.part?.text ?? (p.name.startsWith('comment') ? '영역 대응 미정으로 수치 해석을 보류합니다. 관찰 조건과 자료 한계를 확인하세요.' : p.name === 'cross' ? '유형 경계와 명칭이 미정이므로 분류를 보류합니다.' : '')} /></label>
      <details><summary>{p.label}에 연결할 근거</summary>{view.result.evidence.map(e => <div key={e.evidence_id}><label className="check"><input type="checkbox" name={`${p.name}_evidence`} value={e.evidence_id} defaultChecked={p.part?.evidence_ids.includes(e.evidence_id)} />{e.observation}</label><button type="button" onClick={() => play(e.evidence_id)}>문단 근거 재생</button></div>)}</details>
    </section>)}<label>설명 수정 사유<textarea name="reason" required maxLength={2000} /></label><button>설명 수정 저장</button></fieldset></form>
  </details>;
}

function FrameEditor({ data, videos, base, save, busy }: { data: View; videos: Video[]; base: string; save: Save; busy: boolean }) {
  const [videoId, setVideoId] = useState(data.image?.video_id ?? data.result.media[0]?.video_id ?? '');
  const [second, setSecond] = useState(data.image?.second ?? 1);
  const player = useRef<HTMLVideoElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (!videoId && data.result.media.length) setVideoId(data.result.media[0].video_id); }, [videoId, data.result.media]);
  const media = data.result.media.find(m => m.video_id === videoId);
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>대표 이미지 선택</summary><form onSubmit={e => { e.preventDefault(); void save({ expected_revision: data.revision, video_id: videoId, second }, '/image'); }}><fieldset disabled={busy}>
    <label>대표 이미지 원본 영상<select aria-label="대표 이미지 원본 영상" value={videoId} onChange={e => { setVideoId(e.target.value); setSecond(0); }}>{data.result.media.map(m => <option key={m.video_id} value={m.video_id}>{videos.find(v => v.video_id === m.video_id)?.original_name ?? m.video_id.slice(0, 8)} · {videos.find(v => v.video_id === m.video_id)?.camera_id} · {m.duration_sec.toFixed(1)}초</option>)}</select></label>
    {open && videoId && <video ref={player} controls preload="none" src={`/api${base.replace('/reports/', '/analysis/')}/videos/${videoId}`} />}
    <button type="button" onClick={() => setSecond(Number((player.current?.currentTime ?? 0).toFixed(2)))}>현재 재생 위치 선택</button>
    <label>원본 프레임 시간 (초)<input name="second" type="number" min="0" max={media ? Math.max(0, media.duration_sec - 0.01) : 0} step="0.01" required value={second} onChange={e => setSecond(Number(e.target.value))} /></label><button disabled={!media}>대표 프레임 저장</button>
  </fieldset></form></details>;
}

export function Reports({ caseId, runId, play, videos = [] }: { caseId: string; runId: string; play: (id: string) => void; videos?: Video[] }) {
  const [data, setData] = useState<View | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [message, setMessage] = useState('');
  const [itemId, setItemId] = useState('BS-01');
  const base = `/cases/${caseId}/reports/${runId}`;
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const next = await api<View>(base); if (active) setData(next); }
      catch (e) { if (active) { if (accessLost(e)) setData(null); setError(e instanceof Error ? e.message : '리포트 조회 실패 · 입력은 유지됩니다'); } }
      if (active) timer = setTimeout(poll, 3000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [base]);
  const save: Save = async (body, suffix = '', method = 'PUT') => {
    setBusy(true); setError(''); setMessage('');
    try { const next = await api<View>(base + suffix, method, body); if (method === 'PUT') setData(next); setMessage(method === 'PUT' ? '저장했습니다.' : '설명 생성을 요청했습니다.'); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '저장 실패'); return false; }
    finally { setBusy(false); }
  };
  return <div aria-label="리포트 검토"><Notification message={error} kind="error" onClose={() => setError('')} /><Notification message={message} onClose={() => setMessage('')} />
    {data && <>
      <div className="review-workspace"><Scores run={data.result} play={play} selectedItem={itemId} onSelect={id => { if (id === itemId || mayLeave()) setItemId(id); }} />
        <section><h3>점수 검토·수정</h3><p className="fine">AI 원결과를 보존하며 수정 사유를 기록합니다. 현재 수정 버전 {data.revision}</p>
          <ScoreEditor key={`${runId}-${itemId}`} data={data} itemId={itemId} setItemId={setItemId} save={save} busy={busy} play={play} />
        </section></div>
      <section className="report-preview" aria-label="리포트 미리보기"><h3>리포트 미리보기</h3><p role="status">{states[data.status] ?? data.status}</p>
        {data.status === 'stale' && <p className="warning">점수가 바뀌어 이전 설명은 내보내기에서 제외됩니다. 현재 점수로 설명을 갱신하거나 직접 수정하세요.</p>}
        <button disabled={busy || ['running', 'retry_wait'].includes(data.status)} onClick={() => void save({}, '/generate', 'POST')}>현재 점수로 설명 생성·재시도</button>
        {data.image ? <img className="report-image" src={`/api${base}/image?v=${data.revision}`} alt={`대표 프레임 · 원본 ${data.image.second.toFixed(2)}초`} /> : <p className="fine">대표 이미지 미선택</p>}
        <FrameEditor data={data} videos={videos} base={base} save={save} busy={busy} />
        <h4>표지 요약</h4><p>{data.report?.cover.text ?? '현재 점수에 맞는 설명을 준비해 주세요. 오래된 설명은 내보내기에서 제외됩니다.'}</p>
        <h4>4영역 비교 · 매핑 미정</h4><div className="score-grid">{[1, 2, 3, 4].map(slot => <div className="score-card" key={slot}><strong>영역 {slot}</strong>
          <p>자기인식: 매핑 미정<br />AI관찰: 매핑 미정</p><p>{data.report?.domains.find(d => d.slot === slot)?.comment ?? '대응·통합·가중치 확정 전 수치 대조를 보류합니다.'}</p>
          {data.report?.domains.find(d => d.slot === slot)?.evidence_ids.map((id, i) => <button key={id} onClick={() => play(id)}>관찰 근거 {i + 1}</button>)}</div>)}</div>
        <h4>②④ 교차 해설</h4><p>{data.report?.cross_type.explanation ?? '경계·명칭 미정으로 관계 유형 분류를 보류합니다.'}</p>
        <h4>오늘의 팁</h4>{data.report ? data.report.tips.map((p, i) => <p key={i}>{p.text}</p>) : <p>근거 기반 설명 준비 후 제공됩니다.</p>}
        <p className="fine">진단이 아닌 관찰 기반 제안입니다. 어려움이 지속되면 관련 전문가와 상담해 보세요.</p>
      </section>
      <NarrationEditor data={data} save={save} busy={busy} play={play} />
      <details><summary>수정 이력 · {data.history.length}건</summary>{data.history.map(h => <section key={h.revision}><p>수정 {h.revision} · {h.actor} · {new Date(h.at).toLocaleString()} · {h.reason}</p>
        {(h.before !== undefined || h.after !== undefined) && <div className="history-comparison"><div><strong>수정 전</strong><HistoryValue value={h.before} kind={h.kind} result={data.result} /></div><div><strong>수정 후</strong><HistoryValue value={h.after} kind={h.kind} result={data.result} /></div></div>}
      </section>)}</details>
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
