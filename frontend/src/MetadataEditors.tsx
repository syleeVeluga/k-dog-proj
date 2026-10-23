import { ApiError, api } from './api';
import { useEditBase } from './Editing';
import { focusFirstError, focusSoon, useFieldErrors, validateForm } from './FieldErrors';
import { ParticipantFields, participantValue } from './ParticipantFields';
import type { Case, Run } from './types';

type Props = { item: Case; run: Run; refresh: (message?: string) => Promise<void> };

export function CaseEditor({ item, run, refresh }: Props) {
  const edit = useEditBase(item); const view = edit.view;
  const fields = useFieldErrors();
  return <details><summary>참가자 기본 정보 정정</summary>
    <p className="warning">새 입력 버전으로 저장합니다. 이전 자료는 보존됩니다.</p>
    {edit.dirty && <p role="status">기본 정보 · 저장 전</p>}
    <form noValidate {...fields.bind} key={`${view.input_revision}-${edit.key}`} onFocusCapture={edit.capture} onChange={edit.change} onSubmit={e => {
      e.preventDefault(); const target = e.currentTarget;
      const problems = validateForm(target, ['participant_id', 'sequence_no', 'dog_name', 'age_years']);
      if (Object.keys(problems).length) { fields.set(problems); focusFirstError(target, problems); return; }
      const form = new FormData(target);
      void run(async () => {
        try { await api(`/cases/${item.case_id}`, 'PUT', { expected_revision: view.input_revision, ...participantValue(form) }); }
        catch (error) {
          // 중복 ID·순번은 해당 칸 아래에 알린다. 다른 오류는 전역 알림으로 넘긴다.
          if (error instanceof ApiError && (error.field === 'participant_id' || error.field === 'sequence_no')) {
            const problem = { [error.field]: error.message }; fields.set(problem); focusSoon(target, problem); return;
          }
          throw error;
        }
        fields.clear(); edit.reset(); await refresh('기본 정보를 정정했습니다.');
      });
    }}>{fields.summary && <p className="error" role="alert">{fields.summary}</p>}
      <div className="form-grid"><ParticipantFields value={view} errors={fields.errors} prefix="edit" /></div>
      <button>기본 정보 정정 저장</button><button type="button" onClick={edit.discard}>최신 기본 정보 불러오기</button></form>
  </details>;
}
