import { describe, expect, test } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const storage = new Map<string, string>();
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    get length() { return storage.size; },
    clear() { storage.clear(); },
    getItem(key: string) { return storage.get(key) ?? null; },
    key(index: number) { return Array.from(storage.keys())[index] ?? null; },
    removeItem(key: string) { storage.delete(key); },
    setItem(key: string, value: string) { storage.set(key, value); },
  } satisfies Storage,
});
Object.defineProperty(globalThis, 'sessionStorage', {
  configurable: true,
  value: globalThis.localStorage,
});

describe('EncounterPanel', () => {
  test('keeps an active combat read-only for normal flow', async () => {
    const { default: EncounterPanel } = await import('../src/components/EncounterPanel');
    const html = renderToStaticMarkup(
      React.createElement(EncounterPanel, {
        roomId: 'room-1',
        activeEncounter: {
          encounterId: 'encounter-1',
          roomId: 'room-1',
          type: 'combat',
          status: 'active',
          currentRound: 3,
          summary: '走廊中的冲突仍在继续。',
          participants: [{
            characterId: 'npc:visible',
            side: 'enemy',
            hp: 6,
            hpMax: 10,
            san: 0,
            sanMax: 0,
            dex: 70,
            mov: 7,
            distanceBand: 'near',
            statusTags: [],
            actedThisRound: false,
            weaponName: '手枪',
            damageExpression: '1d6',
            mainSkill: '射击',
            notes: '幕后信息',
            displayName: '走廊中的人影',
          }],
        },
        encounterSuggestion: null,
        onEncounterConfirmed: () => {},
      }),
    );

    expect(html).toContain('战斗由玩家声明、规则引擎与 AI-KP 自动推进');
    expect(html).not.toContain('下一回合');
    expect(html).not.toContain('强制结束');
    expect(html).not.toContain('快速创建 NPC');
    expect(html).not.toContain('创建 NPC');
  });
});
