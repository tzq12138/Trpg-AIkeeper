import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test, vi } from 'vitest';
import PlayerInventory from '../src/pages/PlayerInventory';

vi.hoisted(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: () => null,
      removeItem: () => {},
      setItem: () => {},
    },
  });
});

describe('PlayerInventory', () => {
  test('offers a private-notes workspace', () => {
    const html = renderToStaticMarkup(
      <PlayerInventory onDescribeInNarration={() => {}} onOpenCampaignHome={() => {}} />,
    );

    expect(html).toContain('我的笔记');
    expect(html).toContain('新建笔记');
  });
});
