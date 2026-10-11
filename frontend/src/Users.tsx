import { useEffect, useState } from 'react';
import { api } from './api';
import { formFields } from './types';
import type { Run, User } from './types';

export function Users({ run }: { run: Run }) {
  const [users, setUsers] = useState<User[]>([]);
  const refresh = async () => setUsers(await api<User[]>('/admin/users'));
  useEffect(() => { void run(refresh); }, []);
  return <section><p className="eyebrow">STAFF ACCESS</p><h1>직원 계정</h1><p className="muted">공통 업무 계정을 추가하거나 활성 상태를 바꿉니다.</p>
    <details><summary>자세히</summary><p className="fine">모든 활성 계정이 같은 업무를 수행합니다. 활성 상태를 저장하면 해당 계정의 로그인 세션이 만료됩니다. 현재 로그인 계정은 비활성화할 수 없습니다. 개발자 계정은 로컬 관리 경로로 발급·변경합니다.</p></details>
    <div className="panel">{users.map(user => <form className="toolbar user-row" key={user.username} onSubmit={e => { e.preventDefault(); const value = formFields(e.currentTarget); void run(async () => {
      await api(`/admin/users/${user.username}`, 'PATCH', { active: value.active === 'on' }); await refresh();
    }); }}><strong>{user.username}</strong><span>업무 계정</span>
      <label className="check"><input name="active" type="checkbox" defaultChecked={user.active} />활성</label><button>계정 변경 저장</button></form>)}</div>
    <details className="panel"><summary>직원 계정 추가</summary><form onSubmit={e => { e.preventDefault(); const form = e.currentTarget; const value = formFields(form); void run(async () => {
      await api('/admin/users', 'POST', value); form.reset(); await refresh();
    }); }}><div className="form-grid"><label>새 계정<input name="username" pattern="[A-Za-z0-9_\-]+" required /></label><label>초기 비밀번호<input type="password" name="password" minLength={12} maxLength={256} autoComplete="new-password" required /></label>
      </div><button className="primary">계정 생성</button></form></details>
  </section>;
}
