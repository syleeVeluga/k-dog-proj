import { useEffect, useRef, useState } from 'react';
import { Notification } from './Notification';
import { DeveloperSettings, Recovery } from './DeveloperSettings';
import { api } from './api';
import { mayLeave } from './Editing';
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
import { defaultRoute, hashOf, parseHash } from './navigation';
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
  const [viewSession, setViewSession] = useState('');
  const [search, setSearch] = useState('');
  const [eventFilter, setEventFilter] = useState('');
  const contextTitle = useRef<HTMLHeadingElement>(null);
  const [contextExpanded, setContextExpanded] = useState(false);
  const observedSession = useRef('');
  const current = cases.find(item => item.case_id === selection?.case_id) ?? null;
  const selected = current ? { ...current, selected_session_id: viewSession || current.selected_session_id } : null;
  function setSelected(item: Case | null) { setSelection(item); setViewSession(item?.selected_session_id ?? ''); observedSession.current = item?.selected_session_id ?? ''; }
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
  const writable = user?.role === 'operator' || user?.role === 'admin';
  const filters = { search, eventFilter, setSearch, setEventFilter };
  useEffect(() => { setContextExpanded(false); contextTitle.current?.focus(); }, [route, selected?.case_id, selected?.selected_session_id]);
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
  function closeMenu() {
    setMenuOpen(false);
    requestAnimationFrame(() => menuToggle.current?.focus());
  }
  const stateIndex = () => { const value = (window.history.state as { idx?: number } | null)?.idx; return typeof value === 'number' ? value : null; };
  function go(next: Route) {
    if (next !== routeRef.current && !mayLeave()) return;
    if (drawer && menuOpen) closeMenu();
    if (next === routeRef.current) return;
    const idx = historyIndex.current + 1;
    window.history.pushState({ idx }, '', hashOf(next));
    historyIndex.current = idx; routeRef.current = next; setRoute(next);
  }
  // 로그인·세션 확인 직후 hash를 역할에 맞게 확정한다. 권한 없는 경로는 첫 메뉴로 보낸다.
  function enter(next: User) {
    if (next.role !== 'developer') {
      const target = parseHash(window.location.hash, next.role) ?? defaultRoute(next.role);
      historyIndex.current = stateIndex() ?? 0;
      window.history.replaceState({ idx: historyIndex.current }, '', hashOf(target));
      routeRef.current = target; setRoute(target);
    }
    setUser(next);
  }
  useEffect(() => { setMenuOpen(!drawer); }, [drawer, user]);
  useEffect(() => {
    if (!user || user.role === 'developer') return;
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
    const clear = () => { setUser(null); setCases([]); setSelected(null); setCatalog(null); setUnavailableCases(0); };
    const unavailable = (event: Event) => setUnavailableCases((event as CustomEvent<number>).detail);
    window.addEventListener('kdog-unavailable-cases', unavailable);
    window.addEventListener('kdog-session-expired', clear);
    api<User>('/auth/me').then(enter).catch(() => {}).finally(() => setChecking(false));
    return () => { window.removeEventListener('kdog-session-expired', clear); window.removeEventListener('kdog-unavailable-cases', unavailable); };
  }, []);
  useEffect(() => {
    if (user && user.role !== 'developer') void run(async () => {
      setCases(await api<Case[]>('/cases'));
    });
  }, [user]);
  const surveyVersion = selected ? sessionOf(selected).survey_version : '';
  useEffect(() => {
    if (!user || user.role === 'developer') return;
    let active = true;
    setCatalog(null);
    api<Catalog>(`/catalog/survey${surveyVersion ? `?version=${encodeURIComponent(surveyVersion)}` : ''}`).then(value => { if (active) setCatalog(value); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : '설문 판본 조회 실패'); });
    return () => { active = false; };
  }, [user, surveyVersion]);
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
    <form onSubmit={e => { e.preventDefault(); const value = formFields(e.currentTarget); void run(async () => { enter(await api<User>('/auth/login', 'POST', value)); }); }}>
      <fieldset disabled={busy}><label>계정<input name="username" autoComplete="username" required /></label>
        <label>비밀번호<input name="password" type="password" autoComplete="current-password" required /></label>
        <button className="primary" type="submit">{busy ? '접속 중…' : '로그인'}</button></fieldset>
    </form><Notification message={error} kind="error" onClose={() => setError('')} />
    <p className="fine">직원 전용 · 계정은 운영 관리자에게 문의하세요.</p>
  </main>;

  const hasMenu = user.role !== 'developer';
  return <>
    <header inert={modal}>{hasMenu && <button ref={menuToggle} className="menu-toggle" aria-controls="lnb" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>메뉴</button>}
      <button className="wordmark plain" onClick={() => go('intake')}>K-DOG<span>FIELD NOTES</span></button>
      <div className="account"><span>{user.username} · {roleNames[user.role]}</span><button disabled={busy} onClick={() => void run(async () => {
        if (!mayLeave()) return; await api('/auth/logout', 'POST'); setUser(null); setSelected(null); setCases([]);
      })}>로그아웃</button></div></header>
    <div className="shell">
      {hasMenu && <Lnb role={user.role} current={route} go={go} visible={wide || menuOpen} drawer={drawer} close={closeMenu} />}
    <main inert={modal}>
      <Notification message={error} kind="error" onClose={() => setError('')} />
      <Notification message={notice} onClose={() => setNotice('')} />
      {unavailableCases > 0 && user.role !== 'developer' && <p role="alert">입력 자료 검증에 실패한 참가자 {unavailableCases}명은 목록에서 제외되었습니다. 운영 관리자에게 원본 저장소 확인을 요청하세요. 다른 참가자는 계속 사용할 수 있습니다.</p>}
      {busy && <Notification kind="working" message="처리 중입니다… 파일 업로드 중에는 이 화면을 유지하세요." />}
      {selected && fieldRoutes.includes(route) && <section className="panel participant-context" aria-label="선택 참가자">
        <h2 ref={contextTitle} tabIndex={-1}>{selected.event_id} / {selected.participant_id} / {selected.dog_name} / {selected.manifest.sessions.findIndex(s => s.session_id === selected.selected_session_id) + 1}차 촬영</h2>
        <label>{writable ? '저장 대상 회차 선택' : '조회 회차 선택'}<select aria-label="선택 세션" disabled={busy} value={selected.selected_session_id} onChange={e => {
          const id = e.target.value; if (!mayLeave()) return;
          if (!writable) { setViewSession(id); return; }
          void run(async () => { const saved = await api<Case>(`/cases/${selected.case_id}/sessions`, 'POST', { expected_revision: selected.input_revision, session_id: id }); setSelected(saved); await reload(); });
        }}>{selected.manifest.sessions.map((s, i) => <option key={s.session_id} value={s.session_id}>{i + 1}차 촬영 · 영상 {videoCounts(selected, i)}</option>)}</select></label>
        {writable && current?.selected_session_id !== selected.selected_session_id && <p role="status">다른 요청이 저장 대상 회차를 변경했습니다. 현재 화면의 회차를 확인하고 선택 세션에서 저장 대상을 다시 선택하세요.</p>}
        <div className={`context-tools${contextExpanded ? ' expanded' : ''}`}>
          <button className="context-toggle" aria-expanded={contextExpanded} aria-controls="context-extra" onClick={() => setContextExpanded(!contextExpanded)}>회차 안내·바로가기</button>
          <div id="context-extra" className="context-extra">
            <p className="fine">{writable ? '회차 선택은 저장 대상을 변경합니다. 이전 설문·영상·구간은 보존되며 새 회차에 복사하지 않습니다.' : '조회만 변경합니다. 운영자의 저장 대상과 입력 버전은 바뀌지 않습니다.'}</p>
            <div className="toolbar"><button onClick={() => { if (mayLeave()) setSelected(null); }}>전체 목록으로 돌아가기</button><button onClick={() => go('survey')}>설문 보기</button><button onClick={() => go('recording/record')}>촬영 자료 보기</button><button onClick={() => go('preprocess')}>전처리 상태 보기</button></div>
          </div>
        </div>
      </section>}
      <fieldset disabled={busy} className="workspace">
        {user.role === 'developer' ? <section><p className="eyebrow">개발자 전용</p><h1>개발 설정</h1>
          <DeveloperSettings />
          <button onClick={() => void run(async () => setNotice((await api<{ message: string }>('/developer/status')).message))}>인증 상태 확인</button>
        </section>
          : route === 'intake/upload' ? <FormsImporter cases={cases} run={run} done={async message => { setNotice(message); await reload(); }} />
          : route === 'validation' ? <ValidationData user={user} />
          : route === 'admin/users' ? <Users run={run} />
          : route === 'admin/backup' ? <section><h1>자료 관리</h1><Recovery /></section>
          : route === 'preprocess' ? <Preprocessing cases={cases} selected={selected} select={setSelected} filters={filters} user={user} writable={!!writable} run={run} goTo={go} refresh={async message => { await reload(); if (message) setNotice(message); }} />
          : route === 'scoring' ? <Scoring cases={cases} selected={selected} select={setSelected} filters={filters} user={user} run={run} goTo={go} refresh={async message => { await reload(); if (message) setNotice(message); }} />
          : route === 'report' || route === 'report/comparison' || route === 'report/export' ? <Report view={route === 'report' ? 'issue' : route === 'report/export' ? 'export' : 'comparison'} goTo={go} cases={cases} selected={selected} select={setSelected} filters={filters} user={user} run={run} refresh={async message => { await reload(); if (message) setNotice(message); }} />
          : route === 'survey' ? <Survey cases={cases} selected={selected} select={setSelected} filters={filters} catalog={catalog} writable={!!writable} goTo={go} />
          : route === 'recording/inbox' || route === 'recording/record' ? <Recording view={route === 'recording/inbox' ? 'inbox' : 'record'} user={user} cases={cases} selected={selected} select={setSelected} filters={filters} writable={!!writable} run={run} reload={reload} notify={setNotice} />
          : <Intake user={user} cases={cases} selected={selected} writable={!!writable} busy={busy} run={run} reload={reload}
              select={setSelected} filters={filters} status={connectionError || `3초마다 자동 갱신 · 마지막 조회 ${updatedAt}`} notify={setNotice} goTo={go} />}
      </fieldset>
      <footer>K-DOG · 현장 평가 자료 관리<span>접수 · 설문 · 촬영 · 채점 · 리포트</span></footer>
    </main>
    </div>
  </>;
}
