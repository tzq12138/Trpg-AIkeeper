export type TeamMessageChannel = 'party_chat' | 'speech' | 'ooc';

const CHANNEL_LABELS: Record<TeamMessageChannel, string> = {
  party_chat: '队伍讨论',
  speech: '角色发言',
  ooc: '场外信息',
};

function normalizeChannel(channel: unknown): TeamMessageChannel {
  return channel === 'speech' || channel === 'ooc' || channel === 'party_chat'
    ? channel
    : 'party_chat';
}

export function teamMessageChannelLabel(channel: unknown): string {
  return CHANNEL_LABELS[normalizeChannel(channel)];
}

export function formatTeamMessageText(payload: {
  playerName?: unknown;
  investigatorName?: unknown;
  text?: unknown;
  channel?: unknown;
}): string {
  const sender = String(payload.playerName || payload.investigatorName || '队友');
  return `【${teamMessageChannelLabel(payload.channel)}】${sender}: ${String(payload.text || '')}`;
}
