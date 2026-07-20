import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';

const storage = new Map<string, string>();
Object.defineProperty(globalThis, 'localStorage', {
  value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  },
});


describe('HostAutonomyPolicyControl', () => {
  test('explains delegated offline boundaries without promising unsafe autonomy', async () => {
    const { HostAutonomyPolicyControl } = await import('../src/pages/HostLobby');
    const html = renderToStaticMarkup(React.createElement(HostAutonomyPolicyControl, {
      policy: 'delegated',
      disabled: false,
      onChange: () => {},
    }));

    expect(html).toContain('Host 计划离线策略');
    expect(html).toContain('已委托：普通检定、已揭示范围移动和普通物品使用');
    expect(html).toContain('战斗、秘密行动、幸运消耗和重大结果仍会等待 Host');
  });
});
