import { Notification } from './Notification';
import { useEffect, useState } from 'react';
import { api } from './api';

type Keys = { keys: { provider: string; available: boolean; reference: string }[] };

// 개발자 화면은 공급자 키 관리만 남긴다. 55항목 단계의 프롬프트·파이프라인 편집기는 PR-10에서 제거했고, 채점 단계 설정은 P2에서 다시 정한다.
export function DeveloperSettings() {
  const [data, setData] = useState<Keys | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [provider, setProvider] = useState('gemini');
  const reload = async () => setData(await api<Keys>('/developer/settings'));
  useEffect(() => { void reload().catch(e => setError(e.message)); }, []);
  async function work(action: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : '작업에 실패했습니다.'); }
    finally { setBusy(false); }
  }
  return <section className="panel developer-settings"><h2>공급자 키 관리</h2>
    <p className="fine">Windows 실행 계정의 DPAPI로 보호합니다. 등록 후 원문은 조회할 수 없습니다. 폐기하면 환경 변수 키로 자동 복귀하지 않습니다. 채점 단계의 모델·프롬프트 설정은 42항목 채점 파이프라인과 함께 제공됩니다.</p>
    <Notification message={error} kind="error" onClose={() => setError('')} /><Notification message={message} onClose={() => setMessage('')} />
    {data && <fieldset disabled={busy}>
      <ul>{data.keys.map(k => <li key={k.provider}>{k.provider} · {k.available ? '등록됨' : '개발자 설정 필요'}</li>)}</ul>
      <form onSubmit={e => { e.preventDefault(); const form = e.currentTarget;
        const value = String(new FormData(form).get('secret') || ''); form.reset();
        void work(async () => { await api(`/developer/keys/${provider}`, 'PUT', { value }); await reload(); setMessage('키를 보호하여 저장했습니다.'); });
      }}><label>키 공급자<select value={provider} onChange={e => setProvider(e.target.value)}><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></label>
        <label>새 API 키<input type="password" name="secret" autoComplete="off" minLength={8} maxLength={512} required /></label>
        <div className="toolbar"><button type="submit">키 등록·교체</button><button type="button" onClick={() => void work(async () => {
          const result = await api<{ status: string }>(`/developer/keys/${provider}/test`, 'POST'); setMessage(`연결 시험: ${result.status}`);
        })}>키 연결 시험</button><button type="button" onClick={() => void work(async () => {
          await api(`/developer/keys/${provider}`, 'DELETE'); await reload(); setMessage('키를 폐기했습니다.');
        })}>선택 공급자 키 폐기</button></div>
      </form>
    </fieldset>}
  </section>;
}

export function Recovery() {
  const [status, setStatus] = useState<{ message: string; free_bytes: number; deletion_requests: number; runs: Record<string, number>; last_backup: { path: string } | null } | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api<typeof status>('/admin/recovery').then(setStatus).catch(e => setError(e.message)); }, []);
  return <details className="panel"><summary>자료 백업·복구</summary>
    {status && <><p>{status.message}</p><p>남은 공간 {(status.free_bytes / 1024 ** 3).toFixed(1)} GB · 삭제 요청 {status.deletion_requests}건</p>
      <p className="fine">최근 백업: {status.last_backup?.path ?? '없음'}</p></>}
    <button disabled={busy} onClick={() => { setBusy(true); setMessage(''); setError(''); void api<{ path: string }>('/admin/backups', 'POST')
      .then(v => setMessage(`검증된 백업 저장 완료: ${v.path}`)).catch(e => setError(e.message)).finally(() => setBusy(false)); }}>{busy ? '파일 검증·백업 중…' : '자료 백업 생성 · 키 제외'}</button>
    <Notification message={error} kind="error" onClose={() => setError('')} />
    <Notification message={message} onClose={() => setMessage('')} />
  </details>;
}
