export type ScenarioImageTarget = {
  targetType: 'scene' | 'npc' | 'item' | 'clue';
  targetKey: string;
  label: string;
};

type TargetDefinition = {
  targetType: ScenarioImageTarget['targetType'];
  graphKey: string;
  identifiers: string[];
  label: string;
};

const TARGET_DEFINITIONS: TargetDefinition[] = [
  { targetType: 'scene', graphKey: 'scenes', identifiers: ['scene_id', 'id'], label: '场景' },
  { targetType: 'npc', graphKey: 'npcs', identifiers: ['npc_id', 'id'], label: 'NPC' },
  { targetType: 'item', graphKey: 'items', identifiers: ['item_id', 'id'], label: '物品' },
  { targetType: 'clue', graphKey: 'clues', identifiers: ['clue_id', 'id'], label: '线索' },
];

export function listScenarioImageTargets(graph: Record<string, unknown>): ScenarioImageTarget[] {
  return TARGET_DEFINITIONS.flatMap((definition) => {
    const rawValues = graph[definition.graphKey];
    const values: unknown[] = Array.isArray(rawValues) ? rawValues : [];
    const nameCounts = values.reduce<Record<string, number>>((counts, value) => {
      if (!value || typeof value !== 'object') return counts;
      const name = String((value as Record<string, unknown>).name || '').trim();
      if (name) counts[name] = (counts[name] || 0) + 1;
      return counts;
    }, {});
    return values.flatMap((value: unknown) => {
      if (!value || typeof value !== 'object') return [];
      const item = value as Record<string, unknown>;
      const name = String(item.name || item.title || '').trim();
      const targetKey = definition.identifiers
        .map((identifier) => String(item[identifier] || '').trim())
        .find(Boolean)
        || (name && nameCounts[name] === 1 ? name : '');
      if (!targetKey) return [];
      return [{
        targetType: definition.targetType,
        targetKey,
        label: `${definition.label} · ${name || targetKey}`,
      }];
    });
  });
}

export function listUnillustratedSceneTargets(graph: Record<string, unknown>): ScenarioImageTarget[] {
  const scenes = Array.isArray(graph.scenes) ? graph.scenes : [];
  return listScenarioImageTargets({ scenes: scenes.filter((value) => {
    if (!value || typeof value !== 'object') return false;
    const scene = value as Record<string, unknown>;
    return !scene.image_asset_id && !scene.image_url;
  }) }).filter((target) => target.targetType === 'scene');
}
