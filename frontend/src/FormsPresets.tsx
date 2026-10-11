import { useEffect, useState } from 'react';
import { api } from './api';

export type PresetMapping = { columns: Record<string, string>; answer_labels: Record<string, Record<string, number>>; layout: string; source_profile: string; version: string };
export type Preset = { preset_id: string; name: string; mapping: PresetMapping; created_by: string; created_at: string; can_delete: boolean };

// 열 연결 설정 저장·불러오기. 서버에 저장되어 같은 현장의 다른 PC에서도 보인다.
export function FormsPresets({ current, canSave, apply, run, disabled }: {
  current: () => PresetMapping; canSave: boolean; apply: (preset: Preset) => string;
  run: (work: () => Promise<void>) => Promise<void>; disabled: boolean;
}) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [message, setMessage] = useState('');
  const chosen = presets.find(item => item.preset_id === selected);
  async function refresh() { setPresets(await api<Preset[]>('/forms/presets')); }
  useEffect(() => { void refresh().catch(() => setPresets([])); }, []);
  const saveBlock = !name.trim() ? '저장할 설정 이름을 입력하세요.' : !canSave ? '연결된 열이 없습니다.' : '';
  return <details><summary>열 연결 설정 저장·불러오기 ({presets.length})</summary>
    <p className="fine">자주 쓰는 파일 형식의 열 연결을 이름을 붙여 저장해 두면 다음 파일에서 불러올 수 있습니다. 같은 현장의 다른 PC에서도 보입니다. 파일에 없는 열은 「연결 안 됨」으로 남습니다.</p>
    <fieldset disabled={disabled}>
      <div className="form-grid">
        <label>저장된 열 연결 설정<select aria-label="저장된 열 연결 설정" value={selected} onChange={e => { setSelected(e.target.value); setMessage(''); }}>
          <option value="">설정 선택</option>{presets.map(item => <option key={item.preset_id} value={item.preset_id}>{item.name} · {item.created_by}</option>)}</select></label>
        <label>새 설정 이름<input aria-label="열 연결 설정 이름" value={name} maxLength={60} placeholder="예: 2026 가을 신청폼" onChange={e => setName(e.target.value)} /></label>
      </div>
      <div className="toolbar">
        <button disabled={!chosen} onClick={() => chosen && setMessage(apply(chosen))}>선택한 설정 불러오기</button>
        <button disabled={!chosen?.can_delete} onClick={() => void run(async () => {
          if (!chosen || !window.confirm(`‘${chosen.name}’ 열 연결 설정을 삭제할까요?`)) return;
          await api(`/forms/presets/${chosen.preset_id}`, 'DELETE'); setSelected(''); setMessage('삭제했습니다.'); await refresh();
        })}>선택한 설정 삭제</button>
        <button disabled={!!saveBlock} onClick={() => void run(async () => {
          const saved = await api<Preset>('/forms/presets', 'POST', { name: name.trim(), mapping: current() });
          setName(''); setSelected(saved.preset_id); setMessage(`‘${saved.name}’ 설정을 저장했습니다.`); await refresh();
        })}>현재 연결 저장</button>
        <span className="fine" aria-live="polite">{saveBlock}</span>
      </div>
      {message && <p className="fine" role="status">{message}</p>}
    </fieldset>
  </details>;
}
