import { api } from './api';
import { useEditBase } from './Editing';
import type { Case, Catalog, Session } from './types';

export function SurveyEditor({ item, session, catalog, writable, run, refresh }: { item: Case; session: Session; catalog: Catalog; writable: boolean;
  run: (work: () => Promise<void>) => Promise<void>; refresh: (message?: string) => Promise<void> }) {
  const edit = useEditBase({ item, session });
  const view = edit.view;
  return <details className="panel" id="survey"><summary>설문 원응답 <span className="tag">{Object.values(session.survey).filter(v => v !== null).length}/30</span></summary>
    <p>{catalog.response_instructions}</p><p className="fine">미응답은 빈칸으로 보존합니다. A·C-1·D와 B 참고값은 분석 시 계산하며 q23/C-2 집계는 규칙 확정 전 보류합니다.</p>
    {edit.dirty && <p role="status">설문 입력 · 저장 전</p>}
    {view.item.input_revision !== item.input_revision && <p className="warning">자료가 변경되었습니다. 입력은 보존되지만 저장 전에 최신 자료와 대조해야 합니다.</p>}
    {writable && <button onClick={edit.discard}>최신 설문 불러오기 · 미저장 입력 초기화</button>}
    <form key={`${view.item.input_revision}-${view.session.session_id}-${edit.key}`} onFocusCapture={edit.capture} onChange={edit.change} onSubmit={e => {
      e.preventDefault(); const f = new FormData(e.currentTarget);
      const answers = Object.fromEntries(catalog.items.map(q => [q.item_id, f.get(q.item_id) === '' ? null : Number(f.get(q.item_id))]));
      void run(async () => { await api(`/cases/${item.case_id}/survey`, 'PUT', { expected_revision: view.item.input_revision, session_id: session.session_id, survey_version: catalog.version, answers }); edit.reset(); await refresh('설문을 저장했습니다.'); });
    }}><fieldset disabled={!writable}><div className="questions">{catalog.items.map(q => <label key={q.item_id}><span><b className="mono">{q.item_id}</b> {q.text}</span>
      <select name={q.item_id} aria-label={`${q.item_id} 응답`} defaultValue={view.session.survey[q.item_id] ?? ''}><option value="">미응답</option>{[1, 2, 3, 4, 5].map(n => <option value={n} key={n}>{n}</option>)}</select></label>)}</div>
      {writable && <button className="primary">설문 저장</button>}</fieldset></form>
  </details>;
}
