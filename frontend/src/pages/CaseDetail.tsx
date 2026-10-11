import { CaseEditor } from '../MetadataEditors';
import { protocolName, segmentState, sessionOf, SURVEY_TOTAL, surveyHandled } from '../types';
import type { Case, Run } from '../types';

// 접수 상세: 참가자·반려견 정보와 세션 요약, 정정·삭제 요청. 설문은 「설문」, 영상·구간은 「촬영」 메뉴가 맡는다.
export function CaseDetail({ item, writable, run, refresh, back }: {
  item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; back: () => void;
}) {
  const session = sessionOf(item);
  const profile = [item.dog.breed, item.dog.sex !== '미기재' && item.dog.sex, item.dog.age_years !== null && `${item.dog.age_years}세`,
    item.dog.size !== '미기재' && item.dog.size, item.dog.years_together && `함께 ${item.dog.years_together}`,
    item.dog.adoption_route !== '미기재' && item.dog.adoption_route].filter(Boolean).join(' · ');
  return <>
    <button className="plain back" onClick={back}>← 접수 목록</button>
    <section className="page-heading"><div><p className="eyebrow">{item.event_id} / {item.participant_id}{item.sequence_no !== null && ` · 순번 ${item.sequence_no}`}</p><h1>{item.dog_name}</h1>
      <p className="muted">{item.guardian_name ? `${item.guardian_name} 님` : '보호자명 없음'}{profile && ` · ${profile}`}</p>
      <p className="muted">{item.reservation_at ? `예약 ${item.reservation_at.replace('T', ' ')}` : '예약 정보 없음'}</p></div>
      <span className="tag">입력 버전 {item.input_revision}</span></section>
    <div className="detail-grid" id="sessions">
      <section className="panel"><h2>촬영 세션</h2>
        {item.scoring_status === 'reanalysis_required' && <p role="status"><strong>채점 전</strong> · 아직 채점값이 없습니다. 영상·설문 자료를 확인한 뒤 채점합니다.</p>}
        <p className="fine">영상 {session.videos.length}개 · 구간 {({ none: '없음', draft: '초안', confirmed: '확정' })[segmentState(session)]} · 설문 {surveyHandled(session)}/{SURVEY_TOTAL} · {session.note || '촬영 메모 없음'}</p>
        {item.manifest.migration_note && <p className="fine">{item.manifest.migration_note}</p>}
        {session.survey_version === 'survey-20260929-v3' && <p className="fine">빈칸 사유 {Object.keys(session.survey_blank_reasons ?? {}).length}개 · 등록 완료 기준 미확정 · 비교 대상 자격 미확정</p>}
        <p className="fine">영상 등록·8구간 시각·촬영 메모·재촬영은 「촬영」 메뉴에서, 설문은 「설문」 메뉴에서 다룹니다.</p>
        <details><summary>기술 정보</summary><p>촬영 기준: <strong>{protocolName(session)}</strong> · 설문 판본: <span className="mono">{session.survey_version}</span></p></details>
      </section>
      {writable && <section className="panel"><h2>자료 관리</h2>
        <CaseEditor item={item} run={run} refresh={refresh} />
      </section>}
    </div>
  </>;
}
