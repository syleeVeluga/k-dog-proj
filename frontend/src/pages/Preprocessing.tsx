import { CaseFilters, matchesCase } from '../CaseFilters';
import type { CaseFilterProps } from '../CaseFilters';
import type { Case, Run } from '../types';
import { PreprocessingPanelV4 } from '../PreprocessingPanelV4';

export function Preprocessing({ cases, selected, select, filters, writable, run, refresh }: { cases: Case[]; selected: Case | null; select: (item: Case) => void; filters: CaseFilterProps; writable: boolean; run: Run; refresh: (message?: string) => Promise<void> }) {
  return <section><h1>전처리</h1><p>기준 영상을 구간별로 잘라 분석용 파일을 만듭니다. 원본과 오디오는 보존됩니다. 실행·재시도는 운영자가 버튼을 눌러 시작합니다.</p>
    {selected ? <PreprocessingPanelV4 key={`${selected.case_id}:${selected.selected_session_id}`} item={selected} writable={writable} run={run} refresh={refresh} /> : <>
      <CaseFilters cases={cases} {...filters} /><div className="table-wrap"><table><thead><tr><th>행사 / 참가자</th><th>반려견</th><th>작업</th></tr></thead><tbody>
        {cases.filter(c => matchesCase(c, filters.search, filters.eventFilter)).map(c => <tr key={c.case_id}><td>{c.event_id} / {c.participant_id}</td><td>{c.dog_name}</td><td><button onClick={() => select(c)} aria-label={`${c.participant_id} 전처리 열기`}>열기</button></td></tr>)}
      </tbody></table></div></>}
  </section>;
}
