import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';


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
  test('renders current fog state and reversible host controls', async () => {
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
    expect(html).toContain('雾化区域');
    expect(html).toContain('揭示区域');
  });
});
