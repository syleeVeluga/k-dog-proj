import { useEffect, useRef, useState } from 'react';
import { accessLost, api } from './api';
import { useUnsaved } from './Editing';
import { ExternalComparisonSettingsV4 } from './ExternalComparisonSettingsV4';
import type { User } from './types';
import type { CohortCandidateV4, CohortSelectionV4, CohortSummaryV4, CohortViewV4, ComparisonSourcesV4 } from './comparisonTypesV4';

const exclusions: Record<string, string> = { insufficient_responses: '유효 응답 부족', policy_pending: '부분 평균 정책 미정', unanswered: '미응답', missing: '자료 없음', not_applicable: '해당 없음' };
const number = (value: number | null) => value === null ? '평균 없음' : value.toLocaleString(undefined, { maximumFractionDigits: 3 });
const message = (value: unknown) => value instanceof Error ? value.message : '집단 비교 자료를 확인하지 못했습니다.';

export function ComparisonSettings({ user, onSaved }: { user: User; onSaved?: () => void }) {
  const [candidates, setCandidates] = useState<CohortCandidateV4[]>([]), [history, setHistory] = useState<CohortSummaryV4[]>([]), [sources, setSources] = useState<ComparisonSourcesV4 | null>(null);
  const [title, setTitle] = useState(''), [reason, setReason] = useState(''), [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Record<string, CohortSelectionV4>>({}), [view, setView] = useState<CohortViewV4 | null>(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const alive = useRef(true), sequence = useRef(0), working = useRef(false), opened = useRef('');
  const request = useRef<{ fingerprint: string; request_id: string } | null>(null);
  const dirty = !!title || !!reason || Object.keys(selected).length > 0;
  useUnsaved(dirty);
  function clearView() { opened.current = ''; setView(null); }
  async function reload() {
    const current = ++sequence.current;
    const [available, list, external] = await Promise.all([api<CohortCandidateV4[]>('/comparisons-s1/candidates'), api<CohortSummaryV4[]>('/comparisons-s1/cohorts'), api<ComparisonSourcesV4>('/comparisons-s1/sources')]);
    if (!alive.current || current !== sequence.current) return;
    setCandidates(available); setHistory(list); setSources(external);
    if (opened.current) {
      const id = opened.current;
      const value = await api<CohortViewV4>('/comparisons-s1/cohorts/' + id);
      if (alive.current && current === sequence.current && opened.current === id) setView(value);
    }
  }
  async function work(operation: () => Promise<void>) {
    if (working.current) return;
    working.current = true; setBusy(true); setError('');
    try { await operation(); }
    catch (value) { if (alive.current) { setError(message(value)); clearView(); if (accessLost(value)) { setCandidates([]); setHistory([]); setSources(null); } } }
    finally { working.current = false; if (alive.current) setBusy(false); }
  }
  useEffect(() => { alive.current = true; void work(reload); return () => { alive.current = false; sequence.current++; }; }, []);
  function choose(candidate: CohortCandidateV4, session: string | null) {
    setSelected(previous => {
      const next = { ...previous };
      if (session === null) delete next[candidate.case_id];
      else next[candidate.case_id] = { case_id: candidate.case_id, session_id: session, expected_revision: candidate.input_revision, input: candidate.input };
      return next;
    });
  }
  async function save() {
    const fields = { title: title.trim(), reason: reason.trim(), members: Object.values(selected).sort((a, b) => a.case_id.localeCompare(b.case_id)) };
    const fingerprint = JSON.stringify(fields);
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, request_id: crypto.randomUUID() };
    const value = await api<CohortViewV4>('/comparisons-s1/cohorts', 'POST', { ...fields, request_id: request.current.request_id });
    if (!alive.current) return;
    opened.current = value.reference.snapshot_id; setView(value); setSelected({}); setTitle(''); setReason(''); request.current = null;
    await reload(); onSaved?.();
  }
  if (!['operator', 'admin'].includes(user.role)) return <p role="status">집단 비교는 운영 권한으로 확인합니다.</p>;
  return <section className="panel" aria-label="S1 자체 집단 비교" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>같은 판본의 자체 비교집단</h2><p>분석 동의가 확인된 실제 설문을 선택합니다. 한 대상은 명시한 한 회차만 포함하며, 영역별 유효 평균과 표본수를 따로 계산합니다.</p>
    <p className="fine">카메라 수는 표본수가 아닙니다. 행사 간 같은 개체를 확인할 전역 ID가 없어 이름으로 합치지 않습니다. 이 집단을 전국 규준·백분위·정상 경계로 해석하지 않습니다.</p>
    {error && <p role="alert" className="error">{error}</p>}
    <button disabled={busy} onClick={() => void work(reload)}>비교 후보·이력 새로고침</button>
    <fieldset disabled={busy}><legend>새 집단의 대상과 회차 고정</legend>
      <label>집단 이름<input aria-label="집단 이름" value={title} onChange={event => setTitle(event.target.value)} maxLength={200} /></label>
      <label>집단 선택 사유<textarea aria-label="집단 선택 사유" value={reason} onChange={event => setReason(event.target.value)} maxLength={4000} /></label>
      <label>집단 후보 검색<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="행사, 참가자 ID, 반려견" /></label>
      <div className="table-wrap"><table><thead><tr><th>포함</th><th>대상</th><th>명시 회차와 판본</th></tr></thead><tbody>{candidates.filter(value => `${value.event_id} ${value.participant_id} ${value.dog_name}`.toLowerCase().includes(search.toLowerCase())).map(candidate => {
        const value = selected[candidate.case_id], changed = value && (value.expected_revision !== candidate.input_revision || value.input.manifest_hash !== candidate.input.manifest_hash);
        return <tr key={candidate.case_id}><td><input type="checkbox" aria-label={`${candidate.participant_id} 집단 포함`} checked={!!value} onChange={event => choose(candidate, event.target.checked ? candidate.sessions.length === 1 ? candidate.sessions[0].session_id : '' : null)} /></td>
          <td>{candidate.event_id} / {candidate.participant_id}<br />{candidate.dog_name}</td><td><select aria-label={`${candidate.participant_id} 집단 회차`} value={value?.session_id ?? ''} disabled={!value} onChange={event => choose(candidate, event.target.value)}><option value="">회차를 명시적으로 선택하세요</option>{candidate.sessions.map((session, index) => <option key={session.session_id} value={session.session_id}>{index + 1}회차 · {session.note || session.session_id.slice(0, 8)}</option>)}</select><p>선택 입력 {value?.expected_revision ?? candidate.input_revision}판 · S1 설문 원문</p>{changed && <><p role="status">선택 후 입력이 변경됐습니다. 기존 선택 판본은 자동 교체하지 않습니다.</p><button onClick={() => choose(candidate, candidate.sessions.some(session => session.session_id === value.session_id) ? value.session_id : '')}>이 대상 선택을 최신 판본으로 교체</button></>}</td></tr>;
      })}</tbody></table></div>
      {!candidates.length && <p>동의와 같은 원문 판본이 확인된 선택 후보가 없습니다.</p>}
      {Object.values(selected).filter(value => !candidates.some(candidate => candidate.case_id === value.case_id)).map(value => <p key={value.case_id}>현재 조회할 수 없는 선택 대상 {value.case_id}<button onClick={() => setSelected(previous => { const next = { ...previous }; delete next[value.case_id]; return next; })}>이 선택 제거</button></p>)}
      <p>선택 {Object.keys(selected).length}대상 · 저장 시 각 입력 해시를 다시 검증합니다.</p>
      <button disabled={!title.trim() || !reason.trim() || !Object.keys(selected).length || Object.values(selected).some(value => !value.session_id)} onClick={() => void work(save)}>선택 응답으로 새 집단 고정</button>
      {request.current && <p role="status">응답 확인이 필요한 요청입니다. 같은 선택으로 다시 저장하면 동일 요청 ID를 사용합니다.</p>}
      {dirty && <button onClick={() => { if (window.confirm('입력한 집단 이름·사유·선택을 버릴까요?')) { setTitle(''); setReason(''); setSelected({}); request.current = null; } }}>집단 입력 버리기</button>}
    </fieldset>
    <h3>보존 비교집단</h3><ul>{history.map(row => <li key={row.reference.snapshot_id}>{row.title} · 선택 {row.selection_count}대상{row.outdated && ' · 일부 입력이 이후 변경됨'} <button disabled={busy} onClick={() => void work(async () => { clearView(); const value = await api<CohortViewV4>('/comparisons-s1/cohorts/' + row.reference.snapshot_id); if (alive.current) { opened.current = row.reference.snapshot_id; setView(value); } })}>집단 {row.title} 열기</button></li>)}</ul>
    {view && <section aria-label="고정 집단 상세"><h3>{view.document.title}</h3><p>{view.document.reason} · {view.document.actor} · {new Date(view.document.recorded_at).toLocaleString()}</p><p>{view.document.identity_limitation}</p>
      {!!view.outdated_member_case_ids.length && <p>고정 이후 입력이 변경된 대상 {view.outdated_member_case_ids.length}개입니다. 이전 평균은 보존하며 다시 선택·저장하면 새 집단이 생성됩니다.</p>}
      <div className="table-wrap"><table><thead><tr><th>영역 · 원척도</th><th>평균 · 유효 n</th><th>포함·제외</th></tr></thead><tbody>{view.document.domains.map(domain => <tr key={domain.domain}><td>{domain.domain}<br />{domain.scale_minimum}~{domain.scale_maximum}</td><td>{number(domain.mean)} · n={domain.n}</td><td>포함 {domain.included_case_ids.length} / 제외 {Object.keys(domain.excluded).length}<details><summary>개별 포함·제외 근거</summary>{domain.included_case_ids.map(id => <p key={id}>{id}: 포함</p>)}{Object.entries(domain.excluded).map(([id, why]) => <p key={id}>{id}: {exclusions[why] ?? why}</p>)}</details></td></tr>)}</tbody></table></div>
      <details><summary>고정 입력과 출처</summary><p>{view.document.survey_version} · {view.document.survey_policy}</p><p>집단 {view.reference.snapshot_id} · {view.reference.hash}</p>{view.document.members.map(member => <p key={member.case_id}>{member.case_id} / {member.session_id} · 입력 {member.input_revision}판 · {member.input.manifest_hash}</p>)}</details>
    </section>}
    <h3>외부 비교 D06 · 출처별 확인 상태</h3><p>연구자의 문항 동등성·사용 조건 확인과 관리자의 기술 활성화는 별개입니다. 미승인 참고 수치는 리포트에 표시하지 않습니다.</p>
    {sources?.sources.map(source => <article key={source.source_id}><h4>{source.title}</h4><p>{source.reason}</p></article>)}{sources && <p>{sources.domestic_reason}</p>}
    <p className="fine">실제 외부 비교 활성화는 S17 문헌·연구 확인 자료가 갖춰진 뒤 진행합니다. 자체 집단을 넣지 않아도 정상 리포트를 생성할 수 있습니다.</p>
    <details><summary>외부 비교 연구 확인·활성화 관리</summary><ExternalComparisonSettingsV4 user={user} onChanged={() => { void work(reload); onSaved?.(); }} /></details>
  </section>;
}
