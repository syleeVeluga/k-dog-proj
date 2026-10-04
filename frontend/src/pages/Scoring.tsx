import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import { mayLeave } from '../Editing';
import type { Case, Run, User } from '../types';
import { ScoreSheetsV4 } from '../ScoreSheetsV4';
import { ResearchExportsV4 } from '../ResearchExportsV4';

export function Scoring({ cases, selected, select, filters, user, run, refresh }: { cases: Case[]; selected: Case | null; select: (item: Case | null) => void; filters: CaseFilterProps; user: User; run: Run; refresh: (message?: string) => Promise<void> }) {
  return <section><h1>독립 채점</h1><p>배정된 평가자가 같은 촬영 입력과 실제 관찰창을 기준으로 기록합니다. 다른 평가 결과는 독립 제출 뒤 운영자가 명시적으로 공개한 완료본만 열 수 있습니다.</p>
    {selected ? <><ScoreSheetsV4 key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} user={user} run={run} refresh={refresh} close={() => { if (mayLeave()) select(null); }} />{(user.role === 'operator' || user.role === 'admin') && <details><summary>연구 내보내기</summary><ResearchExportsV4 key={`export:${selected.case_id}:${selected.selected_session_id}`} item={selected} user={user} /></details>}</> : <>
      <CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>행사 / 참가자</th><th>반려견</th><th>작업</th></tr></thead><tbody>
        {cases.filter(c => matchesCase(c, filters.search, filters.eventFilter)).map(c => <tr key={c.case_id}><td>{c.event_id} / {c.participant_id}</td><td>{c.dog_name}</td><td><button onClick={() => select(c)} aria-label={`${c.participant_id} 독립 채점 열기`}>열기</button></td></tr>)}
      </tbody></table></div></>}
  </section>;
}
