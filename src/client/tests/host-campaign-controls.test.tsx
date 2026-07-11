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


describe('HostCampaignControls', () => {
  test('renders session scheduling and team objective controls', async () => {
    const { default: HostCampaignControls } = await import('../src/components/HostCampaignControls');
    const html = renderToStaticMarkup(<HostCampaignControls roomId="room-1" />);

    expect(html).toContain('下一场安排');
    expect(html).toContain('设置下一场');
    expect(html).toContain('队伍目标');
  });
});
