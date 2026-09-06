const statusNames: Record<string, string> = {
  scored: '채점됨', not_visible: '가림', audio_unusable: '오디오 판별 불가', not_performed: '미실시',
  not_applicable: '조건 불성립', insufficient_evidence: '근거 부족', conflicting_evidence: '근거 충돌', rule_pending: '규칙 미정',
};
const domainNames: Record<string, string> = { EDU: '보호자 교육태도', SOC_P: '사회성 · 사람', SOC_D: '사회성 · 개 대리지표',
  SOC_E: '사회성 · 환경', ATT: '친밀·애착', CON: '정서적 일관성', TRN: '훈련' };
type ItemScore = { item_id: string; raw_score: number | null; direction: string | null; status: string; reason: string };
export type ScoreData = {
  evaluations: { evaluation: { branch: string; items: { item_id: string; selected_option_id: string | null; evidence_ids: string[] }[] }; usage: { reused?: boolean } }[];
  scores: { scoring_rule_version: string; items: ItemScore[]; domains: { domain: string; mean: number | null; maximum: number | null;
    valid_count: number; target_count: number; direction: string | null; direction_a_sum: number; direction_b_sum: number }[] } | null;
  survey_scores: { status: string; overall_reference: number | null; scoring_rule_version: string;
    groups: { group: string; mean: number | null; status: string; valid_count: number; target_count: number | null }[];
    items: { item_id: string; raw: number | null; converted: number | null; source_layer: string; status: string }[] } | null;
  behavior_items: { item_id: string; text: string; domain: string | null; options: { option_id: string; text: string }[] }[];
};
const value = (n: number | null) => n === null ? '—' : n.toFixed(2);

export function Scores({ run, play }: { run: ScoreData; play: (id: string) => void }) {
  return <div className="scores" aria-label="평가·점수 결과">
    <h3>행동 평가·점수</h3>
    <div className="toolbar">{['dog', 'owner'].map(branch => <span className="tag" key={branch}>
      {branch === 'dog' ? '반려견' : '보호자'} {run.evaluations.some(e => e.evaluation.branch === branch) ? '평가 완료' : '평가 미완료'}
    </span>)}</div>
    {run.scores && <>
      <p className="fine">완료된 분기의 점수를 즉시 표시합니다. 평균은 유효 항목만 계산하며 대상 수는 전체 영역 기준입니다. 규칙 {run.scores.scoring_rule_version} · 행동 원점수는 설문과 방향이 다릅니다.</p>
      <div className="score-grid">{run.scores.domains.map(d => <div className="score-card" key={d.domain}>
        <strong>{domainNames[d.domain]}</strong><p>평균 {value(d.mean)} · 최고 {value(d.maximum)}</p>
        <small>유효 {d.valid_count}/{d.target_count} · 방향 {d.direction ?? '없음'}<br />A 합 {value(d.direction_a_sum)} · B 합 {value(d.direction_b_sum)}</small>
      </div>)}</div>
      {run.evaluations.map(a => <details key={a.evaluation.branch}><summary>{a.evaluation.branch === 'dog' ? '반려견 36항목' : '보호자 19항목'} · 선택지·상태·근거{a.usage.reused ? ' · 이전 평가 재사용' : ''}</summary>
        {a.evaluation.items.map(item => {
          const score = run.scores!.items.find(s => s.item_id === item.item_id)!;
          const catalog = run.behavior_items.find(c => c.item_id === item.item_id);
          return <details className="score-item" key={item.item_id}><summary>{item.item_id} · {catalog?.text} · {statusNames[score.status]}{score.raw_score !== null ? ` ${value(score.raw_score)}점` : ''}{catalog?.domain === null ? ' · 참고' : ''}</summary>
            {item.selected_option_id && <p>{catalog?.options.find(o => o.option_id === item.selected_option_id)?.text}</p>}
            <p>{score.reason}</p><div className="toolbar">{item.evidence_ids.map((id, index) => <button key={id} onClick={() => play(id)}>근거 {index + 1} 재생</button>)}</div>
          </details>;
        })}
      </details>)}
    </>}
    <p className="fine">DOG-12·OWN-14는 시간 경계·선택 규칙 확인 전 채점을 보류합니다. 규칙 미정과 관찰 부족은 서로 다른 상태입니다.</p>
    {run.survey_scores && <>
      <h3>설문 계산</h3><p>{run.survey_scores.status === 'unregistered' ? '설문 미등록' : `원 척도 참고 전체값 ${value(run.survey_scores.overall_reference)}`}</p>
      <p className="fine">A·C-1·D 평균을 같은 비중으로 계산합니다. 필요한 문항이 누락되면 해당 평균은 표시하지 않습니다. B는 참고값입니다.</p>
      <div className="score-grid">{run.survey_scores.groups.map(g => <div className="score-card" key={g.group}><strong>{g.group}</strong>
        <p>{g.status === 'rule_pending' ? '규칙 미정' : `평균 ${value(g.mean)}`}</p><small>{g.target_count === null ? '문항 포함 규칙 미정' : `응답 ${g.valid_count}/${g.target_count}`}</small></div>)}</div>
      <details><summary>설문 30문항 원응답·환산값</summary><div className="survey-values">{run.survey_scores.items.map(q => <p key={q.item_id}>{q.item_id} · {q.source_layer} · 원응답 {q.raw ?? '미응답'} → {q.status === 'rule_pending' ? '규칙 미정' : q.converted ?? '미응답'}</p>)}</div></details>
    </>}
    <p className="notice">q23/C-2, 4영역 대응과 ②④ 유형은 규칙 미정입니다. 설명·내보내기는 후속 단계에서 제공됩니다.</p>
  </div>;
}
