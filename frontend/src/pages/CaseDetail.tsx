import { useState } from 'react';
import { api } from '../api';
import { mayLeave } from '../Editing';
import { CaseEditor } from '../MetadataEditors';
import { segmentState, sessionOf, SURVEY_TOTAL, surveyHandled } from '../types';
import type { Case, Run } from '../types';

// 접수 상세: 참가자·반려견 정보와 세션 요약, 정정·삭제 요청. 설문은 「설문」, 영상·구간은 「촬영」 메뉴가 맡는다.
export function CaseDetail({ item, writable, run, refresh, back }: {
  item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; back: () => void;
}) {
  const [viewSession, setViewSession] = useState(item.selected_session_id);
  const session = item.manifest.sessions.find(s => s.session_id === (writable ? item.selected_session_id : viewSession)) ?? sessionOf(item);
  const profile = [item.dog.breed, item.dog.sex !== '미기재' && item.dog.sex, item.dog.age_years !== null && `${item.dog.age_years}세`,
    item.dog.size !== '미기재' && item.dog.size, item.dog.years_together && `함께 ${item.dog.years_together}`,
    item.dog.adoption_route !== '미기재' && item.dog.adoption_route].filter(Boolean).join(' · ');
  return <>
    <button className="plain back" onClick={back}>← 접수 목록</button>
    <section className="page-heading"><div><p className="eyebrow">{item.event_id} / {item.participant_id}{item.sequence_no !== null && ` · 순번 ${item.sequence_no}`}</p><h1>{item.dog_name}</h1>
      <p className="muted">{item.guardian_name ? `${item.guardian_name} 님` : '보호자명 없음'}{profile && ` · ${profile}`}</p>
      <p className="muted">{item.reservation_at ? `예약 ${item.reservation_at.replace('T', ' ')}` : '예약 정보 없음'} · <span className={item.consent_confirmed ? 'tag green' : 'tag'}>{item.consent_confirmed ? '동의 확인' : '동의 미확인'}</span></p></div>
      <span className="tag">입력 버전 {item.input_revision}</span></section>
    <div className="detail-grid" id="sessions">
      <section className="panel"><h2>촬영 세션</h2><label>선택 세션<select aria-label="선택 세션" value={session.session_id} onChange={e => { if (!mayLeave()) return; if (!writable) { setViewSession(e.target.value); return; } void run(async () => {
        await api(`/cases/${item.case_id}/sessions`, 'POST', { expected_revision: item.input_revision, session_id: e.target.value }); await refresh();
      }); }}>{item.manifest.sessions.map((s, i) => <option key={s.session_id} value={s.session_id}>{i + 1}차 촬영 · 영상 {s.videos.length}개</option>)}</select></label>
        <p className="fine">영상 {session.videos.length}개 · 구간 {({ none: '없음', draft: '초안', confirmed: '확정' })[segmentState(session)]} · 설문 {surveyHandled(session)}/{SURVEY_TOTAL} · {session.note || '촬영 메모 없음'}</p>
        {item.manifest.migration_note && <p className="fine">{item.manifest.migration_note}</p>}
        <p className="fine">영상 등록·8구간 시각·촬영 메모·재촬영은 「촬영」 메뉴에서, 설문은 「설문」 메뉴에서 다룹니다.</p>
      </section>
      {writable && <section className="panel"><h2>자료 관리</h2>
        <CaseEditor item={item} run={run} refresh={refresh} />
        <details><summary>삭제 요청 접수</summary><form onSubmit={e => { e.preventDefault(); void run(async () => {
          await api(`/cases/${item.case_id}/deletion`, 'POST', { expected_revision: item.input_revision }); await refresh();
        }); }}><label className="check"><input type="checkbox" required />삭제 요청됨</label>
          <p className="fine">저장하면 목록과 파일 접근이 차단됩니다. 실제 파일 폐기는 보관 정책에 따라 별도 처리합니다.</p>
          <button>삭제 요청 저장</button></form></details>
      </section>}
    </div>
  </>;
}
