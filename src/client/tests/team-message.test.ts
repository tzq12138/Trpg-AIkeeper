import { describe, expect, test } from 'vitest';
import { formatTeamMessageText, teamMessageChannelLabel } from '../src/shared/team-message';

describe('team message presentation', () => {
  test('marks out-of-character messages without pretending they are narration', () => {
    expect(teamMessageChannelLabel('ooc')).toBe('场外信息');
    expect(formatTeamMessageText({
      playerName: '李明',
      investigatorName: '陈探员',
      text: '我去拿杯水。',
      channel: 'ooc',
    })).toBe('【场外信息】李明: 我去拿杯水。');
  });

  test('keeps character speech distinct from team discussion', () => {
    expect(teamMessageChannelLabel('speech')).toBe('角色发言');
    expect(teamMessageChannelLabel('party_chat')).toBe('队伍讨论');
  });
});
