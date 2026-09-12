import { useState } from 'react';
export const statusNames: Record<string, string> = {
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
  single_view_item_ids?: string[];
  review_overridden_item_ids?: string[];
};
const value = (n: number | null) => n === null ? '—' : n.toFixed(2);

export function Scores({ run, play, selectedItem, onSelect }: { run: ScoreData; play: (id: string) => void; selectedItem?: string; onSelect?: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [domain, setDomain] = useState('all');
  const counts = Object.fromEntries(Object.keys(statusNames).map(s => [s, run.scores?.items.filter(i => i.status === s).length ?? 0]));
  const matching = (item: ItemScore) => {
    const catalog = run.behavior_items.find(c => c.item_id === item.item_id);
    return `${item.item_id} ${catalog?.text}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || item.status === status)
      && (domain === 'all' || catalog?.domain === domain);
  };
  return <div className="scores" aria-label="평가·점수 결과">
    <h3>행동 평가·점수</h3>
    <div className="toolbar">{['dog', 'owner'].map(branch => <span className="tag" key={branch}>
      {branch === 'dog' ? '반려견' : '보호자'} {run.evaluations.some(e => e.evaluation.branch === branch) ? '처리 완료' : '처리 중/미실행'} · 유효 {run.scores?.items.filter(i => i.status === 'scored' && (branch === 'owner' ? i.item_id.startsWith('OWN') : !i.item_id.startsWith('OWN'))).length ?? 0}/{branch === 'dog' ? 36 : 19}
    </span>)}</div>
    {run.scores && <>
      <p className="fine">완료된 분기의 점수를 즉시 표시합니다. 평균은 유효 항목만 계산하며 대상 수는 전체 영역 기준입니다. 규칙 {run.scores.scoring_rule_version} · 행동 원점수: 1 양호 → 5 문제 방향. 설문: 환산 후 높을수록 긍정.</p>
      <div className="score-grid">{run.scores.domains.map(d => <div className="score-card" key={d.domain}>
        <strong>{domainNames[d.domain]}</strong><p>평균 {value(d.mean)} · 최고 {value(d.maximum)}</p>
        <strong className={d.valid_count < d.target_count ? 'coverage partial' : 'coverage'}>유효 {d.valid_count}/{d.target_count}{d.valid_count < d.target_count ? ' · 부분/미채점' : ''}</strong>
        <small>방향 {d.valid_count === 0 ? '판정 불가' : d.direction === 'A' ? 'A 과함' : d.direction === 'B' ? 'B 위축' : '우세 방향 없음'}</small>
        <details><summary>방향 계산 근거</summary><small>A 과함 합 {value(d.direction_a_sum)} · B 위축 합 {value(d.direction_b_sum)}</small></details>
      </div>)}</div>
      <div className="review-filters"><label>검토 항목 검색<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="항목 ID 또는 이름" /></label>
        <label>검토 상태<select value={status} onChange={e => setStatus(e.target.value)}><option value="all">모든 상태</option>{Object.entries(statusNames).map(([id, name]) => <option key={id} value={id}>{name} {counts[id]}개</option>)}</select></label>
        <label>검토 영역<select value={domain} onChange={e => setDomain(e.target.value)}><option value="all">모든 영역</option>{Object.entries(domainNames).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      </div>
      <p className="warning">유효 채점 {counts.scored}개 · 근거 충돌 {counts.conflicting_evidence}개 · 근거 부족 {counts.insufficient_evidence}개 · 규칙 미정 {counts.rule_pending}개{run.single_view_item_ids?.length ? ` · 영상 1개 단독 판정 ${run.single_view_item_ids.length}개` : ''}{run.review_overridden_item_ids?.length ? ` · 재검토로 보류 해제 ${run.review_overridden_item_ids.length}개` : ''}</p>
      <div className="assessment-list" aria-label="검토 항목 목록">{run.scores.items.filter(matching).map(score => {
        const catalog = run.behavior_items.find(c => c.item_id === score.item_id);
        const item = run.evaluations.flatMap(a => a.evaluation.items).find(i => i.item_id === score.item_id);
        return <article className={selectedItem === score.item_id ? 'score-item selected' : 'score-item'} key={score.item_id}>
          <div className="section-title"><strong>{score.item_id} · {catalog?.text}</strong>{onSelect && <button aria-label={`${score.item_id} 검토하기`} onClick={() => onSelect(score.item_id)}>검토하기</button>}</div>
          <p>{statusNames[score.status]}{score.raw_score !== null ? ` · ${value(score.raw_score)}점` : ''}{catalog?.domain === null ? ' · 참고 항목' : ''}
            {run.single_view_item_ids?.includes(score.item_id) && <span className="tag">영상 1개 단독 판정 · 교차 확인 없음</span>}
            {run.review_overridden_item_ids?.includes(score.item_id) && <span className="tag">재검토로 보류 해제</span>}</p>
          <details><summary>선택지·사유·근거</summary><p>{catalog?.options.find(o => o.option_id === item?.selected_option_id)?.text}</p><p>{score.reason}</p>
            <div className="toolbar">{item?.evidence_ids.map((id, i) => <button key={id} onClick={() => play(id)}>근거 {i + 1} 재생</button>)}</div>
          </details>
        </article>;
      })}</div>
      {!run.scores.items.some(matching) && <p>조건에 맞는 항목이 없습니다.</p>}
    </>}
    <p className="fine">DOG-12·OWN-14는 시간 경계·선택 규칙 확인 전 채점을 보류합니다. 규칙 미정과 관찰 부족은 서로 다른 상태입니다.</p>
    {run.survey_scores && <>
      <h3>설문 계산</h3><p>{run.survey_scores.status === 'unregistered' ? '설문 미등록' : `원 척도 참고 전체값 ${value(run.survey_scores.overall_reference)}`}</p>
      <p className="fine">A·C-1·D 평균을 같은 비중으로 계산합니다. 필요한 문항이 누락되면 해당 평균은 표시하지 않습니다. B는 참고값입니다.</p>
      <div className="score-grid">{run.survey_scores.groups.map(g => <div className="score-card" key={g.group}><strong>{({ A: '가르치는 방식', 'C-1': '정서적 애정', D: '안정적 반응', B: '사회화 참고', 'C-2': '애착 참고' } as Record<string, string>)[g.group]} ({g.group})</strong>
        <p>{g.status === 'rule_pending' ? '규칙 미정' : `평균 ${value(g.mean)}`}</p><small>{g.target_count === null ? '문항 포함 규칙 미정' : `응답 ${g.valid_count}/${g.target_count}`}</small></div>)}</div>
      <details><summary>설문 30문항 원응답·환산값</summary><div className="survey-values">{run.survey_scores.items.map(q => <p key={q.item_id}>{q.item_id} · {q.source_layer} · 원응답 {q.raw ?? '미응답'} → {q.status === 'rule_pending' ? '규칙 미정' : q.converted ?? '미응답'}</p>)}</div></details>
    </>}
    <p className="warning">q23/C-2, 4영역 대응과 ②④ 유형은 규칙 미정입니다.</p>
  </div>;
}
