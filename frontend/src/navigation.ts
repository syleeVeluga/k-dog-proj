import type { Role } from './types';

export type Route =
  | 'intake' | 'intake/upload' | 'survey' | 'recording/inbox' | 'recording/record'
  | 'preprocess' | 'scoring' | 'report' | 'report/comparison' | 'report/export'
  | 'validation' | 'admin/users' | 'admin/backup';

export type MenuItem = { route: Route; label: string; roles: Role[]; parent?: string; roleLabels?: Partial<Record<Role, string>> };
export type MenuGroup = { id: string; label: string; items: MenuItem[] };

const everyone: Role[] = ['operator', 'reviewer', 'admin'];
const staff: Role[] = ['operator', 'admin'];

// 현장 진행 → 분석·평가 → 자료 관리 순서. 역할별 노출은 항목의 roles가 정한다.
export const menuTree: MenuGroup[] = [
  { id: 'field', label: '현장 운영', items: [
    { route: 'intake', label: '참가자 접수', roles: everyone },
    { route: 'intake/upload', label: '일괄 등록 (CSV·Excel)', roles: staff },
    { route: 'survey', label: '설문 현황', roles: everyone },
    { route: 'recording/inbox', label: '영상 수신·연결', roles: staff, parent: '촬영' },
    { route: 'recording/record', label: '촬영 기록 (8구간)', roles: everyone, parent: '촬영' },
  ] },
  { id: 'analysis', label: '분석·평가', items: [
    { route: 'preprocess', label: '전처리', roles: everyone },
    { route: 'scoring', label: '독립 채점', roles: everyone },
    // U08(Q03 결정): 교수/검토자도 리포트 발급 화면을 운영자와 같이 쓴다. 비교 조건·연구 내보내기는 운영자 전용.
    { route: 'report', label: '리포트 발급', roles: everyone, parent: '리포트' },
    { route: 'report/comparison', label: '비교 조건', roles: staff, parent: '리포트' },
    { route: 'report/export', label: '연구 내보내기', roles: staff, parent: '리포트' },
  ] },
  { id: 'data', label: '자료 관리', items: [
    { route: 'validation', label: '검수 자료', roles: staff },
    { route: 'admin/users', label: '직원 계정', roles: ['admin'] },
    { route: 'admin/backup', label: '백업·복구', roles: ['admin'] },
  ] },
];

const items = menuTree.flatMap(group => group.items);

export function visibleMenu(role: Role): MenuGroup[] {
  return menuTree.map(group => ({ ...group, items: group.items.filter(item => item.roles.includes(role)).map(item => ({ ...item, label: item.roleLabels?.[role] ?? item.label })) })).filter(group => group.items.length);
}

export function defaultRoute(role: Role): Route {
  return visibleMenu(role)[0]?.items[0]?.route ?? 'intake';
}

export function canOpen(route: Route, role: Role) {
  return items.some(item => item.route === route && item.roles.includes(role));
}

export function routeLabel(route: Route) {
  return items.find(item => item.route === route)?.label ?? '';
}

export function hashOf(route: Route) {
  return `#/${route}`;
}

// 알 수 없는 hash나 권한 없는 경로는 null이다.
export function parseHash(hash: string, role: Role): Route | null {
  let text = hash.replace(/^#\/?/, '');
  try { text = decodeURIComponent(text); } catch { return null; }
  text = text.replace(/\/+$/, '');
  const route = items.find(item => item.route === text)?.route;
  return route && canOpen(route, role) ? route : null;
}
