import { useEffect, useState } from 'react';
import { api } from './api';
import { CaseFilters, matchesCase } from './CaseFilters';
import type { CaseFilterProps } from './CaseFilters';
import type { Route } from './navigation';
import type { Case } from './types';
import type { PreprocessStatusV4 } from './preprocessTypesV4';

type Check = { status?: PreprocessStatusV4; error?: string };
const identity = (item: Case) => `${item.case_id}:${item.selected_session_id}:${item.input_revision}`;

export function AnalysisTargets({ cases, filters, open }: {
  cases: Case[]; filters: CaseFilterProps; open: (item: Case, route: Route) => void;
}) {
  const [checks, setChecks] = useState<Record<string, Check>>({});
  const [revision, setRevision] = useState(0);
  const visible = cases.filter(item => matchesCase(item, filters.search, filters.eventFilter))
    .sort((a, b) => (a.sequence_no ?? 1e9) - (b.sequence_no ?? 1e9) || a.participant_id.localeCompare(b.participant_id));
  const targets = JSON.stringify(visible.map(item => [item.case_id, item.selected_session_id, item.input_revision, item.progress?.preprocess]));
  useEffect(() => {
    let active = true, cursor = 0;
    const rows = JSON.parse(targets) as [string, string, number, string | null][];
    setChecks({});
    async function load() {
      while (active && cursor < rows.length) {
        const [caseId, sessionId, inputRevision] = rows[cursor++];
        const key = `${caseId}:${sessionId}:${inputRevision}`;
        let check: Check;
        try {
          const status = await api<PreprocessStatusV4>(`/cases/${caseId}/sessions/${sessionId}/preprocess-s1`);
          check = status.input_revision === inputRevision ? { status } : { error: '자료가 변경되었습니다. 준비 상태를 다시 확인하세요.' };
        } catch (error) { check = { error: error instanceof Error ? error.message : '준비 상태를 확인하지 못했습니다.' }; }
        if (active) setChecks(previous => ({ ...previous, [key]: check }));
      }
    }
    for (let worker = 0; worker < Math.min(4, rows.length); worker++) void load();
    return () => { active = false; };
  }, [targets, revision]);
  return <section aria-label="분석 대상 목록">
    <div className="section-title"><h2>분석 대상별 자료 준비</h2><button onClick={() => setRevision(value => value + 1)}>준비 상태 새로고침</button></div>
    <p className="fine">부족한 자료를 보완한 뒤 전처리 설정을 확인하세요. 파일 무결성과 실행 조건은 실행할 때 다시 검사하며, 이 목록에서는 분석을 자동으로 시작하지 않습니다.</p>
    <CaseFilters cases={cases} {...filters} />
    <div className="table-wrap"><table><thead><tr><th>참가자 / 반려견</th><th>현재 회차 준비 상태</th><th>다음 작업</th></tr></thead><tbody>{visible.map(item => {
      const check = checks[identity(item)], status = check?.status;
      const processed = !!status && !status.outdated && ['complete', 'partial'].includes(status.status);
      const label = !check ? '확인 중…' : check.error ? '확인 실패' : status?.outdated ? '입력 변경 · 재전처리 필요'
        : status?.status === 'running' ? '전처리 실행 중' : status?.status === 'failed' ? '전처리 실패 · 확인 필요'
        : status?.status === 'interrupted' ? '전처리 중단 · 확인 필요' : processed ? status?.status === 'partial' ? '일부 영상 전처리 완료' : '전처리 완료'
        : status?.ready ? '촬영 기록 조건 충족' : '자료 보완 필요';
      return <tr key={item.case_id}><td data-label="참가자 / 반려견">{item.participant_id} · {item.dog_name}<small>{item.event_id} · {item.manifest.sessions.findIndex(s => s.session_id === item.selected_session_id) + 1}차 촬영</small></td>
        <td data-label="현재 회차 준비 상태" className="preparation-message"><strong>{label}</strong><small>{check?.error ?? status?.message}</small></td>
        <td data-label="다음 작업"><div className="participant-actions"><button aria-label={`${item.participant_id} 전처리 열기`} onClick={() => open(item, 'preprocess')}>전처리 설정</button>
          {processed ? <button aria-label={`${item.participant_id} 분석 채점 열기`} onClick={() => open(item, 'scoring')}>분석·채점</button> : <><button aria-label={`${item.participant_id} 영상 보완`} onClick={() => open(item, 'recording/inbox')}>영상 등록</button><button aria-label={`${item.participant_id} 촬영 기록 보완`} onClick={() => open(item, 'recording/record')}>촬영 기록</button></>}
        </div></td></tr>;
    })}</tbody></table></div>
    {!visible.length && <p>조건에 맞는 참가자가 없습니다. 검색 조건 또는 참가자 등록을 확인하세요.</p>}
  </section>;
}
