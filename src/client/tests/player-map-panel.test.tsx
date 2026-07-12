import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';

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

describe('SemanticMapPanel', () => {
  test('renders a read-only semantic projection without direct movement controls', async () => {
    const { SemanticMapPanel } = await import('../src/pages/PlayerActionPage');
    const html = renderToStaticMarkup(
      <SemanticMapPanel
        projection={{
          roomId: 'room-1',
          mapStatus: 'active',
          mapType: 'hybrid',
          baseAsset: { assetId: 'map-1' },
          knownLocations: [
            { nodeId: 'station', label: '车站', description: '潮湿的候车室', isCurrent: true, position: { x: 20, y: 30 } },
            { nodeId: 'library', label: '图书馆', description: '只知道入口方向', isCurrent: false, position: { x: 70, y: 30 } },
          ],
          knownConnections: [{ fromNodeId: 'station', toNodeId: 'library', label: '石阶' }],
          partyPosition: { nodeId: 'station', label: '车站' },
          fogOfWar: [{ regionId: 'fog-1', polygon: [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2]] }],
        }}
      />,
    );

    expect(html).toContain('语义地图');
    expect(html).toContain('车站');
    expect(html).toContain('图书馆');
    expect(html).toContain('石阶');
    expect(html).toContain('只读');
    expect(html).not.toContain('<button');
    expect(html).not.toContain('秘密移动');
    expect(html).not.toContain('转到条目');
    expect(html).not.toContain('source_ref');
  });
});
