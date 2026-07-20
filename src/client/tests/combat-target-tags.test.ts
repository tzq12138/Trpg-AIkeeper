import { describe, expect, test } from 'vitest';
import {
  getCombatTargetTags,
  toggleCombatTargetTag,
} from '../src/shared/combat-target-tags';

describe('combat target tags', () => {
  test('adds up to two observed targets without submitting an action', () => {
    const first = toggleCombatTargetTag('我先观察局势。', '走廊中的人影');
    const second = toggleCombatTargetTag(first.inputText, '安娜');
    const third = toggleCombatTargetTag(second.inputText, '北侧铁门');

    expect(second).toEqual({
      inputText: '[本轮行动 · 目标：走廊中的人影、安娜]\n我先观察局势。',
      targetTags: ['走廊中的人影', '安娜'],
      changed: true,
    });
    expect(third).toEqual({
      inputText: second.inputText,
      targetTags: ['走廊中的人影', '安娜'],
      changed: false,
    });
  });

  test('removes a selected target while preserving the natural language draft', () => {
    const result = toggleCombatTargetTag(
      '[本轮行动 · 目标：走廊中的人影、安娜]\n我想掩护她撤退。',
      '走廊中的人影',
    );

    expect(result).toEqual({
      inputText: '[本轮行动 · 目标：安娜]\n我想掩护她撤退。',
      targetTags: ['安娜'],
      changed: true,
    });
  });

  test('does not treat arbitrary bracketed player text as target tags', () => {
    expect(getCombatTargetTags('[这是玩家自己写的]\n我躲到门后。')).toEqual([]);
  });
});
