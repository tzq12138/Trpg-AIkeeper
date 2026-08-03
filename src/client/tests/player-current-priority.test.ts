import { describe, expect, test } from 'vitest';
import { getPlayerCurrentPriority, getPlayerPendingTaskCount } from '../src/shared/player-current-priority';

const storage = new Map<string, string>();
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  },
});

describe('player current priority', () => {
  test('counts only real pending tasks beyond free-form editing', () => {
    expect(getPlayerPendingTaskCount({
      hasPendingCombatReaction: true,
      hasConfirmationDraft: true,
      hasPendingInventoryTransfer: true,
      hasUnresolvedPartyQuestion: true,
      actionStatus: 'typing',
      hasInputText: true,
    })).toBe(4);
    expect(getPlayerPendingTaskCount({
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      actionStatus: 'typing',
      hasInputText: true,
    })).toBe(0);
  });

  test('prioritizes unread private results before public clues and counts both', () => {
    const input = {
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      hasPendingInventoryTransfer: false,
      hasUnresolvedPartyQuestion: false,
      unreadPrivateResultCount: 2,
      unreadPublicClueCount: 1,
      actionStatus: 'idle' as const,
      hasInputText: false,
    };

    expect(getPlayerPendingTaskCount(input)).toBe(3);
    expect(getPlayerCurrentPriority(input)).toMatchObject({
      title: '查看新的私密结果',
      targetTab: 'logs',
      notificationKind: 'private_result',
    });
  });

  test('surfaces a new public clue when no private result is unread', () => {
    expect(getPlayerCurrentPriority({
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      hasPendingInventoryTransfer: false,
      hasUnresolvedPartyQuestion: false,
      unreadPrivateResultCount: 0,
      unreadPublicClueCount: 1,
      actionStatus: 'idle',
      hasInputText: false,
    })).toMatchObject({
      title: '查看新公共线索',
      targetTab: 'logs',
    });
  });

  test('puts an immediate combat reaction ahead of every other player task', () => {
    const current = getPlayerCurrentPriority({
      hasPendingCombatReaction: true,
      hasConfirmationDraft: true,
      actionStatus: 'typing',
      hasInputText: true,
    });

    expect(current).toEqual({
      kind: 'danger',
      title: '立刻回应危险',
      detail: '先处理当前的闪避或反击，再继续其他行动。',
    });
  });

  test('asks for confirmation before continuing a draft or free action', () => {
    expect(getPlayerCurrentPriority({
      hasPendingCombatReaction: false,
      hasConfirmationDraft: true,
      actionStatus: 'awaiting_confirmation',
      hasInputText: true,
    })).toEqual({
      kind: 'decision',
      title: '确认你的行动',
      detail: '已生成理解预览；确认后才会进入裁决。',
    });
  });

  test('surfaces a pending private inventory transfer before ordinary action work', () => {
    expect(getPlayerCurrentPriority({
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      hasPendingInventoryTransfer: true,
      actionStatus: 'typing',
      hasInputText: true,
    })).toEqual({
      kind: 'decision',
      title: '处理待接收物品',
      detail: '队友正在转交物品；接收或拒绝后才会改变背包。',
      targetTab: 'inventory',
    });
  });

  test('surfaces public party questions after decisions and active resolutions', () => {
    expect(getPlayerCurrentPriority({
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      hasPendingInventoryTransfer: false,
      hasUnresolvedPartyQuestion: true,
      actionStatus: 'typing',
      hasInputText: false,
    })).toEqual({
      kind: 'free_action',
      title: '查看队伍待调查问题',
      detail: '队伍证据板有尚未解决的问题；它不会自动变成你的行动。',
      targetTab: 'home',
    });
  });

  test('surfaces a collaboration invitation after active action work', () => {
    const input = {
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      hasPendingInventoryTransfer: false,
      hasCollaborationInvite: true,
      hasUnresolvedPartyQuestion: false,
      actionStatus: 'idle' as const,
      hasInputText: false,
    };

    expect(getPlayerPendingTaskCount(input as any)).toBe(1);
    expect(getPlayerCurrentPriority(input as any)).toEqual({
      kind: 'decision',
      title: '回应协同行动邀请',
      detail: '所有受邀者明确接受后，才会生成各自仍需确认的关联行动。',
      targetTab: 'action',
    });
  });

  test('keeps public party questions actionable from the action page itself', async () => {
    const { getActionPanelCurrentPriority } = await import('../src/pages/PlayerActionPage');
    expect(getActionPanelCurrentPriority({
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      hasPendingInventoryTransfer: false,
      hasUnresolvedPartyQuestion: true,
      actionStatus: 'typing',
      hasInputText: false,
    })).toMatchObject({
      title: '查看队伍待调查问题',
      targetTab: 'home',
    });
  });

  test('keeps a draft editable when nothing else is blocking the player', () => {
    expect(getPlayerCurrentPriority({
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      actionStatus: 'typing',
      hasInputText: true,
    })).toEqual({
      kind: 'free_action',
      title: '继续编辑行动',
      detail: '切换输入类型不会清空你正在写的内容。',
    });
  });

  test('keeps the player informed while a confirmed action is resolving', () => {
    expect(getPlayerCurrentPriority({
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      actionStatus: 'resolving',
      hasInputText: false,
    })).toEqual({
      kind: 'waiting',
      title: '正在裁决你的行动',
      detail: 'AI 与规则引擎正在校验结果；世界状态会保持同步。',
    });
  });

  test('puts an authoritative runtime pause before ordinary mechanical work', () => {
    const input = {
      runtimeIntegrityStatus: 'paused_provider' as const,
      runtimeIntegrityReason: 'provider_unavailable',
      hasPendingConsent: true,
      hasCocFollowUp: true,
      hasPendingCombatReaction: false,
      hasConfirmationDraft: true,
      actionStatus: 'awaiting_confirmation' as const,
      hasInputText: true,
    };

    expect(getPlayerCurrentPriority(input)).toEqual({
      kind: 'danger',
      title: '机械行动已暂停',
      detail: '固定 AI 服务连续失败；你仍可查看记录，等待 Host 恢复或显式切换服务。',
      targetTab: 'action',
    });
  });

  test('prioritizes affected-player consent and CoC follow-up before ordinary actions', () => {
    const base = {
      hasPendingCombatReaction: false,
      hasConfirmationDraft: false,
      actionStatus: 'idle' as const,
      hasInputText: true,
    };

    expect(getPlayerCurrentPriority({ ...base, hasPendingConsent: true, hasCocFollowUp: true }))
      .toMatchObject({ title: '回应受影响行动', kind: 'decision' });
    expect(getPlayerCurrentPriority({ ...base, hasPendingConsent: false, hasCocFollowUp: true }))
      .toMatchObject({ title: '决定失败判定后续', kind: 'decision' });
  });
});
