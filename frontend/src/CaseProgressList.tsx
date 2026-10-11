import { useState } from 'react';
import { CaseFilters, matchesCase } from './CaseFilters';
import type { CaseFilterProps } from './CaseFilters';
import { currentProgress, isMine, nextAction, ownerText, stageNames, stepsOf } from './progressText';
import type { Case, User } from './types';

// 전처리·독립 채점·리포트가 함께 쓰는 참가자 목록. 참가자별로 어느 단계까지 왔는지와 다음 할 일을 보여 준다.
// 원평가자 출처와 공통 진행 단계를 표시한다.
export function CaseProgressList({ cases, user, filters, open, openLabel }: {
  cases: Case[]; user: User; filters: CaseFilterProps; open: (item: Case) => void; openLabel: (item: Case) => string;
}) {
  const [stage, setStage] = useState('');
  const [mine, setMine] = useState(false);
  const visible = cases.filter(item => matchesCase(item, filters.search, filters.eventFilter)
    && (!stage || currentProgress(item)?.stage === stage) && (!mine || isMine(item, user.role)))
    .sort((a, b) => (a.sequence_no ?? 1e9) - (b.sequence_no ?? 1e9) || a.participant_id.localeCompare(b.participant_id));
  const stageOptions = ['recording', 'preprocess', 'scoring', 'final', 'report', 'complete'];
  return <>
    <CaseFilters cases={cases} {...filters} />
    <div className="toolbar">
      <label>진행 단계<select aria-label="진행 단계 필터" value={stage} onChange={event => setStage(event.target.value)}><option value="">전체</option>
        {stageOptions.map(value => <option key={value} value={value}>{stageNames[value]}</option>)}</select></label>
      <label className="check"><input type="checkbox" checked={mine} onChange={event => setMine(event.target.checked)} />미완료만</label>
    </div>
    <div className="table-wrap"><table className="progress-table"><thead><tr><th>순번</th><th>참가자 / 반려견</th><th>진행 단계</th><th>다음 할 일</th><th>원평가자</th><th>작업</th></tr></thead>
      <tbody>{visible.map(item => { const progress = currentProgress(item), steps = progress ? stepsOf(progress, user.role) : [];
        return <tr key={item.case_id}>
          <td data-label="순번"><strong className="mono">{item.sequence_no ?? '—'}</strong></td>
          <td data-label="참가자 / 반려견"><strong className="mono">{item.participant_id}</strong><small>{item.event_id}</small>{item.dog_name}</td>
          <td data-label="진행 단계"><ol className="steps" aria-label={`${item.participant_id} 진행 단계`}>{steps.map(step => <li key={step.key} className={`step ${step.state}`}
            aria-current={step.state === 'current' ? 'step' : undefined}><span className="dot" aria-hidden="true" /><span className="step-label">{step.label}</span><span className="sr-only">{step.state === 'done' ? ' 완료' : step.state === 'current' ? ' 진행 중' : ' 대기'}</span></li>)}</ol></td>
          <td data-label="다음 할 일">{nextAction(item, user.role)}</td>
          <td data-label="원평가자">{ownerText(item, user.role)}</td>
          <td data-label="작업"><button onClick={() => open(item)} aria-label={openLabel(item)}>열기</button></td></tr>; })}</tbody></table>
      {!visible.length && <div className="empty"><h2>{cases.length ? '조건에 맞는 참가자가 없습니다.' : '등록된 참가자가 없습니다.'}</h2><p>검색·행사·진행 단계 조건을 확인하세요.</p></div>}</div>
  </>;
}
