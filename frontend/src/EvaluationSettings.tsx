import { Notification } from './Notification';
import { useEffect, useState } from 'react';
import { api } from './api';

type Settings = { version: string; branches: Record<'dog' | 'owner', { provider: string; model: string }>; key_available: Record<string, boolean> };

export function EvaluationSettings() {
  const [data, setData] = useState<Settings | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; void api<Settings>('/developer/evaluation').then(value => { if (active) setData(value); })
    .catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  return <section className="panel"><h2>분기별 평가 공급자</h2>
    <p className="fine">기본 공급자는 Gemini입니다. 선택한 공급자의 구조화 출력을 지원하는 모델 ID를 입력하세요. 적용한 설정은 새 실행부터 사용합니다.</p>
    <Notification message={error} kind="error" onClose={() => setError('')} /><Notification message={message} onClose={() => setMessage('')} />
    {data && <form onSubmit={e => { e.preventDefault(); setBusy(true); setMessage(''); setError('');
      void api<Settings>('/developer/evaluation', 'PUT', { expected_version: data.version, branches: data.branches }).then(result => {
        setData(result); setMessage('새 실행에 적용했습니다. 기존 실행 설정은 보존됩니다.');
      }).catch(e => setError(e.message)).finally(() => setBusy(false));
    }}><fieldset disabled={busy}>{(['dog', 'owner'] as const).map(branch => <div className="form-grid" key={branch}>
      <label>{branch === 'dog' ? '반려견' : '보호자'} 평가 공급자<select aria-label={`${branch === 'dog' ? '반려견' : '보호자'} 평가 공급자`} value={data.branches[branch].provider} onChange={e => setData({ ...data, branches: {
        ...data.branches, [branch]: { provider: e.target.value, model: '' } } })}>
        <option value="gemini">Gemini</option><option value="openai">GPT · OpenAI</option><option value="anthropic">Claude · Anthropic</option>
        {!['gemini', 'openai', 'anthropic'].includes(data.branches[branch].provider) &&
          <option value={data.branches[branch].provider}>설정 오류 · {data.branches[branch].provider}</option>}
      </select></label>
      <label>{branch === 'dog' ? '반려견' : '보호자'} 평가 모델<input value={data.branches[branch].model} maxLength={150} required
        pattern="[a-zA-Z0-9][a-zA-Z0-9._\-]*" onChange={e => setData({ ...data, branches: { ...data.branches, [branch]: { ...data.branches[branch], model: e.target.value } } })} /></label>
    </div>)}<button className="primary">새 실행에 평가 설정 적용</button></fieldset></form>}
    <p className="fine">버전 편집 시작 전의 빠른 설정입니다. 키는 위의 공급자 키 관리에서 등록합니다. 실제 모델 접근과 연결은 샘플 시험으로 확인하며 다른 공급자로 자동 전환하지 않습니다.</p>
  </section>;
}
