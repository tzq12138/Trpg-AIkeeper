import { describe, expect, it } from 'vitest';
import { listScenarioImageTargets, listUnillustratedSceneTargets } from './scenario-image-generation';

describe('listScenarioImageTargets', () => {
  it('uses identifiers first and a unique name fallback for imported scenes', () => {
    expect(listScenarioImageTargets({
      scenes: [{ scene_id: 'harbor', name: '雨港' }, { name: '没有 ID 的场景' }],
      npcs: [{ npc_id: 'keeper', name: '守夜人' }],
      items: [{ item_id: 'key', name: '铜钥匙' }],
      clues: [{ clue_id: 'letter', name: '潮湿信件' }],
    })).toEqual([
      { targetType: 'scene', targetKey: 'harbor', label: '场景 · 雨港' },
      { targetType: 'scene', targetKey: '没有 ID 的场景', label: '场景 · 没有 ID 的场景' },
      { targetType: 'npc', targetKey: 'keeper', label: 'NPC · 守夜人' },
      { targetType: 'item', targetKey: 'key', label: '物品 · 铜钥匙' },
      { targetType: 'clue', targetKey: 'letter', label: '线索 · 潮湿信件' },
    ]);
  });
});

describe('listUnillustratedSceneTargets', () => {
  it('keeps AI scene-art drafting limited to scenes without an image binding', () => {
    expect(listUnillustratedSceneTargets({
      scenes: [
        { scene_id: 'harbor', name: '雨港' },
        { scene_id: 'study', name: '书房', image_asset_id: 'asset-study' },
        { scene_id: 'attic', name: '阁楼', image_url: '/assets/attic.png' },
      ],
    })).toEqual([{ targetType: 'scene', targetKey: 'harbor', label: '场景 · 雨港' }]);
  });
});
