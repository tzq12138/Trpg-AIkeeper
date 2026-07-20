import { describe, expect, it } from 'vitest';
import { buildHostLaunchChecklist } from '../src/shared/host-launch-checklist';

describe('buildHostLaunchChecklist', () => {
  it('identifies the remaining blockers before a Host starts a room', () => {
    expect(buildHostLaunchChecklist({
      scenarioTitle: '',
      playerCount: 2,
      unreadyPlayerCount: 1,
    })).toEqual([
      { key: 'scenario', label: '可开团剧本', complete: false, detail: '请选择已发布剧本' },
      { key: 'players', label: '调查员加入', complete: true, detail: '2 名调查员已加入' },
      { key: 'ready', label: '玩家准备', complete: false, detail: '1 名玩家尚未准备' },
    ]);
  });

  it('shows a room as launch-ready only when all requirements pass', () => {
    expect(buildHostLaunchChecklist({
      scenarioTitle: '雾港来信',
      playerCount: 4,
      unreadyPlayerCount: 0,
    }).every((item) => item.complete)).toBe(true);
  });
});
