import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';


function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    clear() { store.clear(); },
    getItem(key: string) { return store.get(key) ?? null; },
    key(index: number) { return Array.from(store.keys())[index] ?? null; },
    removeItem(key: string) { store.delete(key); },
    setItem(key: string, value: string) { store.set(key, value); },
  };
}

Object.defineProperty(globalThis, 'localStorage', {
  value: createStorageMock(),
  configurable: true,
});


describe('CampaignHomePanel', () => {
  test('renders the player campaign return and collaboration sections', async () => {
    const { default: CampaignHomePanel } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(<CampaignHomePanel roomId="room-1" />);

    expect(html).toContain('战役回流');
    expect(html).toContain('本场状态');
    expect(html).toContain('引用依据');
    expect(html).toContain('新增个人目标');
    expect(html).toContain('Session Zero');
    expect(html).toContain('私人笔记');
    expect(html).toContain('队伍证据板');
  });

  test('renders the current solo entry with a continue action', async () => {
    const { CampaignCurrentSceneCard } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <CampaignCurrentSceneCard
        scene={{
          node_id: '1',
          title: '条目 1',
          text_preview: '太阳高悬，你正在汽车站等车。',
          citation: {
            label: '开场场景',
            page: 4,
            scene: '奥斯本药店',
            verified: true,
          },
          choice_count: 1,
          image_asset_id: 'opening-image',
        }}
        onContinue={() => {}}
      />,
    );

    expect(html).toContain('当前场景');
    expect(html).not.toContain('条目 1');
    expect(html).toContain('太阳高悬');
    expect(html).toContain('继续当前场景');
    expect(html).toContain('1 个可选方向');
    expect(html).toContain('依据已校验');
    expect(html).toContain('开场场景');
    expect(html).toContain('第 4 页');
    expect(html).toContain('奥斯本药店');
    expect(html).not.toContain('source_ref');
    expect(html).not.toContain('向火独行.pdf');
    expect(html).toContain('/api/player/assets/opening-image');
    expect(html).toContain('当前场景插图');
  });
});
