import { describe, expect, it } from 'vitest';
import { describeItemUse, describeClueShare } from '../src/shared/player-inventory-intents';

describe('player inventory natural-language prompts', () => {
  it('uses the action composer instead of submitting an item action directly', () => {
    expect(describeItemUse('银钥匙')).toBe('我想使用银钥匙，并说明它在当前场景中的作用。');
  });

  it('makes sharing a clue a reviewable public action', () => {
    expect(describeClueShare('门上有血迹')).toBe('我想把线索“门上有血迹”分享给队伍。');
  });
});
