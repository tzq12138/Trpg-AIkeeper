import type { TacticalAction } from './types';

export function buildEncounterActions(
  encounterType: string,
  encounterId: string,
): TacticalAction[] {
  if (!encounterId) return [];
  const encounterParams = { encounterId };
  if (encounterType === 'combat') {
    return [
      { action_id: 'cmb-atk', label: '⚔️ 攻击', intent_type: 'combat_action', params: { ...encounterParams, actionKind: 'attack', skillName: '斗殴' } },
      { action_id: 'cmb-dod', label: '🛡️ 闪避', intent_type: 'combat_action', params: { ...encounterParams, actionKind: 'dodge' } },
      { action_id: 'cmb-def', label: '🛡️ 防御', intent_type: 'combat_action', params: { ...encounterParams, actionKind: 'defend' } },
      { action_id: 'cmb-ast', label: '🤝 协助', intent_type: 'combat_action', params: { ...encounterParams, actionKind: 'assist' } },
      { action_id: 'cmb-fle', label: '🏃 逃跑', intent_type: 'combat_action', params: { ...encounterParams, actionKind: 'flee' } },
      { action_id: 'cmb-wat', label: '⏳ 等待', intent_type: 'combat_action', params: { ...encounterParams, actionKind: 'wait' } },
    ];
  }
  return [
    { action_id: 'chs-pur', label: '🏃 追击', intent_type: 'chase_action', params: { ...encounterParams, actionKind: 'pursue', skillName: '运动' } },
    { action_id: 'chs-esc', label: '💨 逃脱', intent_type: 'chase_action', params: { ...encounterParams, actionKind: 'escape', skillName: '运动' } },
    { action_id: 'chs-blk', label: '🚧 路障', intent_type: 'chase_action', params: { ...encounterParams, actionKind: 'block' } },
    { action_id: 'chs-det', label: '🔄 绕路', intent_type: 'chase_action', params: { ...encounterParams, actionKind: 'detour', skillName: '导航' } },
    { action_id: 'chs-ast', label: '🤝 协助', intent_type: 'chase_action', params: { ...encounterParams, actionKind: 'assist' } },
    { action_id: 'chs-wat', label: '⏳ 等待', intent_type: 'chase_action', params: { ...encounterParams, actionKind: 'wait' } },
  ];
}
