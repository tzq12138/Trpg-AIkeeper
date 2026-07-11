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
});
