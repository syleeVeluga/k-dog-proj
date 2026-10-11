import type { CaseFilterProps } from '../CaseFilters';
import { CaseProgressList } from '../CaseProgressList';
import { mayLeave } from '../Editing';
import { Prerequisites } from '../Prerequisites';
import { ScoreSheetsV4 } from '../ScoreSheetsV4';
import type { Route } from '../navigation';
import type { Case, Run, User } from '../types';

export function Scoring({ cases, selected, select, filters, user, run, refresh, goTo }: { cases: Case[]; selected: Case | null; select: (item: Case | null) => void; filters: CaseFilterProps; user: User; run: Run; refresh: (message?: string) => Promise<void>; goTo: (route: Route) => void }) {
  return <section><h1>독립 채점</h1><p>배정된 평가자가 같은 촬영 입력과 실제 관찰창을 기준으로 기록합니다. 다른 평가 결과는 독립 제출 뒤 운영자가 명시적으로 공개한 완료본만 열 수 있습니다.</p>
    {selected ? <><Prerequisites item={selected} kind="scoring" user={user} goTo={goTo} />
      <ScoreSheetsV4 key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} user={user} run={run} refresh={refresh} close={() => { if (mayLeave()) select(null); }} /></>
      : <CaseProgressList cases={cases} user={user} filters={filters} open={select} openLabel={item => `${item.participant_id} 독립 채점 열기`} />}
  </section>;
}
