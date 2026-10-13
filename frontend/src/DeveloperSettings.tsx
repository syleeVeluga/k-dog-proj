import { Notification } from './Notification';
import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { AiSettingsV4 } from './AiSettingsV4';

type Slot = 'primary' | 'backup';
type KeyTest = { slot: Slot; reference: string; status: string; tested_at: string };
type KeySlot = { slot: Slot; reference: string | null; source: 'vault' | 'environment' | 'none'; available: boolean; unavailable_reason: string | null; last_test: KeyTest | null };
type Keys = { keys: { provider: string; available: boolean; reference: string }[]; gemini_slots: KeySlot[] };
const slotNames: Record<Slot, string> = { primary: 'Gemini 주키', backup: 'Gemini 예비키' };
const localReasons: Record<string, string> = { unregistered: '미등록', removed: '앱에서 제거됨', file_unavailable: '키 파일 없음 · 재등록 필요', decrypt_failed: '실행 계정의 키 복호화 확인 필요', restore_required: '복원 후 재등록 필요' };
const testStatus = (status: string) => status === 'connected' ? '연결 확인' : status === 'developer_settings_required' ? '개발자 설정 필요' : '연결 실패 · 키와 공급자 상태를 확인하세요';

export function DeveloperSettings() {
  const [data, setData] = useState<Keys | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [provider, setProvider] = useState('gemini');
  const generation = useRef(0);
  const reload = async () => {
    const request = ++generation.current;
    const value = await api<Keys>('/developer/settings');
    if (request === generation.current) setData(value);
    return value;
  };
  useEffect(() => { void reload().catch(e => setError(e.message)); return () => { generation.current++; }; }, []);
  async function work(action: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (e) {
      setError(e instanceof Error ? e.message : '작업에 실패했습니다.');
      if (e instanceof ApiError && e.status === 409) {
        try { await reload(); setError('키 상태가 변경되었습니다. 최신 상태를 확인한 뒤 키를 다시 입력하세요.'); }
        catch { setError('최신 키 상태를 조회하지 못했습니다. 화면을 다시 열고 키를 다시 입력하세요.'); }
      }
    }
    finally { setBusy(false); }
  }
  return <><section className="panel developer-settings"><h2>공급자 키 관리</h2>
    <p className="fine">Windows 실행 계정의 DPAPI로 보호합니다. 등록 후 원문은 조회할 수 없습니다. 폐기하면 환경 변수 키로 자동 복귀하지 않습니다. 신판 AI 설정은 아래에서 별도로 저장·활성화합니다.</p>
    <Notification message={error} kind="error" onClose={() => setError('')} /><Notification message={message} onClose={() => setMessage('')} />
    {data && <fieldset disabled={busy}>
      <label>키 공급자<select value={provider} onChange={e => setProvider(e.target.value)}><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></label>
      {provider === 'gemini' ? <>
        <p className="fine">주키 문제 시 등록한 예비키를 자동 사용합니다. 같은 프로젝트의 두 키는 프로젝트 할당량을 공유합니다.</p>
        <div className="form-grid">{data.gemini_slots.map(key => <section className="panel" key={key.slot} aria-label={slotNames[key.slot]}>
          <h3>{slotNames[key.slot]}</h3>
          {key.slot === 'backup' && <p>주키 문제 시 자동 사용</p>}
          <p>{key.available ? key.source === 'environment' ? '실행 환경의 주키' : '앱에 등록됨' : localReasons[key.unavailable_reason ?? ''] ?? '개발자 설정 필요'}</p>
          <p>마지막 연결 시험: {key.last_test ? `${testStatus(key.last_test.status)} · ${new Date(key.last_test.tested_at).toLocaleString()}` : '현재 키의 시험 기록 없음'}</p>
          <form onSubmit={e => {
            e.preventDefault(); const form = e.currentTarget;
            const value = String(new FormData(form).get('secret') || ''); form.reset();
            void work(async () => {
              await api(`/developer/keys/gemini/slots/${key.slot}`, 'PUT', { value, expected_reference: key.reference });
              await reload(); setMessage(`${slotNames[key.slot]}를 보호하여 저장했습니다.`);
            });
          }}><label>{slotNames[key.slot]} API 키<input type="password" name="secret" autoComplete="off" minLength={8} maxLength={512} required /></label>
            <div className="toolbar"><button type="submit">{key.slot === 'primary' ? '주키' : '예비키'} 등록·교체</button>
              <button type="button" onClick={() => void work(async () => {
                const result = await api<KeyTest>(`/developer/keys/gemini/slots/${key.slot}/test`, 'POST');
                const fresh = await reload();
                const latest = fresh.gemini_slots.find(value => value.slot === key.slot);
                const current = latest && (latest.reference === result.reference || latest.reference === null && result.reference === 'unavailable');
                setMessage(current
                  ? `${slotNames[key.slot]} 연결 시험: ${testStatus(result.status)}`
                  : `${slotNames[key.slot]}의 교체 전 키 시험 결과입니다. 현재 키를 다시 시험하세요.`);
              })}>{key.slot === 'primary' ? '주키' : '예비키'} 연결 시험</button>
              <button type="button" onClick={() => void work(async () => {
                await api(`/developer/keys/gemini/slots/${key.slot}`, 'DELETE', { expected_reference: key.reference });
                await reload(); setMessage(`${slotNames[key.slot]}를 앱에서 제거했습니다.`);
              })}>{key.slot === 'primary' ? '주키' : '예비키'}를 앱에서 제거</button>
            </div>
          </form>
        </section>)}</div>
        <p className="fine">주키만 제거해도 예비키가 남으면 사용할 수 있습니다. 전체 사용 중지는 다음 시도부터 두 키를 모두 막습니다. 진행 중인 실행 중지와 공급자 콘솔의 키 취소는 별도입니다. 복원 후 두 슬롯을 다시 등록하세요.</p>
        <p className="fine">연결 시험은 선택 키의 모델 목록 조회입니다. 실제 평가 품질은 별도로 확인합니다.</p>
        <button type="button" onClick={() => void work(async () => { await api('/developer/keys/gemini', 'DELETE'); await reload(); setMessage('Gemini 전체 키 사용을 중지했습니다.'); })}>Gemini 전체 키 사용 중지</button>
      </> : <>
      <ul>{data.keys.filter(key => key.provider !== 'gemini').map(k => <li key={k.provider}>{k.provider} · {k.available ? '등록됨' : '개발자 설정 필요'}</li>)}</ul>
      <form key={provider} onSubmit={e => { e.preventDefault(); const form = e.currentTarget;
        const value = String(new FormData(form).get('secret') || ''); form.reset();
        void work(async () => { await api(`/developer/keys/${provider}`, 'PUT', { value }); await reload(); setMessage('키를 보호하여 저장했습니다.'); });
      }}>
        <label>새 API 키<input type="password" name="secret" autoComplete="off" minLength={8} maxLength={512} required /></label>
        <div className="toolbar"><button type="submit">키 등록·교체</button><button type="button" onClick={() => void work(async () => {
          const result = await api<{ status: string }>(`/developer/keys/${provider}/test`, 'POST'); setMessage(`연결 시험: ${result.status}`);
        })}>키 연결 시험</button><button type="button" onClick={() => void work(async () => {
          await api(`/developer/keys/${provider}`, 'DELETE'); await reload(); setMessage('키를 폐기했습니다.');
        })}>선택 공급자 키 폐기</button></div>
      </form>
      </>}
    </fieldset>}
  </section><AiSettingsV4 /></>;
}

export function Recovery() {
  const [status, setStatus] = useState<{ message: string; free_bytes: number; runs: Record<string, number>; last_backup: { path: string } | null } | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api<typeof status>('/admin/recovery').then(setStatus).catch(e => setError(e.message)); }, []);
  return <details className="panel"><summary>자료 백업·복구</summary>
    {status && <><p>남은 공간 {(status.free_bytes / 1024 ** 3).toFixed(1)} GB</p>
      <p className="fine">최근 백업: {status.last_backup?.path ?? '없음'}</p>
      <p className="fine">{status.message}</p></>}
    <button disabled={busy} onClick={() => { setBusy(true); setMessage(''); setError(''); void api<{ path: string }>('/admin/backups', 'POST')
      .then(v => setMessage(`검증된 백업 저장 완료: ${v.path}`)).catch(e => setError(e.message)).finally(() => setBusy(false)); }}>{busy ? '파일 검증·백업 중…' : '자료 백업 생성 · 키 제외'}</button>
    <Notification message={error} kind="error" onClose={() => setError('')} />
    <Notification message={message} onClose={() => setMessage('')} />
  </details>;
}
