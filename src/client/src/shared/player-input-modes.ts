export const PLAYER_INPUT_MODES = [
  'action',
  'speech',
  'party_chat',
  'ooc',
  'rule_question',
  'private_note',
  'clue_share',
  'item_action',
  'map_move',
  'combat_action',
  'safety',
] as const;

export type PlayerInputMode = typeof PLAYER_INPUT_MODES[number];

export const PLAYER_ACTION_COMPOSER_INPUT_MODES: readonly PlayerInputMode[] = PLAYER_INPUT_MODES.filter(
  (mode) => mode !== 'clue_share',
);

export const PLAYER_INPUT_MODE_LABELS: Record<PlayerInputMode, string> = {
  action: '行动',
  speech: '发言',
  party_chat: '队伍讨论',
  ooc: '场外信息',
  rule_question: '规则问题',
  private_note: '私密笔记',
  clue_share: '分享线索',
  item_action: '使用物品',
  map_move: '移动',
  combat_action: '战斗行动',
  safety: '安全边界',
};

export function isStatefulPlayerInputMode(
  mode: PlayerInputMode,
  speechRoutesToDialogue = false,
): boolean {
  return mode === 'action'
    || mode === 'item_action'
    || mode === 'map_move'
    || mode === 'combat_action'
    || (mode === 'speech' && speechRoutesToDialogue);
}

export function canSendWhileStatefulActionBusy(
  mode: PlayerInputMode,
  speechRoutesToDialogue = false,
): boolean {
  return !isStatefulPlayerInputMode(mode, speechRoutesToDialogue);
}

export function inputModeSubmitLabel(
  mode: PlayerInputMode,
  speechRoutesToDialogue = false,
): string {
  if (mode === 'safety') return '发送安全请求';
  if (mode === 'speech' && speechRoutesToDialogue) return '生成对话预览';
  return isStatefulPlayerInputMode(mode, speechRoutesToDialogue)
    ? '生成行动预览'
    : `记录${PLAYER_INPUT_MODE_LABELS[mode]}`;
}

export function confirmationImpactSummary(
  mode: PlayerInputMode,
  speechRoutesToDialogue = false,
): string {
  if (mode === 'speech' && speechRoutesToDialogue) {
    return '确认后作为角色对话处理，不会先作为队伍讨论发送。';
  }
  if (mode === 'combat_action') {
    return '确认后加入本轮声明；锁定后将与其他行动统一按规则结算。';
  }
  if (mode === 'item_action') {
    return '确认后检查物品与目标条件；只有结算成功才会应用资源变化。';
  }
  if (mode === 'map_move') {
    return '确认后检查路线与可见信息；必要时会进入规则检定。';
  }
  return '确认后会按当前场景、角色状态和规则进行结算；结果不会在确认前写入世界状态。';
}

export function recordedInputSummary(mode: PlayerInputMode, _text: string): string {
  if (mode === 'private_note') return '已记录私密笔记，仅自己可见，不会进入剧情。';
  if (mode === 'rule_question') return '已保存规则问题，仅自己可见，不会进入剧情。';
  if (mode === 'safety') return '已私密发送安全请求，不会进入剧情或改变世界状态。';
  if (mode === 'party_chat') return '已发送队伍讨论，不会自动变成角色行动。';
  if (mode === 'ooc') return '已发送场外信息，不会进入剧情、规则或世界状态。';
  if (mode === 'clue_share') return '已记录线索分享请求，尚未改变线索事实状态。';
  return `已记录${PLAYER_INPUT_MODE_LABELS[mode]}，不会改变世界状态。`;
}
