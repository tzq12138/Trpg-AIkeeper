export const PLAYER_INPUT_MODES = [
  'action',
  'speech',
  'party_chat',
  'ooc',
  'rule_question',
  'private_note',
] as const;

export type PlayerInputMode = typeof PLAYER_INPUT_MODES[number];

export interface PlayerInputModePolicy {
  label: string;
  placeholder: string;
  createsFormalAction: boolean;
}

const INPUT_MODE_POLICIES: Record<PlayerInputMode, PlayerInputModePolicy> = {
  action: {
    label: '行动',
    placeholder: '描述你的行动…',
    createsFormalAction: true,
  },
  speech: {
    label: '角色发言',
    placeholder: '写下角色说的话…',
    createsFormalAction: true,
  },
  party_chat: {
    label: '队伍讨论',
    placeholder: '与队友讨论，不会直接推动世界状态…',
    createsFormalAction: false,
  },
  ooc: {
    label: '桌外交流',
    placeholder: '桌外说明，不会进入剧情或规则…',
    createsFormalAction: false,
  },
  rule_question: {
    label: '规则问题',
    placeholder: '询问规则，不会创建行动…',
    createsFormalAction: false,
  },
  private_note: {
    label: '私人笔记',
    placeholder: '记录推测，仅自己可见…',
    createsFormalAction: false,
  },
};

export function getPlayerInputModePolicy(mode: PlayerInputMode): PlayerInputModePolicy {
  return INPUT_MODE_POLICIES[mode];
}
