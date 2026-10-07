import { SURVEY_TOTAL, surveyDomains, surveyHandled } from './types';
import type { Catalog, Session } from './types';

// Surveys are registered from CSV/Excel in 자료 가져오기; this panel only shows what was registered.
export function SurveyView({ session, catalog }: { session: Session; catalog: Catalog }) {
  if (session.survey_version !== catalog.version) return <p className="fine">설문 판본: {session.survey_version} · 이 판본의 원응답 화면은 설문 연결 단계에서 제공됩니다.</p>;
  const domains = [...new Set(catalog.items.map(q => q.print_section ?? q.domain ?? ''))];
  const state = (id: string) => session.survey_not_applicable.includes(id) ? '해당 없음' : session.survey[id] === null || session.survey[id] === undefined ? '미응답' : String(session.survey[id]);
  return <details className="panel" id="survey"><summary>설문 원응답 <span className="tag">{surveyHandled(session)}/{SURVEY_TOTAL}</span></summary>
    {catalog.version === 'survey-20260929-v3' && <p className="fine">평균 묶음은 전체 응답이 필요합니다. 누락 문항 보완 전 해당 묶음만 미산출하며 다른 영역은 유지합니다. Q24·Q25는 각각 단일 응답이고 Q26~28은 6−원응답으로 역채점합니다.</p>}
    <p className="fine">설문은 CSV·Excel 파일 가져오기로만 등록합니다. 미응답은 빈칸으로 보존합니다. {catalog.version === 'survey-20260929-v3' ? '10~14번의 0은 정상 응답이며 NA는 허용하지 않습니다. 빈칸 사유 미상은 추정하지 않습니다.' : '7~9번의 「해당 없음」은 결측이며 0점이 아닙니다.'} 총점은 만들지 않습니다.</p>
    {catalog.response_scale && <p className="fine">응답 척도: {(catalog.response_scale ?? []).map((label, index) => `${index + 1} ${label}`).join(' · ')}</p>}
    {domains.map(domain => <section key={domain} className="questions"><h3>{domain}. {surveyDomains[domain]}</h3>
      <div className="survey-values">{catalog.items.filter(q => (q.print_section ?? q.domain ?? '') === domain).map(q => <p key={q.item_id}><b className="mono">{q.number}</b> {q.text} · <strong>{state(q.item_id)}</strong>{q.labels && <small>척도: {q.labels.map(label => `${label.value} ${label.text}`).join(' · ')}</small>}{session.survey[q.item_id] === null && <small>빈칸 사유: {session.survey_blank_reasons?.[q.item_id] ?? '사유 미상'}</small>}</p>)}</div>
    </section>)}
  </details>;
}
