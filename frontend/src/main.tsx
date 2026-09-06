import { useEffect, useState } from 'react';
import { EvaluationSettings } from './EvaluationSettings';
import { DeveloperSettings, Recovery } from './DeveloperSettings';
import { Exports, ReportSettings } from './Reports';
import type { FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { api } from './api';
import { Observations, analysisNames } from './Observations';
import type { Case, Catalog, Preview, Role, User } from './types';
import './style.css';

const roleNames: Record<Role, string> = { operator: '운영자', reviewer: '교수 / 검토자', admin: '운영 관리자', developer: '개발자' };
const sessionOf = (item: Case) => item.manifest.sessions.find(s => s.session_id === item.selected_session_id)!;
const fields = (event: FormEvent<HTMLFormElement>) => Object.fromEntries(new FormData(event.currentTarget));
type Run = (work: () => Promise<void>) => Promise<void>;

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [cases, setCases] = useState<Case[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selected, setSelected] = useState<Case | null>(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [versionedSettings, setVersionedSettings] = useState(false);
  const [page, setPage] = useState<'cases' | 'import' | 'users'>('cases');
  const writable = user?.role === 'operator' || user?.role === 'admin';

  const run: Run = async work => {
    setBusy(true); setError(''); setNotice('');
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : '작업을 완료하지 못했습니다.'); }
    finally { setBusy(false); }
  };
  async function reload(id?: string) {
    const values = await api<Case[]>('/cases');
    setCases(values);
    if (id) setSelected(values.find(c => c.case_id === id) ?? null);
  }
  useEffect(() => {
    const clear = () => { setUser(null); setCases([]); setSelected(null); setCatalog(null); };
    window.addEventListener('kdog-session-expired', clear);
    api<User>('/auth/me').then(setUser).catch(() => {}).finally(() => setChecking(false));
    return () => window.removeEventListener('kdog-session-expired', clear);
  }, []);
  useEffect(() => {
    if (user && user.role !== 'developer') void run(async () => {
      const [items, questions] = await Promise.all([api<Case[]>('/cases'), api<Catalog>('/catalog/survey')]);
      setCases(items); setCatalog(questions);
    });
  }, [user]);

  const visible = cases.filter(c => {
    const session = sessionOf(c);
    const ready = session.videos.length > 0 && Object.values(session.survey).every(v => v !== null);
    return `${c.event_id} ${c.participant_id} ${c.dog_name}`.toLowerCase().includes(search.toLowerCase())
      && (filter === 'all' || (filter === 'ready' ? ready : !ready));
  });

  if (checking) return <main><p role="status">접속 확인 중…</p></main>;
  if (!user) return <main className="login">
    <div className="wordmark">K-DOG<span>FIELD NOTES</span></div>
    <p className="eyebrow">운영자 워크스페이스</p><h1>관찰의 시작은<br />정확한 연결부터.</h1>
    <p className="muted">참가자와 설문, 촬영 자료를 한곳에서 관리합니다.</p>
    <form onSubmit={e => { e.preventDefault(); const value = fields(e); void run(async () => { setUser(await api<User>('/auth/login', 'POST', value)); setPage('cases'); }); }}>
      <fieldset disabled={busy}><label>계정<input name="username" autoComplete="username" required /></label>
        <label>비밀번호<input name="password" type="password" autoComplete="current-password" required /></label>
        <button className="primary" type="submit">{busy ? '접속 중…' : '로그인'}</button></fieldset>
    </form>{error && <p role="alert" className="error">{error}</p>}
    <p className="fine">직원 전용 · 계정은 운영 관리자에게 문의하세요.</p>
  </main>;

  return <>
    <header><button className="wordmark plain" onClick={() => { setPage('cases'); setSelected(null); }}>K-DOG<span>FIELD NOTES</span></button>
      <div className="account"><span>{user.username} · {roleNames[user.role]}</span><button disabled={busy} onClick={() => void run(async () => {
        await api('/auth/logout', 'POST'); setUser(null); setSelected(null); setCases([]);
      })}>로그아웃</button></div></header>
    <main>
      {user.role !== 'developer' && <nav aria-label="주 메뉴">
        <button aria-current={page === 'cases' ? 'page' : undefined} onClick={() => { setPage('cases'); setSelected(null); }}>참가자</button>
        {writable && <button aria-current={page === 'import' ? 'page' : undefined} onClick={() => setPage('import')}>자료 가져오기</button>}
        {user.role === 'admin' && <button aria-current={page === 'users' ? 'page' : undefined} onClick={() => setPage('users')}>직원 계정</button>}
      </nav>}
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {busy && <p className="working" role="status">처리 중입니다… 파일 업로드 중에는 이 화면을 유지하세요.</p>}
      <fieldset disabled={busy} className="workspace">
        {user.role === 'developer' ? <section><p className="eyebrow">개발자 전용</p><h1>개발 설정</h1>
          <DeveloperSettings onVersionModeChange={setVersionedSettings} />
          {!versionedSettings && <><EvaluationSettings /><ReportSettings /></>}
          <button onClick={() => void run(async () => setNotice((await api<{ message: string }>('/developer/status')).message))}>인증 상태 확인</button>
        </section> : page === 'import' ? <Importer run={run} catalogVersion={catalog?.version ?? ''} done={async message => { setNotice(message); await reload(); }} />
          : page === 'users' ? <Users run={run} />
          : selected && catalog ? <Detail key={`${selected.case_id}-${selected.input_revision}`} item={selected} catalog={catalog} writable={writable} run={run}
            back={() => void run(async () => { setSelected(null); await reload(); })} refresh={async () => { await reload(selected.case_id); setNotice('저장되었습니다.'); }} />
            : <>
              <section className="page-heading"><div><p className="eyebrow">PARTICIPANT REGISTER</p><h1>참가자 자료</h1><p className="muted">ID를 기준으로 설문과 촬영 자료를 연결하세요.</p></div>
                <div className="count"><strong>{cases.length.toString().padStart(2, '0')}</strong><span>등록된 참가자</span></div></section>
              <div className="toolbar"><label>검색<input type="search" placeholder="참가자 ID, 반려견 이름, 행사" value={search} onChange={e => setSearch(e.target.value)} /></label>
                <label>자료 상태<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">전체</option><option value="ready">자료 등록 완료</option><option value="missing">자료 보완 필요</option></select></label>
                <button onClick={() => void run(() => reload())}>새로고침</button></div>
              <Exports />
              <div className="table-wrap"><table><thead><tr><th>참가자 / 행사</th><th>반려견</th><th>설문</th><th>영상</th><th>분석 상태</th><th>자료</th></tr></thead>
                <tbody>{visible.map(c => { const s = sessionOf(c); const count = Object.values(s.survey).filter(v => v !== null).length;
                  return <tr key={c.case_id}><td><strong className="mono">{c.participant_id}</strong><small>{c.event_id}</small></td><td>{c.dog_name}</td>
                    <td><span className={count === 30 ? 'tag green' : 'tag'}>{count}/30</span></td><td>{s.videos.length}개</td><td><span className="muted">{analysisNames[c.analysis_status] ?? '미실행'}</span></td>
                    <td><button aria-label={`${c.participant_id} 상세 열기`} onClick={() => void run(async () => setSelected(await api<Case>(`/cases/${c.case_id}`)))}>열기 ↗</button></td></tr>;
                })}</tbody></table>{!visible.length && <div className="empty"><h2>{cases.length ? '조건에 맞는 참가자가 없습니다.' : '첫 참가자를 등록하세요.'}</h2><p>행사와 참가자 ID를 먼저 확인한 뒤 자료를 연결합니다.</p></div>}</div>
              {writable && <details className="panel" open={!cases.length}><summary>참가자 등록</summary>
                <form onSubmit={e => { e.preventDefault(); const value = fields(e); void run(async () => {
                  const created = await api<Case>('/cases', 'POST', value); await reload(created.case_id); setNotice('참가자를 등록했습니다.');
                }); }}><div className="form-grid"><label>행사 ID<input name="event_id" placeholder="KDOG-2026" pattern="[A-Za-z0-9_-]+" required /></label>
                  <label>참가자 ID<input name="participant_id" placeholder="0001" pattern="[A-Za-z0-9_-]+" required /></label>
                  <label>반려견 이름<input name="dog_name" required maxLength={200} /></label><label>예약 시각<input name="reservation_at" type="datetime-local" /></label></div>
                  <p className="fine">이름이 같아도 참가자 ID는 각각 등록합니다. ID 앞자리 0은 그대로 보존됩니다.</p><button className="primary">참가자 저장</button></form></details>}
            </>}
      </fieldset>
      {user.role === 'admin' && <Recovery />}
      <footer>K-DOG · 현장 평가 자료 관리<span>영상 관찰 · 행동 평가 · 프로그램 점수 집계</span></footer>
    </main>
  </>;
}

function Detail({ item, catalog, writable, run, refresh, back }: {
  item: Case; catalog: Catalog; writable: boolean; run: Run; refresh: () => Promise<void>; back: () => void;
}) {
  const session = sessionOf(item);
  const [answers, setAnswers] = useState(session.survey);
  const [files, setFiles] = useState<FileList | null>(null);
  const [camera, setCamera] = useState('CAM-1');
  const [playing, setPlaying] = useState<string | null>(null);
  return <>
    <button className="plain back" onClick={back}>← 참가자 목록</button>
    <section className="page-heading"><div><p className="eyebrow">{item.event_id} / {item.participant_id}</p><h1>{item.dog_name}</h1>
      <p className="muted">{item.reservation_at ? `예약 ${item.reservation_at.replace('T', ' ')}` : '예약 정보 없음'}</p></div><span className="tag">입력 버전 {item.input_revision}</span></section>
    <div className="detail-grid">
      <section className="panel"><h2>촬영 세션</h2><label>선택 세션<select aria-label="선택 세션" value={session.session_id} disabled={!writable} onChange={e => void run(async () => {
        await api(`/cases/${item.case_id}/sessions`, 'POST', { expected_revision: item.input_revision, session_id: e.target.value }); await refresh();
      })}>{item.manifest.sessions.map((s, i) => <option key={s.session_id} value={s.session_id}>{i + 1}차 촬영 · 영상 {s.videos.length}개</option>)}</select></label>
        <p className="fine">동시/순차: {({ simultaneous: '동시 촬영', sequential: '순차 촬영', unknown: '미확인' })[session.capture_mode]}<br />{session.route_note || '동선 메모 없음'}</p>
        {writable && <details><summary>현재 촬영 정보 수정</summary><form onSubmit={e => { e.preventDefault(); const value = fields(e); void run(async () => {
          await api(`/cases/${item.case_id}/sessions/${session.session_id}`, 'PUT', { ...value, expected_revision: item.input_revision }); await refresh();
        }); }}><label>현재 촬영 방식<select name="capture_mode" defaultValue={session.capture_mode}><option value="unknown">미확인</option><option value="simultaneous">동시 촬영</option><option value="sequential">순차 촬영</option></select></label>
          <label>현재 동선 메모<textarea name="route_note" defaultValue={session.route_note} maxLength={2000} /></label><button>촬영 정보 저장</button></form></details>}
        {writable && <details><summary>재촬영 세션 추가</summary><form onSubmit={e => { e.preventDefault(); const value = fields(e); void run(async () => {
          await api(`/cases/${item.case_id}/sessions`, 'POST', { ...value, expected_revision: item.input_revision }); await refresh();
        }); }}><label>촬영 방식<select name="capture_mode"><option value="unknown">미확인</option><option value="simultaneous">동시 촬영</option><option value="sequential">순차 촬영</option></select></label>
          <label>동선 메모<textarea name="route_note" maxLength={2000} /></label><p className="fine">이전 촬영은 보존됩니다. 새 세션에는 설문과 영상을 따로 연결하세요.</p><button>새 촬영 시작</button></form></details>}
      </section>
      {writable && <section className="panel"><h2>자료 관리</h2>
        <details><summary>삭제 요청 접수</summary><form onSubmit={e => { e.preventDefault(); void run(async () => {
          await api(`/cases/${item.case_id}/deletion`, 'POST', { expected_revision: item.input_revision }); await refresh();
        }); }}><label className="check"><input type="checkbox" required />삭제 요청됨</label>
          <p className="fine">저장하면 목록과 파일 접근이 차단되고 진행 중인 분석이 중지됩니다. 실제 파일 폐기는 보관 정책에 따라 별도 처리합니다.</p>
          <button>삭제 요청 저장</button></form></details>
      </section>}
    </div>
    <section className="panel"><div className="section-title"><h2>영상 자료</h2><span className="mono">{session.videos.length} FILES</span></div>
      {session.videos.length === 0 && <p className="muted">등록된 영상이 없습니다. 참가자·촬영 세션·카메라를 확인한 후 파일을 선택하세요.</p>}
      {session.videos.map(v => <div className="video-row" key={v.video_id}><div><strong>{v.original_name}</strong><small>{v.camera_id} · {(v.size_bytes / 1048576).toFixed(2)} MiB · 원본 등록됨</small></div>
        <button onClick={() => setPlaying(`/api/cases/${item.case_id}/videos/${v.video_id}`)}>영상 열기</button></div>)}
      {playing && <div><video src={playing} controls preload="metadata" /><button onClick={() => setPlaying(null)}>재생 닫기</button></div>}
      {writable && <form onSubmit={e => { e.preventDefault(); if (!files) return; void run(async () => {
        let revision = item.input_revision;
        try {
          for (const file of files) {
            const query = new URLSearchParams({ session_id: session.session_id, camera_id: camera, filename: file.name, expected_revision: String(revision) });
            const updated = await api<Case>(`/cases/${item.case_id}/videos?${query}`, 'POST', file); revision = updated.input_revision;
          }
        } finally { await refresh(); }
      }); }}><fieldset>
        <div className="toolbar"><label>카메라 ID<input value={camera} pattern="[A-Za-z0-9_-]+" required onChange={e => setCamera(e.target.value)} /></label>
          <label>영상 파일<input type="file" accept=".mp4,.mov,.m4v,.avi,.mkv,.webm" multiple required onChange={e => setFiles(e.target.files)} /></label><button className="primary">영상 등록</button></div>
        <p className="fine">선택 파일은 모두 현재 카메라에 연결됩니다. 다른 카메라는 따로 등록하세요. 복사가 끝나야 저장됩니다.</p></fieldset>
        </form>}
    </section>
    <Observations item={item} writable={writable} />
    <details className="panel"><summary>설문 원응답 <span className="tag">{Object.values(answers).filter(v => v !== null).length}/30</span></summary>
      <p>{catalog.response_instructions}</p><p className="fine">미응답은 빈칸으로 보존합니다. q23 환산과 영역 집계는 아직 제공하지 않습니다.</p>
      <form onSubmit={e => { e.preventDefault(); void run(async () => {
        await api(`/cases/${item.case_id}/survey`, 'PUT', { expected_revision: item.input_revision, session_id: session.session_id, survey_version: catalog.version, answers }); await refresh();
      }); }}><fieldset disabled={!writable}><div className="questions">{catalog.items.map(q => <label key={q.item_id}><span><b className="mono">{q.item_id}</b> {q.text}</span>
        <select aria-label={`${q.item_id} 응답`} value={answers[q.item_id] ?? ''} onChange={e => setAnswers({ ...answers, [q.item_id]: e.target.value === '' ? null : Number(e.target.value) })}><option value="">미응답</option>{[1, 2, 3, 4, 5].map(n => <option value={n} key={n}>{n}</option>)}</select></label>)}</div>
        {writable && <button className="primary">설문 저장</button>}</fieldset></form>
    </details>
  </>;
}

function Importer({ run, done, catalogVersion }: { run: Run; done: (message: string) => Promise<void>; catalogVersion: string }) {
  const [kind, setKind] = useState('participants');
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Preview | null>(null);
  return <section><p className="eyebrow">STANDARD INTAKE</p><h1>자료 가져오기</h1><p className="muted">표준 CSV·Excel을 검증한 뒤 정상 행을 저장합니다.</p>
    <div className="panel"><label>자료 종류<select value={kind} onChange={e => { setKind(e.target.value); setResult(null); }}><option value="participants">참가자</option><option value="survey">설문 원응답</option></select></label>
      <p className="links"><a href={`/api/templates/${kind}?format=csv`}>CSV 양식 다운로드</a><a href={`/api/templates/${kind}?format=xlsx`}>Excel 양식 다운로드</a></p>
      <p className="fine">ID는 텍스트로 입력하세요. 설문은 등록된 참가자의 현재 촬영 세션에 연결됩니다. 기존 원본 가로 양식은 표준 열로 옮겨 입력하세요.</p>
      {kind === 'survey' && <p className="fine">survey_version 열에 입력할 값: <strong className="mono">{catalogVersion}</strong></p>}
      <form onSubmit={e => { e.preventDefault(); if (!file) return; void run(async () => {
        const format = file.name.toLowerCase().endsWith('.xlsx') ? 'xlsx' : 'csv'; setResult(null);
        setResult(await api<Preview>(`/imports/preview?kind=${kind}&format=${format}`, 'POST', file));
      }); }}><label>입력 파일<input type="file" accept=".csv,.xlsx" required onChange={e => { setFile(e.target.files?.[0] ?? null); setResult(null); }} /></label><button>검증 미리보기</button></form>
    </div>
    {result && <div className="panel"><h2>검증 결과 · 정상 {result.rows.length}행 / 오류 {result.errors.length}행</h2>
      {result.errors.map((error, i) => <p className="error" key={i}>{error}</p>)}
      <ul>{result.rows.map(row => <li key={row.row_number}>{row.row_number}행 · {row.event_id} / {row.participant_id} · {row.participant ? row.participant.dog_name : `설문 원응답 ${Object.values(row.survey!.answers).filter(v => v !== null).length}/30`}
        {row.survey && <details><summary>원응답 확인</summary><p className="fine mono">{Object.entries(row.survey.answers).map(([q, answer]) => `${q}: ${answer ?? '미응답'}`).join(' · ')}</p></details>}</li>)}</ul>
      <button className="primary" disabled={!result.rows.length} onClick={() => void run(async () => {
        const saved = await api<{ message: string }>('/imports/commit', 'POST', { rows: result.rows }); setResult(null); await done(saved.message);
      })}>정상 {result.rows.length}행 저장</button><p className="fine">오류 행은 저장되지 않습니다. 미리보기 이후 자료가 변경되면 새로 검증해야 합니다.</p></div>}
  </section>;
}

function Users({ run }: { run: Run }) {
  const [users, setUsers] = useState<User[]>([]);
  const refresh = async () => setUsers(await api<User[]>('/admin/users'));
  useEffect(() => { void run(refresh); }, []);
  return <section><p className="eyebrow">STAFF ACCESS</p><h1>직원 계정</h1><p className="muted">역할 변경·비활성화 시 해당 계정의 로그인 세션이 만료됩니다.</p>
    <div className="panel">{users.map(user => <form className="toolbar user-row" key={user.username} onSubmit={e => { e.preventDefault(); const value = fields(e); void run(async () => {
      await api(`/admin/users/${user.username}`, 'PATCH', { role: value.role, active: value.active === 'on' }); await refresh();
    }); }}><strong>{user.username}</strong><label>역할<select name="role" defaultValue={user.role}>{(['operator', 'reviewer', 'admin'] as const).map(role => <option key={role} value={role}>{roleNames[role]}</option>)}</select></label>
      <label className="check"><input name="active" type="checkbox" defaultChecked={user.active} />활성</label><button>계정 변경 저장</button></form>)}</div>
    <details className="panel"><summary>직원 계정 추가</summary><form onSubmit={e => { e.preventDefault(); const value = fields(e); const form = e.currentTarget; void run(async () => {
      await api('/admin/users', 'POST', value); form.reset(); await refresh();
    }); }}><div className="form-grid"><label>새 계정<input name="username" pattern="[A-Za-z0-9_-]+" required /></label><label>초기 비밀번호<input type="password" name="password" minLength={12} maxLength={256} autoComplete="new-password" required /></label>
      <label>새 계정 역할<select name="role"><option value="operator">운영자</option><option value="reviewer">교수 / 검토자</option><option value="admin">운영 관리자</option></select></label></div><button className="primary">계정 생성</button></form></details>
  </section>;
}

createRoot(document.getElementById('root')!).render(<App />);
