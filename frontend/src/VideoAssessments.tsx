import { statusNames, type ScoreData } from './Scores';

export type VideoAssessment = { video_id: string; review_item_ids: string[]; video_items: {
  item_id: string; status: string; selected_option_id: string | null; reason: string;
  coverage: string; coverage_reason: string; evidence_ids: string[];
  measurements: { kind: string; value: number; start_sec: number; end_sec: number }[];
}[] };

const coverageNames: Record<string, string> = { sufficient: '판정 범위 충분', partial: '일부만 관찰', none: '관찰 불가' };
const measurementNames: Record<string, string> = { command_count: '구령 횟수', behavior_count: '행동 횟수', duration_sec: '지속 시간(초)', latency_sec: '반응 시간(초)' };

export function VideoAssessments({ assessments, catalog, name, play }: {
  assessments: VideoAssessment[]; catalog: ScoreData['behavior_items']; name: (id: string) => string; play: (id: string) => void;
}) {
  return <div aria-label="영상별 평가 결과"><h3>영상별 평가 결과</h3>
    <p className="fine">각 영상에서 판단한 선택지와 관찰 범위입니다. 최종 결과는 충분한 근거가 있는 항목별 판단을 한 번만 채택합니다. 다른 선택지는 원본 재검토 후에도 일치하지 않으면 보류합니다.</p>
    {assessments.map((a, index) => <details key={`${a.video_id}-${index}`}>
      <summary>{name(a.video_id)} · {a.review_item_ids.length ? '불일치 항목 재검토' : '최초 평가'} · 채점 가능 {a.video_items.filter(i => i.status === 'scored').length}/{a.video_items.length}</summary>
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
