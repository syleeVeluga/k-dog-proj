import { useEffect, useState } from 'react';
import { api } from '../api';
import { Importer } from '../Importer';
import { SurveyView } from '../SurveyView';
import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { SURVEY_TOTAL, sessionOf, surveyDomains, surveyHandled } from '../types';
import type { Case, Catalog, Run, SurveyResult } from '../types';

type Props = { cases: Case[]; selected: Case | null; select: (item: Case | null) => void; filters: CaseFilterProps; catalog: Catalog | null; writable: boolean; run: Run; reload: (id?: string) => Promise<void>; notify: (message: string) => void };

// 설문 메뉴: 사람이 CSV·Excel로 가져오고, 여기서는 등록 현황과 영역 응답 수·분리 유형만 본다. 숫자 점수·총점은 내지 않는다(01 §6).
export function Survey({ cases, selected, select, filters, catalog, writable, run, reload, notify }: Props) {
  const [result, setResult] = useState<SurveyResult | null>(null);
  const [resultError, setResultError] = useState('');
  const session = selected ? sessionOf(selected) : null;
  useEffect(() => {
    setResult(null); setResultError('');
    if (!selected) return;
    let active = true;
    api<SurveyResult>(`/cases/${selected.case_id}/survey/result?session_id=${selected.selected_session_id}`).then(value => { if (active) setResult(value); })
      .catch(e => { if (active) setResultError(e instanceof Error ? e.message : '결과를 조회하지 못했습니다.'); });
    return () => { active = false; };
  }, [selected?.case_id, selected?.input_revision, selected?.selected_session_id]);
  const sorted = cases.filter(c => matchesCase(c, filters.search, filters.eventFilter)).sort((a, b) => (a.sequence_no ?? 1e9) - (b.sequence_no ?? 1e9) || a.participant_id.localeCompare(b.participant_id));
  const registered = cases.filter(c => surveyHandled(sessionOf(c)) === SURVEY_TOTAL).length;
  return <>
    <section className="page-heading"><div><p className="eyebrow">SURVEY</p><h1>설문</h1><p className="muted">보호자 설문 28문항은 CSV·Excel 파일로 등록합니다. 여기서는 등록 현황과 영역별 응답 수, 분리 유형 이름만 확인합니다.</p></div>
      <div className="count"><strong>{registered.toString().padStart(2, '0')}</strong><span>설문 완료 / {cases.length}명</span></div></section>
    {!selected && writable && <details className="panel" open={registered < cases.length}><summary>설문 파일 가져오기 (CSV·Excel)</summary>
      <p className="fine">열은 <span className="mono">event_id, participant_id, survey_version, s01 … s28</span>이며 7~9번은 <span className="mono">NA</span>로 「해당 없음」을 표시합니다. 양식은 아래에서 내려받습니다.</p>
      <Importer fixedKind="survey" run={run} catalog={catalog} catalogVersion={catalog?.version ?? ''} done={async message => { notify(message); await reload(); }} />
    </details>}
    {!selected && <><CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>순번</th><th>참가자</th><th>반려견 / 보호자</th><th>설문</th><th>미응답</th><th>해당 없음</th><th>현황</th></tr></thead>
      <tbody>{sorted.map(c => { const s = sessionOf(c); const count = surveyHandled(s); const missing = SURVEY_TOTAL - count;
        return <tr key={c.case_id}><td data-label="순번"><strong className="mono">{c.sequence_no ?? '—'}</strong></td>
          <td data-label="참가자"><strong className="mono">{c.participant_id}</strong><small>{c.event_id}</small></td>
          <td data-label="반려견 / 보호자">{c.dog_name}<small>{c.guardian_name ? `${c.guardian_name} 님` : '보호자명 없음'}</small></td>
          <td data-label="설문"><span className={count === SURVEY_TOTAL ? 'tag green' : 'tag'}>{count}/{SURVEY_TOTAL}</span></td>
          <td data-label="미응답">{missing}</td><td data-label="해당 없음">{s.survey_not_applicable.length}</td>
          <td data-label="현황"><button aria-label={`${c.participant_id} 설문 현황 열기`} onClick={() => select(c)}>열기 ↗</button></td></tr>;
      })}</tbody></table>{!sorted.length && <div className="empty"><h2>표시할 참가자가 없습니다.</h2><p>검색·행사 필터 또는 접수 등록을 확인하세요.</p></div>}</div></>}
    {selected && session && catalog && <section className="panel" aria-label="설문 현황">
      <div className="section-title"><h2>{selected.dog_name} · {selected.participant_id}</h2><button onClick={() => select(null)}>닫기</button></div>
      {result ? <>
        <p className="fine">등록 {surveyHandled(session)}/28 · 응답 {Object.values(session.survey).filter(v => v !== null).length} · 해당 없음 {session.survey_not_applicable.length} · 미응답 {28 - surveyHandled(session)} · 총점은 만들지 않습니다.</p>
        {session.survey_not_applicable.length > 0 && <p className="fine">A 영역은 해당 없음 {session.survey_not_applicable.length}개를 제외하고 계산합니다. 해당 없음은 등록된 응답 상태이며 0점이나 미응답이 아닙니다.</p>}
        <div className="score-grid">{result.domains.map(d => <div className="score-card" key={d.domain}><strong>{d.domain}. {surveyDomains[d.domain]}</strong><p>응답 {d.answered_count}/{d.target_count}{d.answered_count < d.target_count && ` · 미응답·해당 없음 ${d.target_count - d.answered_count}`}</p></div>)}
          <div className="score-card"><strong>D. {surveyDomains.D}</strong><p>분리 유형: {result.separation.label ?? `없음 (${result.separation.reason ?? '미응답'})`}</p></div></div>
      </> : resultError ? <p className="error" role="alert">{resultError}</p> : <p role="status">결과 조회 중…</p>}
      <SurveyView key={`${selected.case_id}-${selected.input_revision}`} session={session} catalog={catalog} />
    </section>}
  </>;
}
