import { useEffect, useRef, useState } from 'react';
import { Notification } from './Notification';
import { DeveloperSettings, Recovery } from './DeveloperSettings';
import { api } from './api';
import { mayLeave } from './Editing';
import { Importer } from './Importer';
import { Users } from './Users';
import { Intake } from './pages/Intake';
import { Survey } from './pages/Survey';
import { Recording } from './pages/Recording';
import { Preprocessing } from './pages/Preprocessing';
import { formFields, roleNames } from './types';
import type { Case, Catalog, Role, Run, User } from './types';
import './style.css';

type Page = 'intake' | 'survey' | 'recording' | 'import' | 'users' | 'data' | 'preprocess';
// 대메뉴 하나가 PR 하나다: 접수(PR-6) · 설문(PR-7) · 촬영(PR-8) · 자료 가져오기 · 직원 계정.
const menu: { page: Page; label: string; roles: Role[] }[] = [
  { page: 'intake', label: '접수', roles: ['operator', 'reviewer', 'admin'] },
  { page: 'survey', label: '설문', roles: ['operator', 'reviewer', 'admin'] },
  { page: 'recording', label: '촬영', roles: ['operator', 'reviewer', 'admin'] },
  { page: 'preprocess', label: '전처리', roles: ['operator', 'reviewer', 'admin'] },
  { page: 'import', label: '자료 가져오기', roles: ['operator', 'admin'] },
  { page: 'users', label: '직원 계정', roles: ['admin'] },
  { page: 'data', label: '자료 관리', roles: ['admin'] },
];

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [cases, setCases] = useState<Case[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selection, setSelection] = useState<Case | null>(null);
  const [viewSession, setViewSession] = useState('');
  const [search, setSearch] = useState('');
  const [eventFilter, setEventFilter] = useState('');
  const contextTitle = useRef<HTMLHeadingElement>(null);
  const observedSession = useRef('');
  const current = cases.find(item => item.case_id === selection?.case_id) ?? null;
  const selected = current ? { ...current, selected_session_id: viewSession || current.selected_session_id } : null;
  function setSelected(item: Case | null) { setSelection(item); setViewSession(item?.selected_session_id ?? ''); observedSession.current = item?.selected_session_id ?? ''; }
  const [updatedAt, setUpdatedAt] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [unavailableCases, setUnavailableCases] = useState(0);
  const [page, setPage] = useState<Page>('intake');
  const writable = user?.role === 'operator' || user?.role === 'admin';
  const filters = { search, eventFilter, setSearch, setEventFilter };
  useEffect(() => { contextTitle.current?.focus(); }, [page, selected?.case_id, selected?.selected_session_id]);
  useEffect(() => {
    if (!current || !writable || observedSession.current === current.selected_session_id) return;
    observedSession.current = current.selected_session_id;
    if (mayLeave()) setViewSession(current.selected_session_id);
  }, [current?.selected_session_id, writable]);

  const run: Run = async work => {
    setBusy(true); setError(''); setNotice('');
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : '작업을 완료하지 못했습니다.'); }
    finally { setBusy(false); }
  };
  async function reload(id?: string) {
    const values = await api<Case[]>('/cases');
    setCases(values); setUpdatedAt(new Date().toLocaleTimeString());
    if (id && id !== selection?.case_id) setSelected(values.find(c => c.case_id === id) ?? null);
  }
  function go(next: Page) {
    if (!mayLeave()) return;
    setPage(next);
  }
  useEffect(() => {
    const clear = () => { setUser(null); setCases([]); setSelected(null); setCatalog(null); setUnavailableCases(0); };
    const unavailable = (event: Event) => setUnavailableCases((event as CustomEvent<number>).detail);
    window.addEventListener('kdog-unavailable-cases', unavailable);
    window.addEventListener('kdog-session-expired', clear);
    api<User>('/auth/me').then(setUser).catch(() => {}).finally(() => setChecking(false));
    return () => { window.removeEventListener('kdog-session-expired', clear); window.removeEventListener('kdog-unavailable-cases', unavailable); };
  }, []);
  useEffect(() => {
    if (user && user.role !== 'developer') void run(async () => {
      const [items, questions] = await Promise.all([api<Case[]>('/cases'), api<Catalog>('/catalog/survey')]);
      setCases(items); setCatalog(questions);
    });
  }, [user]);
  useEffect(() => {
    if (!user || user.role === 'developer') return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const items = await api<Case[]>('/cases'); if (active) { setCases(items); setUpdatedAt(new Date().toLocaleTimeString()); setConnectionError(''); } }
      catch { if (active) setConnectionError('목록 연결이 끊겼습니다. 마지막 조회 결과를 표시하며 자동 재연결합니다.'); }
      if (active) timer = setTimeout(poll, 3000);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [user]);

  if (checking) return <main><p role="status">접속 확인 중…</p></main>;
  if (!user) return <main className="login">
    <div className="wordmark">K-DOG<span>FIELD NOTES</span></div>
    <p className="eyebrow">운영자 워크스페이스</p><h1>관찰의 시작은<br />정확한 연결부터.</h1>
    <p className="muted">참가자와 설문, 촬영 자료를 한곳에서 관리합니다.</p>
    <form onSubmit={e => { e.preventDefault(); const value = formFields(e.currentTarget); void run(async () => { setUser(await api<User>('/auth/login', 'POST', value)); setPage('intake'); }); }}>
      <fieldset disabled={busy}><label>계정<input name="username" autoComplete="username" required /></label>
        <label>비밀번호<input name="password" type="password" autoComplete="current-password" required /></label>
        <button className="primary" type="submit">{busy ? '접속 중…' : '로그인'}</button></fieldset>
    </form><Notification message={error} kind="error" onClose={() => setError('')} />
    <p className="fine">직원 전용 · 계정은 운영 관리자에게 문의하세요.</p>
  </main>;

  return <>
    <header><button className="wordmark plain" onClick={() => go('intake')}>K-DOG<span>FIELD NOTES</span></button>
      <div className="account"><span>{user.username} · {roleNames[user.role]}</span><button disabled={busy} onClick={() => void run(async () => {
        if (!mayLeave()) return; await api('/auth/logout', 'POST'); setUser(null); setSelected(null); setCases([]);
      })}>로그아웃</button></div></header>
    <main>
      {user.role !== 'developer' && <nav aria-label="주 메뉴">
        {menu.filter(entry => entry.roles.includes(user.role)).map(entry =>
          <button key={entry.page} aria-current={page === entry.page ? 'page' : undefined} onClick={() => go(entry.page)}>{entry.label}</button>)}
      </nav>}
      <Notification message={error} kind="error" onClose={() => setError('')} />
      <Notification message={notice} onClose={() => setNotice('')} />
      {unavailableCases > 0 && user.role !== 'developer' && <p role="alert">입력 자료 검증에 실패한 참가자 {unavailableCases}명은 목록에서 제외되었습니다. 운영 관리자에게 원본 저장소 확인을 요청하세요. 다른 참가자는 계속 사용할 수 있습니다.</p>}
      {busy && <Notification kind="working" message="처리 중입니다… 파일 업로드 중에는 이 화면을 유지하세요." />}
      {selected && ['intake', 'survey', 'recording', 'preprocess'].includes(page) && <section className="panel" aria-label="선택 참가자">
        <h2 ref={contextTitle} tabIndex={-1}>{selected.event_id} / {selected.participant_id} / {selected.dog_name} / {selected.manifest.sessions.findIndex(s => s.session_id === selected.selected_session_id) + 1}차 촬영</h2>
        <label>{writable ? '저장 대상 회차 선택' : '조회 회차 선택'}<select aria-label="선택 세션" disabled={busy} value={selected.selected_session_id} onChange={e => {
          const id = e.target.value; if (!mayLeave()) return;
          if (!writable) { setViewSession(id); return; }
          void run(async () => { const saved = await api<Case>(`/cases/${selected.case_id}/sessions`, 'POST', { expected_revision: selected.input_revision, session_id: id }); setSelected(saved); await reload(); });
        }}>{selected.manifest.sessions.map((s, i) => <option key={s.session_id} value={s.session_id}>{i + 1}차 촬영 · 영상 {s.videos.length}개</option>)}</select></label>
        <p className="fine">{writable ? '회차 선택은 저장 대상을 변경합니다. 이전 설문·영상·구간은 보존되며 새 회차에 복사하지 않습니다.' : '조회만 변경합니다. 운영자의 저장 대상과 입력 버전은 바뀌지 않습니다.'}</p>
        {writable && current?.selected_session_id !== selected.selected_session_id && <p role="status">다른 요청이 저장 대상 회차를 변경했습니다. 현재 화면의 회차를 확인하고 선택 세션에서 저장 대상을 다시 선택하세요.</p>}
        <div className="toolbar"><button onClick={() => { if (mayLeave()) setSelected(null); }}>전체 목록으로 돌아가기</button><button onClick={() => go('survey')}>설문 보기</button><button onClick={() => go('recording')}>촬영 자료 보기</button><button onClick={() => go('preprocess')}>전처리 상태 보기</button></div>
      </section>}
      <fieldset disabled={busy} className="workspace">
        {user.role === 'developer' ? <section><p className="eyebrow">개발자 전용</p><h1>개발 설정</h1>
          <DeveloperSettings />
          <button onClick={() => void run(async () => setNotice((await api<{ message: string }>('/developer/status')).message))}>인증 상태 확인</button>
        </section>
          : page === 'import' ? <Importer run={run} catalog={catalog} catalogVersion={catalog?.version ?? ''} done={async message => { setNotice(message); await reload(); }} />
          : page === 'users' ? <Users run={run} />
          : page === 'data' ? <section><h1>자료 관리</h1><Recovery /></section>
          : page === 'preprocess' ? <Preprocessing cases={cases} selected={selected} select={setSelected} filters={filters} writable={!!writable} />
          : page === 'survey' ? <Survey cases={cases} selected={selected} select={setSelected} filters={filters} catalog={catalog} writable={!!writable} run={run} reload={reload} notify={setNotice} />
          : page === 'recording' ? <Recording cases={cases} selected={selected} select={setSelected} filters={filters} writable={!!writable} run={run} reload={reload} notify={setNotice} />
          : <Intake user={user} cases={cases} selected={selected} writable={!!writable} run={run} reload={reload}
              select={setSelected} filters={filters} status={connectionError || `3초마다 자동 갱신 · 마지막 조회 ${updatedAt}`} notify={setNotice} />}
      </fieldset>
      <footer>K-DOG · 현장 평가 자료 관리<span>접수 · 설문 · 촬영 · 채점 · 리포트</span></footer>
    </main>
  </>;
}
