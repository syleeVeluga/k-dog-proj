import { useEffect, useState } from 'react';
import { api } from '../api';
import { mayLeave } from '../Editing';
import { Observations } from '../Observations';
import { CaseEditor, SessionEditor } from '../MetadataEditors';
import { VideoUpload } from '../VideoUpload';
import { formFields, sessionOf } from '../types';
import type { Case, Run } from '../types';

export function CaseDetail({ item, writable, run, refresh, back }: {
  item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; back: () => void;
}) {
  const [viewSession, setViewSession] = useState(item.selected_session_id);
  const [view, setView] = useState<'analysis' | 'report'>('analysis');
  const session = item.manifest.sessions.find(s => s.session_id === (writable ? item.selected_session_id : viewSession)) ?? sessionOf(item);
  const [playing, setPlaying] = useState<string | null>(null);
  useEffect(() => { setPlaying(null); }, [session.session_id, view]);
  function changeView(next: 'analysis' | 'report') {
    setView(next);
    document.getElementById('analysis')?.scrollIntoView({ block: 'start' });
  }
  const profile = [item.dog.breed, item.dog.sex !== '미기재' && item.dog.sex, item.dog.age_years !== null && `${item.dog.age_years}세`,
    item.dog.size !== '미기재' && item.dog.size, item.dog.years_together && `함께 ${item.dog.years_together}`,
    item.dog.adoption_route !== '미기재' && item.dog.adoption_route].filter(Boolean).join(' · ');
  return <>
    <button className="plain back" onClick={back}>← 접수 목록</button>
    <section className="page-heading"><div><p className="eyebrow">{item.event_id} / {item.participant_id}{item.sequence_no !== null && ` · 순번 ${item.sequence_no}`}</p><h1>{item.dog_name}</h1>
      <p className="muted">{item.guardian_name ? `${item.guardian_name} 님` : '보호자명 없음'}{profile && ` · ${profile}`}</p>
      <p className="muted">{item.reservation_at ? `예약 ${item.reservation_at.replace('T', ' ')}` : '예약 정보 없음'} · <span className={item.consent_confirmed ? 'tag green' : 'tag'}>{item.consent_confirmed ? '동의 확인' : '동의 미확인'}</span></p></div>
      <span className="tag">입력 버전 {item.input_revision}</span></section>
    <nav className="section-nav" aria-label="참가자 업무">
      <button aria-current={view === 'analysis' ? 'page' : undefined} onClick={() => changeView('analysis')}>자료·이전 분석</button>
      <button aria-current={view === 'report' ? 'page' : undefined} onClick={() => changeView('report')}>보고서</button>
      {view === 'analysis' && <><a href="#videos">영상 자료</a><a href="#sessions">촬영 세션</a></>}
    </nav>
    <Observations item={item} writable={writable} view={view} />
    <div hidden={view !== 'analysis'}>
    <div className="detail-grid" id="sessions">
      <section className="panel"><h2>촬영 세션</h2><label>선택 세션<select aria-label="선택 세션" value={session.session_id} onChange={e => { if (!mayLeave()) return; if (!writable) { setViewSession(e.target.value); return; } void run(async () => {
        await api(`/cases/${item.case_id}/sessions`, 'POST', { expected_revision: item.input_revision, session_id: e.target.value }); await refresh();
      }); }}>{item.manifest.sessions.map((s, i) => <option key={s.session_id} value={s.session_id}>{i + 1}차 촬영 · 영상 {s.videos.length}개</option>)}</select></label>
        <p className="fine">{session.note || '촬영 메모 없음'}</p>
        {item.manifest.migration_note && <p className="fine">{item.manifest.migration_note}</p>}
        {writable && <SessionEditor key={session.session_id} item={item} session={session} run={run} refresh={refresh} />}
        {writable && <details><summary>재촬영 세션 추가</summary><form onSubmit={e => { e.preventDefault(); if (!mayLeave()) return; const value = formFields(e.currentTarget); void run(async () => {
          await api(`/cases/${item.case_id}/sessions`, 'POST', { ...value, expected_revision: item.input_revision }); await refresh();
        }); }}><label>촬영 메모<textarea name="note" maxLength={2000} /></label><p className="fine">이전 촬영은 보존됩니다. 새 세션에는 설문과 영상을 따로 연결하세요.</p><button>새 촬영 시작</button></form></details>}
      </section>
      {writable && <section className="panel"><h2>자료 관리</h2>
        <CaseEditor item={item} run={run} refresh={refresh} />
        <details><summary>삭제 요청 접수</summary><form onSubmit={e => { e.preventDefault(); void run(async () => {
          await api(`/cases/${item.case_id}/deletion`, 'POST', { expected_revision: item.input_revision }); await refresh();
        }); }}><label className="check"><input type="checkbox" required />삭제 요청됨</label>
          <p className="fine">저장하면 목록과 파일 접근이 차단되고 진행 중인 분석이 중지됩니다. 실제 파일 폐기는 보관 정책에 따라 별도 처리합니다.</p>
          <button>삭제 요청 저장</button></form></details>
      </section>}
    </div>
    <section className="panel" id="videos"><div className="section-title"><h2>영상 자료</h2><span className="mono">{session.videos.length} FILES</span></div>
      {session.videos.length === 0 && <p className="muted">등록된 영상이 없습니다. 참가자·촬영 세션을 확인한 후 파일을 선택하세요.</p>}
      {session.videos.map(v => <div className="video-row" key={v.video_id}><div><strong>{v.original_name}</strong><small>{(v.size_bytes / 1048576).toFixed(2)} MiB · 원본 등록됨</small></div>
        <button onClick={() => setPlaying(`/api/cases/${item.case_id}/videos/${v.video_id}`)}>영상 열기</button></div>)}
      {playing && <div><video src={playing} controls preload="metadata" /><button onClick={() => setPlaying(null)}>재생 닫기</button></div>}
      {writable && <VideoUpload key={session.session_id} item={item} session={session} refresh={refresh} />}
    </section>
    <p className="fine">설문 등록 현황과 결과는 「설문」 메뉴에서 봅니다.</p>
    </div>
  </>;
}
