import { api } from './api';
import { useEditBase } from './Editing';
import type { Case, Session } from './types';

export const stages: Record<string, string> = { entry: '입장', separation: '분리·재회', training: '훈련', play: '놀이', exit: '퇴장' };
export const completion: Record<string, string> = { unknown: '미확인', performed: '실시', skipped: '미실시', retake: '재촬영 필요' };
type Props = { item: Case; run: (work: () => Promise<void>) => Promise<void>; refresh: (message?: string) => Promise<void> };

export function CaseEditor({ item, run, refresh }: Props) {
  const edit = useEditBase(item); const view = edit.view;
  return <details><summary>참가자 기본 정보 정정</summary>
    <p className="warning">새 입력 버전으로 저장합니다. 이전 분석·내보낸 파일은 보존되며, 정정한 정보로 분석하려면 새 실행이 필요합니다.</p>
    {edit.dirty && <p role="status">기본 정보 · 저장 전</p>}
    <form key={`${view.input_revision}-${edit.key}`} onFocusCapture={edit.capture} onChange={edit.change} onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(async () => {
      await api(`/cases/${item.case_id}`, 'PUT', { expected_revision: view.input_revision, participant_id: f.get('participant_id'), dog_name: f.get('dog_name'), reservation_at: f.get('reservation_at') }); edit.reset(); await refresh('기본 정보를 정정했습니다.');
    }); }}><label>정정 참가자 ID<input name="participant_id" pattern="[A-Za-z0-9_\-]+" required defaultValue={view.participant_id} /></label>
      <label>정정 반려견 이름<input name="dog_name" required maxLength={200} defaultValue={view.dog_name} /></label><label>정정 예약 시각<input name="reservation_at" type="datetime-local" defaultValue={view.reservation_at} /></label>
      <button>기본 정보 정정 저장</button><button type="button" onClick={edit.discard}>최신 기본 정보 불러오기</button></form>
  </details>;
}

export function SessionEditor({ item, session, run, refresh }: Props & { session: Session }) {
  const edit = useEditBase({ item, session }); const view = edit.view;
  return <details><summary>현재 촬영 정보 수정</summary>
    {edit.dirty && <p role="status">촬영 정보 · 저장 전</p>}
    <form key={`${view.item.input_revision}-${edit.key}`} onFocusCapture={edit.capture} onChange={edit.change} onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(async () => {
      await api(`/cases/${item.case_id}/sessions/${session.session_id}`, 'PUT', { expected_revision: view.item.input_revision,
        capture_mode: f.get('capture_mode'), route_note: f.get('route_note'), checklist: Object.fromEntries(Object.keys(stages).map(id => [id, f.get(id)])) });
      edit.reset(); await refresh('촬영 정보와 체크리스트를 저장했습니다.');
    }); }}><label>현재 촬영 방식<select name="capture_mode" defaultValue={view.session.capture_mode}><option value="unknown">미확인</option><option value="simultaneous">동시 촬영</option><option value="sequential">순차 촬영</option></select></label>
      <div className="form-grid">{Object.entries(stages).map(([id, label]) => <label key={id}>{label} 실시 상태<select name={id} defaultValue={view.session.checklist?.[id] ?? 'unknown'}>{Object.entries(completion).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>)}</div>
      <label>현재 동선 메모<textarea name="route_note" defaultValue={view.session.route_note} maxLength={2000} /></label>
      <p className="fine">체크리스트는 촬영 기록입니다. 점수나 관찰 근거를 대체하지 않습니다.</p>
      <button>촬영 정보 저장</button><button type="button" onClick={edit.discard}>최신 촬영 정보 불러오기</button></form>
  </details>;
}
