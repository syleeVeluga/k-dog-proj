import { SURVEY_TOTAL, surveyDomains, surveyHandled } from './types';
import type { Catalog, Session } from './types';

// Surveys are registered from CSV/Excel in 자료 가져오기; this panel only shows what was registered.
export function SurveyView({ session, catalog }: { session: Session; catalog: Catalog }) {
  const domains = [...new Set(catalog.items.map(q => q.domain))];
  const state = (id: string) => session.survey_not_applicable.includes(id) ? '해당 없음' : session.survey[id] === null || session.survey[id] === undefined ? '미응답' : String(session.survey[id]);
  return <details className="panel" id="survey"><summary>설문 원응답 <span className="tag">{surveyHandled(session)}/{SURVEY_TOTAL}</span></summary>
    <p className="fine">설문은 「자료 가져오기」에서 CSV·Excel로 등록합니다. 미응답은 빈칸으로 보존하고, 7~9번의 「해당 없음」은 결측이며 0점이 아닙니다. 총점은 만들지 않습니다.</p>
    <p className="fine">응답 척도: {catalog.response_scale.map((label, index) => `${index + 1} ${label}`).join(' · ')}</p>
    {domains.map(domain => <section key={domain} className="questions"><h3>{domain}. {surveyDomains[domain]}</h3>
      <div className="survey-values">{catalog.items.filter(q => q.domain === domain).map(q => <p key={q.item_id}><b className="mono">{q.number}</b> {q.text} · <strong>{state(q.item_id)}</strong></p>)}</div>
    </section>)}
  </details>;
}
