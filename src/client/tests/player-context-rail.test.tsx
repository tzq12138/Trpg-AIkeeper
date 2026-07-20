import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import type { NarrativeFeedItem } from '../src/pages/PlayerActionPage';

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

describe('PlayerContextRail', () => {
  test('renders pending work and player-visible recent events in the mobile drawer', async () => {
    const { PlayerContextRail } = await import('../src/pages/PlayerActionPage');
    const recentItems: NarrativeFeedItem[] = [
      { id: 'event-1', kind: 'kp_narration', text: '雨声压过了远处的汽笛。' },
      { id: 'event-2', kind: 'judgement', text: '你成功撬开了仓库门。' },
    ];
    const html = renderToStaticMarkup(
      <PlayerContextRail
        character={null}
        currentPriority={{
          kind: 'decision',
          title: '处理待接收物品',
          detail: '队友正在转交物品；接收或拒绝后才会改变背包。',
          targetTab: 'inventory',
        }}
        recentItems={recentItems}
        onOpenTab={() => {}}
      />,
    );

    expect(html).toContain('待处理');
    expect(html).toContain('最近发生');
    expect(html).toContain('处理待接收物品');
    expect(html).toContain('查看待接收物品');
    expect(html).toContain('你成功撬开了仓库门。');
  });

  test('limits recent items to five and never invents a pending task', async () => {
    const { PlayerContextRail } = await import('../src/pages/PlayerActionPage');
    const recentItems: NarrativeFeedItem[] = Array.from({ length: 6 }, (_, index) => ({
      id: `event-${index + 1}`,
      kind: 'kp_narration',
      text: `事件 ${index + 1}`,
    }));
    const html = renderToStaticMarkup(
      <PlayerContextRail
        character={null}
        currentPriority={null}
        recentItems={recentItems}
        onOpenTab={() => {}}
      />,
    );

    expect(html).toContain('暂无待处理事项。');
    expect(html).not.toContain('事件 1');
    expect(html).toContain('事件 2');
    expect(html).toContain('事件 6');
  });
});
