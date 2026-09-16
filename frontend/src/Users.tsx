import { useEffect, useState } from 'react';
import { api } from './api';
import { formFields, roleNames } from './types';
import type { Run, User } from './types';

export function Users({ run }: { run: Run }) {
  const [users, setUsers] = useState<User[]>([]);
  const refresh = async () => setUsers(await api<User[]>('/admin/users'));
  useEffect(() => { void run(refresh); }, []);
  return <section><p className="eyebrow">STAFF ACCESS</p><h1>직원 계정</h1><p className="muted">역할 변경·비활성화 시 해당 계정의 로그인 세션이 만료됩니다.</p>
    <p className="fine">운영자는 접수·설문 가져오기·촬영 자료를 저장합니다. 교수/검토자는 참가자와 촬영 회차를 읽기만 합니다. 운영 관리자는 직원 계정과 자료 백업도 관리합니다.</p>
    <div className="panel">{users.map(user => <form className="toolbar user-row" key={user.username} onSubmit={e => { e.preventDefault(); const value = formFields(e.currentTarget); void run(async () => {
      await api(`/admin/users/${user.username}`, 'PATCH', { role: value.role, active: value.active === 'on' }); await refresh();
    }); }}><strong>{user.username}</strong><label>역할<select name="role" defaultValue={user.role}>{(['operator', 'reviewer', 'admin'] as const).map(role => <option key={role} value={role}>{roleNames[role]}</option>)}</select></label>
      <label className="check"><input name="active" type="checkbox" defaultChecked={user.active} />활성</label><button>계정 변경 저장</button></form>)}</div>
    <details className="panel"><summary>직원 계정 추가</summary><form onSubmit={e => { e.preventDefault(); const form = e.currentTarget; const value = formFields(form); void run(async () => {
      await api('/admin/users', 'POST', value); form.reset(); await refresh();
    }); }}><div className="form-grid"><label>새 계정<input name="username" pattern="[A-Za-z0-9_\-]+" required /></label><label>초기 비밀번호<input type="password" name="password" minLength={12} maxLength={256} autoComplete="new-password" required /></label>
      <label>새 계정 역할<select name="role"><option value="operator">운영자</option><option value="reviewer">교수 / 검토자</option><option value="admin">운영 관리자</option></select></label></div><button className="primary">계정 생성</button></form></details>
  </section>;
}
