import type { Role } from './types';

export type Route =
  | 'intake' | 'intake/upload' | 'survey' | 'recording/inbox' | 'recording/record' | 'recording/shared'
  | 'preprocess' | 'scoring' | 'report' | 'report/comparison' | 'report/export'
  | 'validation' | 'admin/users' | 'admin/backup' | 'developer/settings';

export type MenuItem = { route: Route; label: string; roles: Role[]; parent?: string; roleLabels?: Partial<Record<Role, string>> };
export type MenuGroup = { id: string; label: string; items: MenuItem[] };

const everyone: Role[] = ['operator', 'reviewer', 'admin', 'developer'];
const staff = everyone;

// 업무 메뉴는 공통이며 개발 설정만 별도로 보호한다.
export const menuTree: MenuGroup[] = [
  { id: 'field', label: '현장 운영', items: [
    { route: 'intake', label: '참가자 접수', roles: everyone },
    { route: 'intake/upload', label: '참가자 및 설문 일괄 등록', roles: staff },
    { route: 'survey', label: '설문 확인', roles: everyone },
  ] },
  { id: 'analysis', label: '분석·평가', items: [
    { route: 'preprocess', label: '전처리', roles: everyone },
    { route: 'scoring', label: '독립 채점', roles: everyone },
    { route: 'report', label: '리포트 발급', roles: everyone, parent: '리포트' },
    { route: 'report/comparison', label: '비교 조건', roles: staff, parent: '리포트' },
    { route: 'report/export', label: '연구 내보내기', roles: staff, parent: '리포트' },
  ] },
  { id: 'data', label: '자료 관리', items: [
    { route: 'validation', label: '검수 자료', roles: staff },
    { route: 'admin/users', label: '직원 계정', roles: everyone },
    { route: 'admin/backup', label: '백업·복구', roles: everyone },
    { route: 'developer/settings', label: '개발 설정', roles: ['developer'] },
  ] },
];

const items: MenuItem[] = [...menuTree.flatMap(group => group.items),
  { route: 'recording/inbox', label: '영상 등록', roles: everyone },
  { route: 'recording/record', label: '촬영 기록', roles: everyone },
  { route: 'recording/shared', label: '공용 업로드 보관함', roles: everyone },
];

export const participantTasks: Route[] = ['survey', 'recording/inbox', 'recording/record'];

export function routeGroup(route: Route) {
  return menuTree.find(group => group.items.some(item => item.route === route))?.label ?? '현장 운영';
}

export function routeParent(route: Route) {
  return items.find(item => item.route === route)?.parent;
}

export function visibleMenu(role: Role): MenuGroup[] {
  return menuTree.map(group => ({ ...group, items: group.items.filter(item => item.roles.includes(role)).map(item => ({ ...item, label: item.roleLabels?.[role] ?? item.label })) })).filter(group => group.items.length);
}

export function defaultRoute(role: Role): Route {
  if (role === 'developer') return 'developer/settings';
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
