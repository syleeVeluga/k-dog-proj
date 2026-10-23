import { useEffect, useRef, useState } from 'react';
import { Notification } from './Notification';
import { DeveloperSettings, Recovery } from './DeveloperSettings';
import { api } from './api';
import { ActivityLogV4 } from './ActivityLogV4';
import { forgetEdits, mayLeave } from './Editing';
import { FormsImporter } from './FormsImporter';
import { Users } from './Users';
import { Intake } from './pages/Intake';
import { Survey } from './pages/Survey';
import { Recording } from './pages/Recording';
import { Preprocessing } from './pages/Preprocessing';
import { Scoring } from './pages/Scoring';
import { Report } from './pages/Report';
import { ValidationData } from './ValidationData';
import { Lnb, useMatch } from './Lnb';
import { LocationTrail, ParticipantTasks } from './LocationTrail';
import { defaultRoute, hashOf, parseHash, participantTasks } from './navigation';
import { videoCounts } from './progressText';
import type { Route } from './navigation';
import { formFields, roleNames, sessionOf } from './types';
import type { Case, Catalog, Role, Run, User } from './types';
import './style.css';

// 화면 위치는 URL hash(#/intake 등)에 남는다. 메뉴 구조는 navigation.ts가 정한다.
const fieldRoutes: Route[] = ['intake', 'survey', 'recording/inbox', 'recording/record', 'preprocess', 'scoring', 'report', 'report/export'];

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [cases, setCases] = useState<Case[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selection, setSelection] = useState<Case | null>(null);
  const selectionSequence = useRef(0);
  const caseRefreshVersion = useRef(0);
  const pinnedSession = useRef(false);
  const [viewSession, setViewSession] = useState('');
  const [search, setSearch] = useState('');
  const [eventFilter, setEventFilter] = useState('');
  const [intakeFilter, setIntakeFilter] = useState('all');
  const [listOrigin, setListOrigin] = useState<Route>('intake');
  const contextTitle = useRef<HTMLHeadingElement>(null);
  const observedSession = useRef('');
  const current = cases.find(item => item.case_id === selection?.case_id) ?? null;
  const selected = current ? { ...current, selected_session_id: viewSession || current.selected_session_id } : null;
  function setSelected(item: Case | null) { selectionSequence.current++; pinnedSession.current = false; setSelection(item); setViewSession(item?.selected_session_id ?? ''); observedSession.current = item?.selected_session_id ?? ''; }
  const [updatedAt, setUpdatedAt] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [unavailableCases, setUnavailableCases] = useState(0);
  const [route, setRoute] = useState<Route>('intake');
  const routeRef = useRef<Route>('intake');
  const historyIndex = useRef(0);
  const restoring = useRef(false);
  const wide = useMatch('(min-width: 1024px)');
  const drawer = useMatch('(max-width: 767px)');
  const [menuOpen, setMenuOpen] = useState(() => window.innerWidth >= 768);
  const menuToggle = useRef<HTMLButtonElement>(null);
  const modal = drawer && menuOpen;
  const writable = !!user;
  const filters = { search, eventFilter, setSearch, setEventFilter };
  useEffect(() => { contextTitle.current?.focus(); }, [route, selected?.case_id, selected?.selected_session_id]);
  useEffect(() => {
    if (!current || !writable || observedSession.current === current.selected_session_id) return;
    const previous = observedSession.current;
    observedSession.current = current.selected_session_id;
    if (!pinnedSession.current && viewSession === previous && mayLeave()) setViewSession(current.selected_session_id);
  }, [current?.selected_session_id, writable]);

  const run: Run = async work => {
    setBusy(true); setError(''); setNotice('');
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : '작업을 완료하지 못했습니다.'); }
    finally { setBusy(false); }
  };
  async function reload(id?: string) {
    const version = ++caseRefreshVersion.current;
    const values = await api<Case[]>('/cases');
    if (version !== caseRefreshVersion.current) return;
    setCases(values); setUpdatedAt(new Date().toLocaleTimeString());
    if (id && id !== selection?.case_id) setSelected(values.find(c => c.case_id === id) ?? null);
  }
  function closeMenu() {
    setMenuOpen(false);
    requestAnimationFrame(() => menuToggle.current?.focus());
  }
  const stateIndex = () => { const value = (window.history.state as { idx?: number } | null)?.idx; return typeof value === 'number' ? value : null; };
  function go(next: Route) {
    if (next !== routeRef.current && !mayLeave()) return false;
    if (drawer && menuOpen) closeMenu();
    if (next === routeRef.current) return true;
    if (selected && participantTasks.includes(next) && !participantTasks.includes(routeRef.current) && fieldRoutes.includes(routeRef.current)) setListOrigin(routeRef.current);
    const idx = historyIndex.current + 1;
    window.history.pushState({ idx }, '', hashOf(next));
    historyIndex.current = idx; routeRef.current = next; setRoute(next);
    return true;
  }
  function goMenu(next: Route) {
    if (go(next) && (next === 'intake' || next === 'survey')) setListOrigin(next);
  }
  const listRoute = participantTasks.includes(route) ? listOrigin : route.startsWith('recording/') ? 'intake' : route;
  function backToList() {
    if (!mayLeave()) return;
    forgetEdits(); setSelected(null); go(listRoute);
  }
  // 로그인·세션 확인 직후 hash를 역할에 맞게 확정한다. 권한 없는 경로는 첫 메뉴로 보낸다.
  function enter(next: User) {
    setListOrigin('intake');
    const target = parseHash(window.location.hash, next.role) ?? defaultRoute(next.role);
    historyIndex.current = stateIndex() ?? 0;
    window.history.replaceState({ idx: historyIndex.current }, '', hashOf(target));
    routeRef.current = target; setRoute(target);
    setUser(next);
  }
  useEffect(() => { setMenuOpen(!drawer); }, [drawer, user]);
  useEffect(() => {
    if (!user) return;
    const role = user.role;
    // 뒤로가기·주소 직접 수정도 미저장 입력 보호를 거친다. 취소하면 기록 위치째로 원래 항목으로 되돌린다.
    const onHash = () => {
      if (restoring.current) { restoring.current = false; return; }
      const arrived = stateIndex();
      const parsed = parseHash(window.location.hash, role);
      const target = parsed ?? defaultRoute(role);
      const changes = target !== routeRef.current;
      if (changes && !mayLeave()) {
        if (arrived !== null && arrived !== historyIndex.current) {
          restoring.current = true; window.setTimeout(() => { restoring.current = false; }, 1000);
          window.history.go(historyIndex.current - arrived);
        } else window.history.replaceState({ idx: historyIndex.current }, '', hashOf(routeRef.current));
        return;
      }
      const idx = arrived ?? historyIndex.current + 1;
      historyIndex.current = idx;
      if (!parsed || arrived === null) window.history.replaceState({ idx }, '', hashOf(target));
      if (changes) { routeRef.current = target; setRoute(target); }
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [user?.role]);
  useEffect(() => {
    const clear = () => { for (const key of Object.keys(sessionStorage)) if (key.startsWith('kdog-preprocess:') || key.startsWith('kdog-ai:')) sessionStorage.removeItem(key); setUser(null); setCases([]); setSelected(null); setCatalog(null); setUnavailableCases(0); };
    const unavailable = (event: Event) => setUnavailableCases((event as CustomEvent<number>).detail);
    window.addEventListener('kdog-unavailable-cases', unavailable);
    window.addEventListener('kdog-session-expired', clear);
    api<User>('/auth/me').then(enter).catch(() => {}).finally(() => setChecking(false));
    return () => { window.removeEventListener('kdog-session-expired', clear); window.removeEventListener('kdog-unavailable-cases', unavailable); };
  }, []);
  useEffect(() => {
    if (user) void run(async () => {
      const version = caseRefreshVersion.current;
      const values = await api<Case[]>('/cases');
      if (version === caseRefreshVersion.current) setCases(values);
    });
  }, [user]);
  const surveyVersion = selected ? sessionOf(selected).survey_version : '';
  useEffect(() => {
    if (!user) return;
    let active = true;
    setCatalog(null);
    api<Catalog>(`/catalog/survey${surveyVersion ? `?version=${encodeURIComponent(surveyVersion)}` : ''}`).then(value => { if (active) setCatalog(value); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : '설문 판본 조회 실패'); });
    return () => { active = false; };
  }, [user, surveyVersion]);
  useEffect(() => {
    if (!user) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const version = caseRefreshVersion.current;
      try { const items = await api<Case[]>('/cases'); if (active && version === caseRefreshVersion.current) { setCases(items); setUpdatedAt(new Date().toLocaleTimeString()); setConnectionError(''); } }
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
    <form onSubmit={e => { e.preventDefault(); const value = formFields(e.currentTarget); void run(async () => { enter(await api<User>('/auth/login', 'POST', value)); }); }}>
      <fieldset disabled={busy}><label>계정<input name="username" autoComplete="username" required /></label>
        <label>비밀번호<input name="password" type="password" autoComplete="current-password" required /></label>
        <button className="primary" type="submit">{busy ? '접속 중…' : '로그인'}</button></fieldset>
    </form><Notification message={error} kind="error" onClose={() => setError('')} />
    <p className="fine">업무 계정으로 로그인하세요.</p>
  </main>;

  const openCase = async (item: Pick<Case, 'case_id' | 'selected_session_id'> & { pinSession?: boolean } | null, next?: Route) => {
    if (next && !mayLeave()) return false;
    if (!item) { setSelected(null); return true; }
    const current = ++selectionSequence.current, context = routeRef.current;
    let opened = false;
    await run(async () => {
      const value = await api<Case>(`/cases/${item.case_id}?purpose=open`);
      if (current !== selectionSequence.current || context !== routeRef.current) return;
      if (next) forgetEdits();
      caseRefreshVersion.current++;
      setCases(values => values.some(row => row.case_id === value.case_id) ? values.map(row => row.case_id === value.case_id ? value : row) : [...values, value]);
      if (!route.startsWith('recording/') && (!selected || (next && !participantTasks.includes(route)))) setListOrigin(route);
      setSelected({ ...value, selected_session_id: item.selected_session_id });
      pinnedSession.current = !!item.pinSession;
      observedSession.current = value.selected_session_id;
      if (next) go(next);
      opened = true;
    });
    return opened;
  };
  return <>
    <header inert={modal}><button ref={menuToggle} className="menu-toggle" aria-controls="lnb" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>메뉴</button>
      <button className="wordmark plain" onClick={() => go('intake')}>K-DOG<span>FIELD NOTES</span></button>
      <div className="account"><span>{user.username} · {roleNames[user.role]}</span><button disabled={busy} onClick={() => void run(async () => {
        if (!mayLeave()) return; await api('/auth/logout', 'POST'); for (const key of Object.keys(sessionStorage)) if (key.startsWith('kdog-preprocess:') || key.startsWith('kdog-ai:')) sessionStorage.removeItem(key); setUser(null); setSelected(null); setCases([]);
      })}>로그아웃</button></div></header>
    <div className="shell">
      <Lnb role={user.role} current={selected && participantTasks.includes(route) ? listOrigin : route.startsWith('recording/') ? 'intake' : route} go={goMenu} visible={wide || menuOpen} drawer={drawer} close={closeMenu} />
    <main inert={modal}>
      <LocationTrail route={route} selected={fieldRoutes.includes(route) ? selected : null} listRoute={listRoute} back={backToList} />
      <Notification message={error} kind="error" onClose={() => setError('')} />
      <Notification message={notice} onClose={() => setNotice('')} />
      {unavailableCases > 0 && <p role="alert">입력 자료 검증에 실패한 참가자 {unavailableCases}명은 목록에서 제외되었습니다. 원본 저장소를 확인하세요. 다른 참가자는 계속 사용할 수 있습니다.</p>}
      {busy && <Notification kind="working" message="처리 중입니다… 파일 업로드 중에는 이 화면을 유지하세요." />}
      {selected && fieldRoutes.includes(route) && <section className="panel participant-context" aria-label="선택 참가자">
        <div className="context-return"><button onClick={backToList}>전체 목록으로 돌아가기</button></div>
        <h2 ref={contextTitle} tabIndex={-1}>{selected.event_id} / {selected.participant_id} / {selected.dog_name} / {selected.manifest.sessions.findIndex(s => s.session_id === selected.selected_session_id) + 1}차 촬영</h2>
        {writable && current?.selected_session_id !== selected.selected_session_id && <p role="status">다른 작업에서 촬영 회차가 변경되었습니다. 현재 화면의 자료는 유지됩니다. 회차를 다시 열려면 촬영 이력을 이용하세요.</p>}
        {selected.manifest.sessions.length > 1 && <details className="session-history" key={`${selected.case_id}:${selected.selected_session_id}`}>
          <summary>촬영 이력 ({selected.manifest.sessions.length}회)</summary>
          <p className="fine">이전 촬영의 자료를 확인하거나 보완할 때 여세요. 이후 작업은 열어 둔 회차에서 이어집니다.</p>
          <ul>{selected.manifest.sessions.map((s, i) => <li key={s.session_id}>
            <div><strong>{i + 1}차 촬영</strong><small>영상 {videoCounts(selected, i)}</small></div>
            {s.session_id === selected.selected_session_id && s.session_id === current?.selected_session_id ? <span className="tag">현재 작업 중</span>
              : <button disabled={busy} onClick={() => {
                if (!mayLeave()) return;
                if (!writable) { forgetEdits(); setViewSession(s.session_id); return; }
                void run(async () => { const saved = await api<Case>(`/cases/${selected.case_id}/sessions`, 'POST', { expected_revision: selected.input_revision, session_id: s.session_id }); forgetEdits(); setSelected(saved); await reload(); });
              }}>{i + 1}차 촬영 열기</button>}
          </li>)}</ul>
        </details>}
        <ActivityLogV4 key={selected.case_id} path={`/cases/${selected.case_id}/activity`} />
      </section>}
      {selected && (route === 'intake' || participantTasks.includes(route)) && <ParticipantTasks route={route} go={go} />}
      <fieldset disabled={busy} className="workspace">
        {route === 'developer/settings' ? <section><p className="eyebrow">개발자 전용</p><h1>개발 설정</h1>
          <DeveloperSettings />
        </section>
          : route === 'intake/upload' ? <FormsImporter cases={cases} run={run} done={async message => { setNotice(message); await reload(); }} />
          : route === 'validation' ? <ValidationData user={user} />
          : route === 'admin/users' ? <Users run={run} />
          : route === 'admin/backup' ? <section><h1>자료 관리</h1><Recovery /></section>
          : route === 'preprocess' ? <Preprocessing cases={cases} selected={selected} select={openCase} openParticipant={openCase} filters={filters} user={user} writable={!!writable} run={run} goTo={go} refresh={async message => { await reload(); if (message) setNotice(message); }} />
          : route === 'scoring' ? <Scoring cases={cases} selected={selected} select={openCase} filters={filters} user={user} run={run} goTo={go} refresh={async message => { await reload(); if (message) setNotice(message); }} />
          : route === 'report' || route === 'report/comparison' || route === 'report/export' ? <Report view={route === 'report' ? 'issue' : route === 'report/export' ? 'export' : 'comparison'} goTo={go} cases={cases} selected={selected} select={openCase} filters={filters} user={user} run={run} refresh={async message => { await reload(); if (message) setNotice(message); }} />
          : route === 'survey' ? <Survey cases={cases} selected={selected} select={openCase} openParticipant={openCase} filters={filters} catalog={catalog} writable={!!writable} goTo={go} />
          : route.startsWith('recording/') ? <Recording key={route} view={route === 'recording/record' ? 'record' : route === 'recording/shared' ? 'shared' : 'inbox'} user={user} cases={cases} selected={route === 'recording/shared' ? null : selected} select={openCase} filters={filters} writable={!!writable} run={run} reload={reload} notify={setNotice} goTo={go} back={backToList} />
          : <Intake user={user} cases={cases} selected={selected} writable={!!writable} busy={busy} run={run} reload={reload}
              select={item => { if (item) setListOrigin('intake'); setSelected(item); }} openParticipant={openCase} filters={filters} filter={intakeFilter} setFilter={setIntakeFilter} status={connectionError || `3초마다 자동 갱신 · 마지막 조회 ${updatedAt}`} notify={setNotice} goTo={go} />}
      </fieldset>
      <footer>K-DOG · 현장 평가 자료 관리<span>접수 · 설문 · 촬영 · 채점 · 리포트</span></footer>
    </main>
    </div>
  </>;
}
