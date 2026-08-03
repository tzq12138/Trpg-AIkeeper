import type { ActionStatus, RuntimeIntegrityStatus } from './types';

export type PlayerCurrentPriorityKind = 'danger' | 'decision' | 'waiting' | 'free_action';

export interface PlayerCurrentPriorityInput {
  hasPendingCombatReaction: boolean;
  hasConfirmationDraft: boolean;
  hasPendingConsent?: boolean;
  hasCocFollowUp?: boolean;
  runtimeIntegrityStatus?: RuntimeIntegrityStatus;
  runtimeIntegrityReason?: string | null;
  hasPendingInventoryTransfer?: boolean;
  hasCollaborationInvite?: boolean;
  hasUnresolvedPartyQuestion?: boolean;
  unreadPrivateResultCount?: number;
  unreadPublicClueCount?: number;
  actionStatus: ActionStatus;
  hasInputText: boolean;
}

export interface PlayerCurrentPriority {
  kind: PlayerCurrentPriorityKind;
  title: string;
  detail: string;
  targetTab?: 'action' | 'inventory' | 'home' | 'logs';
  notificationKind?: 'private_result' | 'public_clue';
}

const WAITING_STATUSES = new Set<ActionStatus>([
  'analyzing',
  'queued',
  'batched',
  'resolving',
  'awaiting_player_choice',
  'awaiting_player_consent',
  'awaiting_host_exception',
]);

function positiveCount(value: number | undefined): number {
  return Number.isFinite(value) && value && value > 0 ? Math.floor(value) : 0;
}

export function getPlayerPendingTaskCount(input: PlayerCurrentPriorityInput): number {
  return [
    Boolean(input.runtimeIntegrityStatus && input.runtimeIntegrityStatus !== 'healthy'),
    input.hasPendingCombatReaction,
    input.hasConfirmationDraft,
    input.hasPendingConsent,
    input.hasCocFollowUp,
    input.hasPendingInventoryTransfer,
    WAITING_STATUSES.has(input.actionStatus) && !input.hasCocFollowUp,
    input.hasCollaborationInvite,
    input.hasUnresolvedPartyQuestion,
  ].filter(Boolean).length
    + positiveCount(input.unreadPrivateResultCount)
    + positiveCount(input.unreadPublicClueCount);
}

export function getPlayerCurrentPriority(input: PlayerCurrentPriorityInput): PlayerCurrentPriority {
  if (input.runtimeIntegrityStatus === 'paused_provider') {
    return {
      kind: 'danger',
      title: '机械行动已暂停',
      detail: '固定 AI 服务连续失败；你仍可查看记录，等待 Host 恢复或显式切换服务。',
      targetTab: 'action',
    };
  }

  if (input.runtimeIntegrityStatus === 'read_only_recovery') {
    return {
      kind: 'danger',
      title: '房间处于只读恢复',
      detail: '状态完整性需要 Host 处理；当前只能查看既有记录，不能提交机械行动。',
      targetTab: 'action',
    };
  }

  if (input.hasPendingCombatReaction) {
    return {
      kind: 'danger',
      title: '立刻回应危险',
      detail: '先处理当前的闪避或反击，再继续其他行动。',
    };
  }

  if (input.hasPendingConsent) {
    return {
      kind: 'decision',
      title: '回应受影响行动',
      detail: '只有你能决定是否接受这次对你产生机械影响的行动；沉默不会视为同意。',
      targetTab: 'action',
    };
  }

  if (input.hasConfirmationDraft) {
    return {
      kind: 'decision',
      title: '确认你的行动',
      detail: '已生成理解预览；确认后才会进入裁决。',
    };
  }

  if (input.hasCocFollowUp) {
    return {
      kind: 'decision',
      title: '决定失败判定后续',
      detail: '从现有回执选择精确消耗幸运、承担推骰风险，或保留原失败。',
      targetTab: 'action',
    };
  }

  if (input.hasPendingInventoryTransfer) {
    return {
      kind: 'decision',
      title: '处理待接收物品',
      detail: '队友正在转交物品；接收或拒绝后才会改变背包。',
      targetTab: 'inventory',
    };
  }

  if (WAITING_STATUSES.has(input.actionStatus)) {
    return {
      kind: 'waiting',
      title: '正在裁决你的行动',
      detail: 'AI 与规则引擎正在校验结果；世界状态会保持同步。',
    };
  }

  if (input.hasCollaborationInvite) {
    return {
      kind: 'decision',
      title: '回应协同行动邀请',
      detail: '所有受邀者明确接受后，才会生成各自仍需确认的关联行动。',
      targetTab: 'action',
    };
  }

  if (positiveCount(input.unreadPrivateResultCount) > 0) {
    return {
      kind: 'free_action',
      title: '查看新的私密结果',
      detail: `有 ${positiveCount(input.unreadPrivateResultCount)} 条仅你可见的结果等待查看。`,
      targetTab: 'logs',
      notificationKind: 'private_result',
    };
  }

  if (positiveCount(input.unreadPublicClueCount) > 0) {
    return {
      kind: 'free_action',
      title: '查看新公共线索',
      detail: `有 ${positiveCount(input.unreadPublicClueCount)} 条已公开线索等待查看。`,
      targetTab: 'logs',
      notificationKind: 'public_clue',
    };
  }

  if (input.hasUnresolvedPartyQuestion) {
    return {
      kind: 'free_action',
      title: '查看队伍待调查问题',
      detail: '队伍证据板有尚未解决的问题；它不会自动变成你的行动。',
      targetTab: 'home',
    };
  }

  if (input.hasInputText) {
    return {
      kind: 'free_action',
      title: '继续编辑行动',
      detail: '切换输入类型不会清空你正在写的内容。',
    };
  }

  return {
    kind: 'free_action',
    title: '轮到你决定',
    detail: '描述你想做的事；需要判定时系统会先说明。',
  };
}
