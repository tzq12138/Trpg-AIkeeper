import { describe, expect, test } from 'vitest';
import { combatRoundSummaryText } from '../src/shared/combat-round-summary';

describe('combat round summary', () => {
  test('renders only the explicit public summary fields', () => {
    const text = combatRoundSummaryText({
      combat_summary: {
        title: '第 4 轮结束',
        public_facts: ['北侧铁门已经打开'],
        current_situation: '人影仍挡在走廊中央。',
        hidden_enemy_hp: 1,
      },
    });

    expect(text).toBe('第 4 轮结束\n北侧铁门已经打开\n人影仍挡在走廊中央。');
    expect(text).not.toContain('hidden_enemy_hp');
  });

  test('does not repeat the final public fact as the current situation', () => {
    const text = combatRoundSummaryText({
      combat_summary: {
        title: '第 4 轮结束',
        public_facts: ['北侧铁门已经打开'],
        current_situation: '北侧铁门已经打开',
      },
    });

    expect(text).toBe('第 4 轮结束\n北侧铁门已经打开');
  });
});
