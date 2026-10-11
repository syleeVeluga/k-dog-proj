import type { CaseFilterProps } from '../CaseFilters';
import { CaseProgressList } from '../CaseProgressList';
import { Prerequisites } from '../Prerequisites';
import { PreprocessingPanelV4 } from '../PreprocessingPanelV4';
import type { Route } from '../navigation';
import type { Case, Run, User } from '../types';

export function Preprocessing({ cases, selected, select, filters, user, writable, run, refresh, goTo }: { cases: Case[]; selected: Case | null; select: (item: Case) => void; filters: CaseFilterProps; user: User; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; goTo: (route: Route) => void }) {
  return <section><h1>전처리</h1><p>기준 영상을 구간별로 잘라 분석용 파일을 만듭니다. 원본과 오디오는 보존됩니다. 실행·재시도는 운영자가 버튼을 눌러 시작합니다.</p>
    {selected ? <><Prerequisites item={selected} kind="preprocess" user={user} goTo={goTo} />
      <PreprocessingPanelV4 key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} writable={writable} run={run} refresh={refresh} /></>
      : <CaseProgressList cases={cases} user={user} filters={filters} open={select} openLabel={item => `${item.participant_id} 전처리 열기`} />}
  </section>;
}
