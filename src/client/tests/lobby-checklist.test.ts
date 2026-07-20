import { describe, expect, it } from 'vitest';
import { buildPlayerLobbyChecklist } from '../src/shared/lobby-checklist';

describe('buildPlayerLobbyChecklist', () => {
  it('shows the exact remaining preparation work', () => {
    const checklist = buildPlayerLobbyChecklist({
      scenarioTitle: '雾港来信',
      hasCharacter: true,
      isReady: false,
      isConnected: false,
      roomStatus: 'lobby',
    });

    expect(checklist).toEqual([
      { key: 'scenario', label: '剧本已确认', complete: true, detail: '雾港来信' },
      { key: 'character', label: '角色已确认', complete: true, detail: '可随时调整准备状态' },
      { key: 'connection', label: '实时连接', complete: false, detail: '正在恢复连接' },
      { key: 'ready', label: '准备开局', complete: false, detail: '确认后通知 Host' },
    ]);
  });

  it('marks a started room as ready to enter', () => {
    const checklist = buildPlayerLobbyChecklist({
      scenarioTitle: '雾港来信',
      hasCharacter: true,
      isReady: true,
      isConnected: true,
      roomStatus: 'active',
    });

    expect(checklist.at(-1)).toEqual({
      key: 'ready',
      label: '游戏已开始',
      complete: true,
      detail: '可以进入 KP 叙事',
    });
  });
});
