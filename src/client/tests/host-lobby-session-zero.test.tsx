// @vitest-environment jsdom
/**
 * HostLobby readiness feedback and Stage-independence coverage (B3).
 *
 * A start rejection with the structured AI_ONLY_SESSION_ZERO_INCOMPLETE body
 * must render per-player missing items readable by a human, never
 * "[object Object]". AI-only rooms must not offer force-start or host-offline
 * policy controls, and a successful start must land on the host operations
 * console — the Stage is optional and must never gate a successful start.
 */
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('../src/shared/identity', () => ({
  getSlotValue: (key: string) => (key === 'owner_token' ? 'owner-1' : ''),
}));

vi.mock('../src/components/HostCampaignControls', () => ({
  default: () => null,
}));

import HostLobby from '../src/pages/HostLobby';

// Silences the "environment is not configured to support act(...)" warning.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ── global stubs ─────────────────────────────────────────────────────

class WebSocketStub {
  onopen: (() => void) | null = null;
  onmessage: ((event: unknown) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  close() {}
  send() {}
  addEventListener() {}
}

const roomBody = {
  room_id: 'room-1',
  status: 'lobby',
  scenario_id: 'sc-1',
  scenario_title: '玻璃雨夜',
  speech_routing: 'party_message',
  host_autonomy_policy: 'delegated',
  session_mode: 'ai_only',
  players: [
    {
      character_id: 'char-1',
      player_name: '张三',
      investigator_name: '李四',
      status: 'joined',
      is_ready: true,
    },
  ],
};

interface FetchResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

let startPayload: unknown = { ok: true };
let stageAccessFails = false;

function responseFor(url: string): FetchResponse {
  if (url.endsWith('/start')) {
    const ok = Boolean((startPayload as any)?.ok);
    return { ok, status: ok ? 200 : 409, json: async () => startPayload };
  }
  if (url.includes('/stage-access')) {
    return stageAccessFails
      ? { ok: false, status: 403, json: async () => ({}) }
      : { ok: true, status: 200, json: async () => ({ stage_token: 'stage-token-1' }) };
  }
  if (url.includes('/hud')) {
    return { ok: false, status: 404, json: async () => ({}) };
  }
  if (url.endsWith('/scenario-options')) {
    return { ok: true, status: 200, json: async () => ({ scenarios: [] }) };
  }
  if (url.endsWith('/api/rooms/room-1')) {
    return { ok: true, status: 200, json: async () => roomBody };
  }
  return { ok: false, status: 404, json: async () => ({}) };
}

// ── mount harness ────────────────────────────────────────────────────

let root: Root;
let container: HTMLDivElement;
const locationTarget = {
  protocol: 'http:',
  host: 'localhost:3000',
  href: '',
} as { protocol: string; host: string; href: string };

async function flushAsync() {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

function clickStart() {
  const startButton = Array.from(container.querySelectorAll('button'))
    .find((button) => button.textContent?.includes('开始游戏'));
  expect(startButton).toBeTruthy();
  act(() => startButton!.click());
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  startPayload = { ok: true };
  stageAccessFails = false;
  locationTarget.href = '';
  vi.stubGlobal('WebSocket', WebSocketStub);
  vi.stubGlobal('fetch', vi.fn(async (url: string) => responseFor(url)));
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: locationTarget,
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  // Restore the real location descriptor for later tests in this file.
  Object.defineProperty(window, 'location', { configurable: true, value: locationTarget });
});

// ── tests ────────────────────────────────────────────────────────────

describe('HostLobby Session Zero readiness', () => {
  test('structured missing items render readable player entries, never [object Object]', async () => {
    startPayload = {
      detail: {
        code: 'AI_ONLY_SESSION_ZERO_INCOMPLETE',
        missing: [
          { character_id: 'char-1', missing: ['character_rules', 'safety', 'connection'] },
        ],
      },
    };

    act(() => root.render(<HostLobby roomId="room-1" />));
    await flushAsync();
    clickStart();
    await flushAsync();

    const text = container.textContent || '';
    expect(text).toContain('张三');
    expect(text).toContain('角色规则确认');
    expect(text).toContain('安全边界确认');
    expect(text).toContain('连接与设备确认');
    expect(text).not.toContain('[object Object]');
  });

  test('ai_only room never offers force start or host offline policy controls', async () => {
    act(() => root.render(<HostLobby roomId="room-1" />));
    await flushAsync();

    const text = container.textContent || '';
    expect(text).not.toContain('强制开始');
    expect(text).not.toContain('Host 计划离线策略');
  });

  test('successful start navigates to the host console even when Stage token fails', async () => {
    stageAccessFails = true;
    act(() => root.render(<HostLobby roomId="room-1" />));
    await flushAsync();
    clickStart();
    await flushAsync();

    expect(locationTarget.href).toBe('/host/room-1/console');
    expect(locationTarget.href).not.toContain('/stage');
  });

  test('legacy string start errors still render as plain text', async () => {
    startPayload = { detail: '自定义字符串错误' };
    act(() => root.render(<HostLobby roomId="room-1" />));
    await flushAsync();
    clickStart();
    await flushAsync();

    expect(container.textContent).toContain('自定义字符串错误');
  });
});
