import { useEffect, useState } from 'react';
import { api } from './api';
import type { Case } from './types';
import { Reports } from './Reports';
import type { ScoreData } from './Scores';

export const analysisNames: Record<string, string> = {
  queued: '대기', running: '분석 중', retry_wait: '재시도 대기', observed: '관찰 완료', scored: '점수 준비됨',
  partial_failed: '일부 실패', failed: '실패', settings_required: '개발자 설정 필요', stopped: '중지',
};
const errorNames: Record<string, string> = {
  developer_settings_required: '개발자 설정 필요', provider_connection_lost: '공급자 응답 유실',
  observation_schema_invalid: '관찰 구조·시간 검증 실패', observation_incomplete: '관찰 응답 미완료',
  evaluation_schema_invalid: '평가 항목·근거 검증 실패', evaluation_incomplete: '평가 응답 미완료', evaluation_refused: '공급자 평가 거절',
  worker_interrupted: 'worker 중단', artifact_invalid: '저장 결과 검증 실패',
  remote_processing_timeout: '원격 영상 준비 시간 초과', remote_file_failed: '원격 영상 준비 실패',
};
type Evidence = { evidence_id: string; video_id: string; camera_id: string; source_start_sec: number;
  source_end_sec: number; observation: string; candidate_item_ids: string[]; quality_flags: string[] };
type ObservationRun = ScoreData & { run_id: string; input_revision: number; status: string; is_current: boolean;
  evidence: Evidence[]; media_errors: Record<string, string>; unconfirmed_conditions: string[]; reused_from: string[];
  media: { video_id: string; duration_sec: number; codec: string; width: number; height: number; audio_status: string }[];
  steps: { stage: string; branch_key: string; attempt: number; status: string; retry_at: string | null; usage: Record<string, string | number | boolean> }[] };
type Analysis = { configured: boolean; message: string; runs: ObservationRun[] };

export function Observations({ item, writable }: { item: Case; writable: boolean }) {
  const [data, setData] = useState<Analysis | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState('');
  const [reuse, setReuse] = useState(false);
  const [playing, setPlaying] = useState<Evidence | null>(null);
  const base = `/cases/${item.case_id}/analysis`;
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<Analysis>(base);
        if (active) {
          setData(result); setError('');
          setPlaying(previous => previous && result.runs.some(r => r.evidence.some(e => e.evidence_id === previous.evidence_id)) ? previous : null);
        }
      } catch (e) {
        if (active) { setData(null); setPlaying(null); setError(e instanceof Error ? e.message : '관찰 상태 조회 실패'); }
      }
      if (active) timer = setTimeout(poll, 3000);
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [base]);
  const current = data?.runs.find(r => r.run_id === selected) ?? data?.runs.find(r => r.is_current) ?? data?.runs[0];
  async function act(path: string, body?: object) {
    setBusy(true); setError('');
    try {
      const result = await api<Analysis>(path, 'POST', body);
      setData(result); setPlaying(null);
      if (path === base) setSelected(result.runs.find(r => r.is_current)?.run_id ?? '');
    } catch (e) { setError(e instanceof Error ? e.message : '관찰 요청 실패'); }
    finally { setBusy(false); }
  }
  const active = current && ['queued', 'running', 'retry_wait'].includes(current.status);
  return <section className="panel" aria-label="영상 관찰">
    <div className="section-title"><h2>영상 관찰·행동 평가</h2><span className="tag">{current ? analysisNames[current.status] : '실행 전'}</span></div>
    <p className="fine">{data?.message ?? '분석 상태 확인 중…'} 화면을 닫아도 백그라운드 처리는 계속됩니다. 완료된 분기부터 점수를 확인할 수 있습니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {writable && <fieldset disabled={busy}><div className="toolbar">
      <button className="primary" disabled={!item.consent?.video_analysis || !item.consent?.external_ai}
        onClick={() => void act(base, { expected_revision: item.input_revision, reuse_run_id: reuse && current ? current.run_id : null })}>분석 시작</button>
      {current && <label className="check"><input type="checkbox" checked={reuse} disabled={active || !current.steps.some(s => s.stage === 'observe' && s.status === 'succeeded')}
        onChange={e => setReuse(e.target.checked)} />선택 실행의 호환되는 관찰·평가 재사용</label>}
      {active && <button onClick={() => void act(`${base}/${current.run_id}/cancel`)}>분석 중지</button>}
      {current && ['failed', 'partial_failed', 'settings_required'].includes(current.status) &&
        <button onClick={() => void act(`${base}/${current.run_id}/retry`)}>실패 단계 재시도</button>}
    </div><p className="fine">외부 AI 전송 동의가 필요합니다. 실제 실행 시 사용 요금이 발생합니다. 중지해도 이미 전송한 요청의 취소·환불은 보장되지 않습니다.</p></fieldset>}
    {data && data.runs.length > 0 && <label>관찰 실행 이력<select value={current?.run_id ?? ''} onChange={e => { setSelected(e.target.value); setPlaying(null); setReuse(false); }}>
      {data.runs.map(r => <option value={r.run_id} key={r.run_id}>입력 {r.input_revision} · {analysisNames[r.status]} · {r.run_id.slice(0, 8)}{r.is_current ? ' · 현재 표시' : ' · 이전 실행'}</option>)}
    </select></label>}
    {current && <>
      {!current.is_current && <p className="notice">이전 실행 결과입니다. 현재 입력과 다를 수 있습니다.</p>}
      {current.reused_from.length > 0 && <p className="fine">기존 성공 관찰 재사용 · 원본 근거 ID 보존</p>}
      {current.media.map(m => <p className="fine" key={m.video_id}>{item.manifest.sessions.flatMap(s => s.videos).find(v => v.video_id === m.video_id)?.camera_id} · {m.duration_sec.toFixed(1)}초 · {m.width}×{m.height} · {m.codec} · {m.audio_status === 'present' ? '오디오 트랙 있음' : '오디오 없음'}</p>)}
      {Object.entries(current.media_errors).map(([id, message]) => <p className="error" key={id}>{message}</p>)}
      {current.steps.map((s, i) => <p className="fine" key={i}>{s.stage === 'prepare' ? '미디어 검사' : s.stage === 'integrate' ? '근거 통합' : s.stage === 'survey' ? '설문 계산' : s.stage === 'report' ? '리포트 설명' : s.stage === 'evaluate' ? `${s.branch_key === 'dog' ? '반려견' : '보호자'} 평가` : '카메라 관찰'} · 시도 {s.attempt} · {({ succeeded: '완료', running: '처리 중', failed: '실패', retry_wait: '재시도 대기', abandoned: '중단' } as Record<string, string>)[s.status] ?? s.status}
        {s.usage.code && ` · ${errorNames[String(s.usage.code)] ?? s.usage.code}`}{s.retry_at && ` · 재시도 ${new Date(s.retry_at).toLocaleString()}`}
        {s.usage.billing_uncertain === true && ' · 중복 과금 가능'}{s.usage.remote_cleanup_pending === true && ' · 원격 파일 삭제 확인 필요'}</p>)}
      {(current.survey_scores || current.evaluations.length > 0) && <Reports key={current.run_id} caseId={item.case_id} runId={current.run_id} play={id => setPlaying(current.evidence.find(e => e.evidence_id === id) ?? null)} />}
      <p>관찰 근거 {current.evidence.length}개</p>
      {current.unconfirmed_conditions.map((flag, i) => <p className="fine" key={i}>{flag}</p>)}
      {current.evidence.map(e => <div className="video-row" key={e.evidence_id}><div><strong>{e.camera_id} · {e.source_start_sec.toFixed(2)}–{e.source_end_sec.toFixed(2)}초</strong>
        <p>{e.observation}</p><small>{e.candidate_item_ids.join(', ')} · {e.quality_flags.join(', ')}</small></div>
        <button onClick={() => setPlaying(e)}>원본 근거 재생</button></div>)}
      {playing && <div><video key={playing.evidence_id} controls preload="metadata"
        src={`/api/cases/${item.case_id}/analysis/${current.run_id}/videos/${playing.video_id}#t=${playing.source_start_sec},${playing.source_end_sec}`} />
        <button onClick={() => setPlaying(null)}>근거 재생 닫기</button></div>}
      {current.evidence.length > 0 && <p className="fine">동기화 미확인 카메라는 별도 근거로 보존하며 횟수를 합산하지 않습니다. 관찰 내용은 원본과 대조하세요.</p>}
    </>}
  </section>;
}
