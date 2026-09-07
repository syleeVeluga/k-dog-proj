import { statusNames, type ScoreData } from './Scores';

export type Ledger = { video_id: string; unconfirmed_conditions: string[];
  events: { step: string; kind: string; start_sec: number; end_sec: number; subject: string; modality: string;
    command: string; observation: string; quality_flags: string[] }[];
  measures: { command_counts?: { step: string; command: string | null; count: number; talk_count: number; scored: boolean }[] } };

export type VideoAssessment = { video_id: string; branch: 'dog' | 'owner' | null; review_item_ids: string[]; video_items: {
  item_id: string; status: string; selected_option_id: string | null; reason: string;
  coverage: string; coverage_reason: string; evidence_ids: string[];
  measurements: { kind: string; value: number; start_sec: number; end_sec: number }[];
}[] };

const coverageNames: Record<string, string> = { sufficient: '판정 범위 충분', partial: '일부만 관찰', none: '관찰 불가' };
const branchNames: Record<string, string> = { dog: '반려견·행동신호', owner: '보호자' };
const stepNames: Record<string, string> = { entry: '입장', baseline_no_response: '무반응 10초 기준선', separation: '분리',
  reunion: '재회', command_1: '지시① 앉아', command_2: '지시②', command_3: '지시③ 엎드려', command_4: '지시④ 앉아',
  play: '놀이', exit: '퇴장', unknown: '미확정' };
const kindNames: Record<string, string> = { command_utterance: '구령 발화', dog_performance: '개의 수행',
  reward_response: '보상 반응', owner_exit: '보호자 퇴장', owner_return: '보호자 재입장', dog_settled: '개 안정',
  play_cue: '놀이 지시·말', other: '그 밖의 사건' };
const measurementNames: Record<string, string> = { command_count: '구령 횟수', behavior_count: '행동 횟수', duration_sec: '지속 시간(초)', latency_sec: '반응 시간(초)' };

export function VideoAssessments({ assessments, ledgers, catalog, name, play }: {
  assessments: VideoAssessment[]; ledgers: Ledger[]; catalog: ScoreData['behavior_items'];
  name: (id: string) => string; play: (id: string) => void;
}) {
  return <div aria-label="영상별 평가 결과"><h3>영상별 평가 결과</h3>
    <p className="fine">각 영상은 평가 순서에 따른 사건 원장을 먼저 기록하고, 같은 영상으로 반려견·보호자 분기를 나누어 평가합니다. 구령 횟수 등 두 분기가 공유하는 사실은 원장에서만 계산하며 분기 판단이 이를 다시 추정하지 않습니다. 최종 결과는 충분한 근거가 있는 항목별 판단을 한 번만 채택하고, 다른 선택지는 원본 재검토 후에도 일치하지 않으면 보류합니다.</p>
    {ledgers.map(l => <details key={`ledger-${l.video_id}`}>
      <summary>{name(l.video_id)} · 사건 원장 · 사건 {l.events.length}건</summary>
      {(l.measures.command_counts ?? []).map(c => <p className="fine" key={c.step}>
        {stepNames[c.step] ?? c.step} · 계산된 지시 {c.count}회 · 보호자 발화 {c.talk_count}회{c.scored ? '' : ' · 채점 행 없음'}</p>)}
      {l.events.map((e, n) => <p key={n}>{stepNames[e.step] ?? e.step} · {kindNames[e.kind] ?? e.kind} · {e.start_sec.toFixed(2)}–{e.end_sec.toFixed(2)}초 · {e.observation}</p>)}
      {l.unconfirmed_conditions.map((c, n) => <p className="fine" key={`c-${n}`}>미확인: {c}</p>)}
    </details>)}
    {assessments.map((a, index) => <details key={`${a.video_id}-${a.branch}-${index}`}>
      <summary>{name(a.video_id)} · {a.branch ? branchNames[a.branch] : '전체'} · {a.review_item_ids.length ? '불일치 항목 재검토' : '최초 평가'} · 채점 가능 {a.video_items.filter(i => i.status === 'scored').length}/{a.video_items.length}</summary>
      {a.video_items.map(i => {
        const item = catalog.find(c => c.item_id === i.item_id);
        return <article className="score-item" key={i.item_id}><strong>{i.item_id} · {item?.text}</strong>
          <p>{statusNames[i.status]} · {coverageNames[i.coverage]}</p>
          {i.selected_option_id && <p>선택: {item?.options.find(o => o.option_id === i.selected_option_id)?.text ?? i.selected_option_id}</p>}
          <p>{i.reason}</p><p className="fine">관찰 범위: {i.coverage_reason}</p>
          {i.measurements.map((m, n) => <p className="fine" key={n}>{measurementNames[m.kind]} {m.value} · {m.start_sec.toFixed(2)}–{m.end_sec.toFixed(2)}초</p>)}
          <div className="toolbar">{i.evidence_ids.map((id, n) => <button key={id} onClick={() => play(id)}>{i.item_id} 근거 {n + 1} 재생</button>)}</div>
        </article>;
      })}
    </details>)}
  </div>;
}
