import { api } from './api';
import { useEditBase } from './Editing';
import { ParticipantFields, participantValue } from './ParticipantFields';
import type { Case, Run, Session } from './types';

type Props = { item: Case; run: Run; refresh: (message?: string) => Promise<void> };

export function CaseEditor({ item, run, refresh }: Props) {
  const edit = useEditBase(item); const view = edit.view;
  return <details><summary>참가자 기본 정보 정정</summary>
    <p className="warning">새 입력 버전으로 저장합니다. 이전 자료는 보존됩니다.</p>
    {edit.dirty && <p role="status">기본 정보 · 저장 전</p>}
    <form key={`${view.input_revision}-${edit.key}`} onFocusCapture={edit.capture} onChange={edit.change} onSubmit={e => { e.preventDefault(); const form = new FormData(e.currentTarget); void run(async () => {
      await api(`/cases/${item.case_id}`, 'PUT', { expected_revision: view.input_revision, ...participantValue(form) }); edit.reset(); await refresh('기본 정보를 정정했습니다.');
    }); }}><div className="form-grid"><ParticipantFields value={view} /></div>
      <button>기본 정보 정정 저장</button><button type="button" onClick={edit.discard}>최신 기본 정보 불러오기</button></form>
  </details>;
}

export function SessionEditor({ item, session, run, refresh }: Props & { session: Session }) {
  const edit = useEditBase({ item, session }); const view = edit.view;
  return <details><summary>현재 촬영 메모 수정</summary>
    {edit.dirty && <p role="status">촬영 메모 · 저장 전</p>}
    <form key={`${view.item.input_revision}-${edit.key}`} onFocusCapture={edit.capture} onChange={edit.change} onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(async () => {
      await api(`/cases/${item.case_id}/sessions/${session.session_id}`, 'PUT', { expected_revision: view.item.input_revision, note: f.get('note') });
      edit.reset(); await refresh('촬영 메모를 저장했습니다.');
    }); }}><label>촬영 메모<textarea name="note" defaultValue={view.session.note} maxLength={2000} /></label>
      <p className="fine">마이크·구간 진행 등 현장 특이사항을 적습니다. 점수나 관찰 근거를 대체하지 않습니다. 8구간 시각 기록은 촬영 메뉴에서 합니다.</p>
      <button>촬영 메모 저장</button><button type="button" onClick={edit.discard}>최신 촬영 메모 불러오기</button></form>
  </details>;
}
