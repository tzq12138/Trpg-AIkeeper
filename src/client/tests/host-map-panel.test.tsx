import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import { readFileSync } from 'node:fs';


function createStorageMock(): Storage {
  return {
    length: 0,
    clear() {},
    getItem() { return null; },
    key() { return null; },
    removeItem() {},
    setItem() {},
  };
}

Object.defineProperty(globalThis, 'localStorage', { value: createStorageMock(), configurable: true });
Object.defineProperty(globalThis, 'sessionStorage', { value: createStorageMock(), configurable: true });


describe('RegionFogControls', () => {
  test('renders current fog state as read-only director evidence', async () => {
    const { RegionFogControls } = await import('../src/components/HostMapPanel');
    const html = renderToStaticMarkup(
      <RegionFogControls
        regions={[
          { regionId: 'library', nodeId: 'library', label: '图书馆' },
          { regionId: 'cellar', nodeId: 'cellar', label: '地下室' },
        ]}
        fogRegions={['cellar']}
        onSetVisibility={() => {}}
      />,
    );

    expect(html).toContain('区域迷雾');
    expect(html).toContain('图书馆：已显示');
    expect(html).toContain('地下室：迷雾中');
    expect(html).toContain('只读');
    expect(html).not.toContain('<button');
    expect(html).not.toContain('雾化区域');
    expect(html).not.toContain('揭示区域');
  });

  test('does not retain dangerous map mutation POST handlers in source', () => {
    const source = readFileSync(new URL('../src/components/HostMapPanel.tsx', import.meta.url), 'utf8');

    expect(source).not.toContain('/map/reveal');
    expect(source).not.toContain('/map/move-character');
    expect(source).not.toContain('/visibility');
    expect(source).not.toContain('handleForceMove');
    expect(source).not.toContain('handleReveal');
    expect(source).not.toContain('handleHide');
  });
});
