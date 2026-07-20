export type HomeTaskTone = 'default' | 'yellow' | 'black';

export interface HomeTask {
  label: string;
  eyebrow: string;
  href: string;
  tone: HomeTaskTone;
}

const PLAYER_TASKS: HomeTask[] = [
  { label: '加入房间', eyebrow: 'PLAYER / INVITATION', href: '/player/join', tone: 'yellow' },
  { label: '创建调查员', eyebrow: 'PLAYER / CHARACTER', href: '/player/builder', tone: 'default' },
];

const HOST_TASKS: HomeTask[] = [
  { label: '创建房间', eyebrow: 'HOST / KEEPER', href: '/host/create', tone: 'yellow' },
  { label: '加入房间', eyebrow: 'PLAYER / INVESTIGATOR', href: '/player/join', tone: 'default' },
];

const ADMIN_TASKS: HomeTask[] = [
  { label: '内容与系统后台', eyebrow: 'ADMIN / OPERATIONS', href: '/admin', tone: 'black' },
  { label: '创建房间', eyebrow: 'HOST / KEEPER', href: '/host/create', tone: 'yellow' },
  { label: '加入房间', eyebrow: 'PLAYER / INVESTIGATOR', href: '/player/join', tone: 'default' },
];

export function getHomeTasks(role?: string): HomeTask[] {
  if (role === 'admin') return ADMIN_TASKS;
  if (role === 'host') return HOST_TASKS;
  return PLAYER_TASKS;
}
