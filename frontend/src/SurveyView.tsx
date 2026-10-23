import { SURVEY_TOTAL, surveyDomains } from './types';
import { surveyStatus } from './surveyStatus';
import type { Catalog, Session } from './types';

// Surveys are registered from CSV/Excel in 일괄 등록; this panel only shows what was registered.
export function SurveyView({ session, catalog, expanded = false }: { session: Session; catalog: Catalog; expanded?: boolean }) {
  if (session.survey_version !== catalog.version) return <p className="fine">설문 판본: {session.survey_version} · 이 판본의 원응답 화면은 설문 연결 단계에서 제공됩니다.</p>;
  const counts = surveyStatus(session);
  const domains = [...new Set(catalog.items.map(q => q.print_section ?? q.domain ?? ''))];
  const state = (id: string) => session.survey_not_applicable.includes(id) ? '해당 없음' : session.survey[id] === null || session.survey[id] === undefined ? '미응답' : String(session.survey[id]);
  return <details className="panel" id="survey" open={expanded}><summary>설문 원응답 <span className="tag">{counts.answered}/{SURVEY_TOTAL}</span></summary>
    <p className="survey-summary">전체 {SURVEY_TOTAL}문항 · 응답 {counts.answered}개 · 미응답 {SURVEY_TOTAL - counts.answered - counts.notApplicable}개 · 해당 없음 {counts.notApplicable}개</p>
    {catalog.version === 'survey-20260929-v3' && <p className="fine">평균 묶음은 전체 응답이 필요합니다. 누락 문항 보완 전 해당 묶음만 미산출하며 다른 영역은 유지합니다. Q24·Q25는 각각 단일 응답이고 Q26~28은 6−원응답으로 역채점합니다.</p>}
    <p className="fine">설문은 CSV·Excel 파일 가져오기로만 등록합니다. 미응답은 빈칸으로 보존합니다. {catalog.version === 'survey-20260929-v3' ? '10~14번의 0은 정상 응답이며 NA는 허용하지 않습니다. 빈칸 사유 미상은 추정하지 않습니다.' : '7~9번의 「해당 없음」은 결측이며 0점이 아닙니다.'} 총점은 만들지 않습니다.</p>
    {catalog.response_scale && <p className="fine">응답 척도: {(catalog.response_scale ?? []).map((label, index) => `${index + 1} ${label}`).join(' · ')}</p>}
    {domains.map(domain => <section key={domain} className="questions"><h3 id={`survey-section-${domain}`}>{domain}. {surveyDomains[domain]}</h3>
      <div className="table-wrap survey-responses"><table aria-labelledby={`survey-section-${domain}`}>
        <thead><tr><th scope="col">번호</th><th scope="col">설문 문항</th><th scope="col">응답</th><th scope="col">미응답 사유</th></tr></thead>
        <tbody>{catalog.items.filter(q => (q.print_section ?? q.domain ?? '') === domain).map(q => {
          const answer = state(q.item_id);
          return <tr key={q.item_id}>
            <td data-label="번호" className="mono">{q.number}</td>
            <td data-label="설문 문항">{q.text}{q.labels && <small>척도: {q.labels.map(label => `${label.value} ${label.text}`).join(' · ')}</small>}</td>
            <td data-label="응답"><strong className={answer === '미응답' ? 'tag' : answer === '해당 없음' ? 'tag neutral' : 'tag green'}>{answer}</strong></td>
            <td data-label="미응답 사유">{answer === '미응답' ? session.survey_blank_reasons?.[q.item_id] || '사유 미입력' : '—'}</td>
          </tr>;
        })}</tbody>
      </table></div>
    </section>)}
  </details>;
}
