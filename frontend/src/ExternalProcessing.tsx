import { useEffect, useState } from 'react';
import { api, ApiError } from './api';
import { useEditBase } from './Editing';
import type { Case, ExternalProcessing, Run, Video } from './types';

export const unknownProcessing: ExternalProcessing = { projection: 'unknown', timeline: 'unknown' };
export const cameraName = (camera: string | null | undefined) => camera === 'EXT360' ? '360 통합 영상' : camera ?? '카메라 미등록';
export function processingSummary(value: ExternalProcessing) {
  return `${({ flat: '일반 화면', equirectangular: '360 펼침 영상', unknown: '영상 배치 미확인' })[value.projection]} · ${({ preserved: '촬영 시간 유지', edited: '구간 편집·속도 변경 있음', unknown: '촬영 시각 대응 미확인' })[value.timeline]}`;
}
export function ProcessingNotice({ value }: { value: ExternalProcessing }) {
  return <div className="fine"><p>사용자 제공 외부 처리 정보 · 원본 미등록 · {processingSummary(value)}</p>
    {value.projection !== 'flat' && <p>{value.projection === 'equirectangular' ? '일반 화면으로 재구도한 MP4가 필요합니다.' : '영상 배치를 확인해야 영상 클립을 제작할 수 있습니다.'}</p>}
    {value.timeline !== 'preserved' && <p>촬영 시각 대응을 확인해야 합니다. 편집·미확인 영상은 기준 영상이나 사건·관찰 시각의 근거로 확정할 수 없습니다. 시간 유지 영상을 선택해 촬영 기록을 다시 확정하세요.</p>}
    {value.projection === 'flat' && value.timeline === 'preserved' && <p>촬영 기록의 실제 시각을 확정한 뒤 전처리를 실행하세요. 업로드 완료는 분석 완료를 뜻하지 않습니다.</p>}
  </div>;
}
export function ExternalProcessingFields({ value, change }: { value: ExternalProcessing; change: (value: ExternalProcessing) => void }) {
  return <><div className="form-grid">
    <label>영상 배치<select aria-label="영상 배치" value={value.projection} onChange={event => change({ ...value, projection: event.target.value as ExternalProcessing['projection'] })}>
      <option value="unknown">잘 모름</option><option value="flat">일반 화면으로 내보냄</option><option value="equirectangular">360 펼침 영상</option></select></label>
    <label>촬영 시간<select aria-label="촬영 시간" value={value.timeline} onChange={event => change({ ...value, timeline: event.target.value as ExternalProcessing['timeline'] })}>
      <option value="unknown">잘 모름</option><option value="preserved">촬영 시간의 순서·속도 유지</option><option value="edited">구간 편집·속도 변경 있음</option></select></label>
  </div><details><summary>내보내기 도구·메모 (선택)</summary><div className="form-grid">
    <label>내보내기 도구<input value={value.tool_name ?? ''} maxLength={2000} onChange={event => change({ ...value, tool_name: event.target.value || null })} /></label>
    <label>내보내기 도구 버전<input value={value.tool_version ?? ''} maxLength={2000} onChange={event => change({ ...value, tool_version: event.target.value || null })} /></label>
    <label>처리 메모<textarea value={value.note ?? ''} maxLength={2000} onChange={event => change({ ...value, note: event.target.value || null })} /></label>
  </div></details></>;
}

export function ExternalProcessingEditor({ item, video, sessionId, declared, run, changed }: {
  item: Case; video: Video; sessionId: string; declared: ExternalProcessing; run: Run; changed: (message?: string) => Promise<void>;
}) {
  const edit = useEditBase(item);
  const [value, setValue] = useState(video.external_processing ?? unknownProcessing);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!edit.dirty) setValue(video.external_processing ?? unknownProcessing); }, [item.input_revision, video.video_id]);
  return <details><summary>처리 정보 확인·정정</summary>
    <p className="fine">업로드 당시: {processingSummary(declared)}</p><p className="fine">현재 입력 {item.input_revision}: {processingSummary(video.external_processing ?? unknownProcessing)}</p>
    <form onSubmit={event => { event.preventDefault(); void run(async () => {
      setBusy(true); setError('');
      try {
        await api(`/cases/${item.case_id}/videos/${video.video_id}/external-processing`, 'PATCH', {
          session_id: sessionId, expected_revision: edit.view.input_revision, external_processing: value,
        });
        edit.reset(); await changed('처리 정보를 새 입력 판본으로 저장했습니다. 촬영 기록을 확인하고 새 전처리를 명시 실행하세요.');
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : '처리 정보를 저장하지 못했습니다.');
        if (reason instanceof ApiError && reason.status === 409) await changed();
      } finally { setBusy(false); }
    }); }}>
      <fieldset disabled={busy || item.selected_session_id !== sessionId}><ExternalProcessingFields value={value} change={next => { edit.change(); setValue(next); }} /></fieldset>
      {edit.dirty && <p role="status">처리 정보 · 저장 전</p>}
      {edit.dirty && edit.view.input_revision !== item.input_revision && <p className="warning">다른 변경이 저장되었습니다. 최신 정보를 확인한 뒤 다시 입력하세요.</p>}
      {item.selected_session_id !== sessionId && <p className="warning">선택 촬영 회차가 변경되었습니다. 입력은 보존 중입니다. 이 영상의 회차로 돌아와 최신 정보를 확인하세요.</p>}
      <button disabled={busy || !edit.dirty || edit.view.input_revision !== item.input_revision || item.selected_session_id !== sessionId}>처리 정보 저장</button>
      {edit.dirty && <button type="button" disabled={busy} onClick={() => { if (edit.discard()) { setValue(video.external_processing ?? unknownProcessing); setError(''); } }}>입력 버리고 최신 값 보기</button>}
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    <p className="fine">파일은 다시 전송하지 않습니다. 이전 판본과 결과는 보존됩니다. 과거 전처리가 새 처리 정보로 자동 갱신되지는 않습니다.</p>
  </details>;
}
