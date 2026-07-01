export type AppPage =
  | 'home'
  | 'admin'
  | 'rag-test'
  | 'host-create'
  | 'host-lobby'
  | 'host-stage'
  | 'player-join'
  | 'player-action'
  | 'player-builder'
  | 'login';

export interface AppRoute {
  page: AppPage;
  param: string;
}

export type HostTabKey = 'narrative' | 'combat' | 'database' | 'logs' | 'map';
export type PlayerTabKey = 'action' | 'character' | 'inventory' | 'logs' | 'map';

export const hostTabs: Array<{ key: HostTabKey; label: string; eyebrow: string }> = [
  { key: 'narrative', label: '传说', eyebrow: 'STAGE' },
  { key: 'combat', label: '追逐', eyebrow: 'COMBAT' },
  { key: 'database', label: '资料库', eyebrow: 'ARCHIVE' },
  { key: 'logs', label: '日志', eyebrow: 'LOG' },
  { key: 'map', label: '地图', eyebrow: 'MAP' },
];

export const playerTabs: Array<{ key: PlayerTabKey; label: string; eyebrow: string }> = [
  { key: 'action', label: '行动', eyebrow: 'ACT' },
  { key: 'character', label: '技能', eyebrow: 'SKILLS' },
  { key: 'inventory', label: '装备', eyebrow: 'GEAR' },
  { key: 'logs', label: '日志', eyebrow: 'LOGS' },
  { key: 'map', label: '地图', eyebrow: 'MAP' },
];

export function getRouteForPath(path: string): AppRoute {
  if (path === '/') return { page: 'home', param: '' };
  if (path === '/admin') return { page: 'admin', param: '' };
  if (path === '/rag-test') return { page: 'rag-test', param: '' };
  if (path === '/host/create') return { page: 'host-create', param: '' };
  if (path.match(/^\/host\/[^/]+\/stage$/)) return { page: 'host-stage', param: path.split('/')[2] };
  if (path.startsWith('/host/')) return { page: 'host-lobby', param: path.split('/')[2] };
  if (path === '/player/join') return { page: 'player-join', param: '' };
  if (path === '/login') return { page: 'login', param: '' };
  if (path.startsWith('/player/builder')) return { page: 'player-builder', param: '' };
  if (path.startsWith('/player/')) return { page: 'player-action', param: path.split('/')[2] };
  return { page: 'home', param: '' };
}

export function getCurrentRoute(): AppRoute {
  return getRouteForPath(window.location.pathname);
}
