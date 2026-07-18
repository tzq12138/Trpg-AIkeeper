import { describe, expect, test } from 'vitest';

import { getHomeTasks } from '../src/shared/home-navigation';

describe('role-aware home navigation', () => {
  test('prioritizes the player invitation journey for player accounts', () => {
    const tasks = getHomeTasks('player');

    expect(tasks[0]).toMatchObject({ label: '加入房间', href: '/player/join', tone: 'yellow' });
    expect(tasks.map((task) => task.href)).not.toContain('/admin');
  });

  test('prioritizes content operations for administrators', () => {
    const tasks = getHomeTasks('admin');

    expect(tasks[0]).toMatchObject({ label: '内容与系统后台', href: '/admin', tone: 'black' });
    expect(tasks.map((task) => task.href)).toContain('/host/create');
  });
});
