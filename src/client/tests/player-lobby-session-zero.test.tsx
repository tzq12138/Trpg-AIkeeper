// @vitest-environment jsdom
/**
 * Mount-level coverage for the Session Zero panel inside PlayerLobby (B2).
 *
 * These tests render the real component tree into a jsdom document and drive
 * the actual useEffect / state flow: load, confirm-then-re-read, load failure
 * with retry, and a stale-contract confirm failure. API modules are mocked so
 * the tests observe the request sequence rather than the network.
 */
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import type { SessionZeroDTO } from '../src/shared/types';

// jsdom does not implement scrollIntoView; the lobby chat auto-scroll needs it.
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || (() => {});

// Silences the "environment is not configured to support act(...)" warning.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ── mocks ────────────────────────────────────────────────────────────

vi.mock('../src/shared/player-api', () => ({
  getSessionZero: vi.fn(),
  confirmSessionZero: vi.fn(),
}));

vi.mock('../src/shared/api', () => ({
  apiFetch: vi.fn(async (url: string) => {
    if (url === '/api/player/character') {
      return {
        character_id: 'char-1',
        is_ready: false,
        status: 'joined',
        room_status: 'lobby',
        runtime_integrity: { status: 'healthy' },
      };
    }
    if (url.includes('/join-info')) {
      return {
        room_id: 'room-1',
        room_status: 'lobby',
        scenario_title: '玻璃雨夜',
        players: [],
      };
    }
    throw new Error(`unexpected apiFetch url: ${url}`);
  }),
  authHeaders: () => ({}),
}));

vi.mock('../src/shared/identity', () => ({
  getSlotValue: () => '',
}));

vi.mock('../src/shared/ws', () => ({
  PlayerWS: class {
    onStatus() {}
    onEvent() {}
    connect() {}
    disconnect() {}
  },
}));

import * as playerApi from '../src/shared/player-api';
import PlayerLobby from '../src/pages/PlayerLobby';

const getSessionZeroMock = vi.mocked(playerApi.getSessionZero);
const confirmSessionZeroMock = vi.mocked(playerApi.confirmSessionZero);

function stepsDto(confirmedSteps: string[]): SessionZeroDTO {
  const allSteps = ['character_rules', 'safety', 'ai_host', 'private_data', 'connection'];
  return {
    steps: allSteps.map((step) => ({
      step,
      confirmed: confirmedSteps.includes(step),
      confirmed_at: confirmedSteps.includes(step) ? '2026-09-05T00:00:00Z' : null,
    })),
    complete: confirmedSteps.length === allSteps.length,
    risk_contract: null,
  };
}

const notConfirmed = stepsDto([]);
const allConfirmed = stepsDto([
  'character_rules',
  'safety',
  'ai_host',
  'private_data',
  'connection',
]);

// ── mount harness ────────────────────────────────────────────────────

let root: Root;
let container: HTMLDivElement;

async function flushAsync() {
  // Settle promise chains started by effects/click handlers.
  for (let i = 0; i < 5; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

function confirmButton(labelText: string): HTMLButtonElement | undefined {
  const buttons = Array.from(container.querySelectorAll('button'));
  return buttons.find((button) => button.textContent?.includes(labelText));
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  getSessionZeroMock.mockReset();
  confirmSessionZeroMock.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

// ── tests ────────────────────────────────────────────────────────────

describe('PlayerLobby Session Zero', () => {
  test('loads and renders the Session Zero panel for a new joiner', async () => {
    getSessionZeroMock.mockResolvedValue(notConfirmed);

    act(() => root.render(<PlayerLobby roomId="room-1" />));
    await flushAsync();

    expect(container.textContent).toContain('Session Zero');
    expect(container.textContent).toContain('确认当前版本');
    expect(getSessionZeroMock).toHaveBeenCalledTimes(1);
  });

  test('confirming a step calls confirm then re-reads server state', async () => {
    getSessionZeroMock
      .mockResolvedValueOnce(notConfirmed)
      .mockResolvedValueOnce(allConfirmed);
    confirmSessionZeroMock.mockResolvedValue(undefined);

    act(() => root.render(<PlayerLobby roomId="room-1" />));
    await flushAsync();

    const firstButton = confirmButton('确认当前版本');
    expect(firstButton).toBeTruthy();
    act(() => firstButton!.click());
    await flushAsync();

    expect(confirmSessionZeroMock).toHaveBeenCalledWith('character_rules', undefined);
    // Re-read after confirm, and the panel now shows the completed state.
    expect(getSessionZeroMock).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain('Session Zero 已完成');
  });

  test('load failure shows the error and retry re-loads the panel', async () => {
    getSessionZeroMock
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(notConfirmed);

    act(() => root.render(<PlayerLobby roomId="room-1" />));
    await flushAsync();

    expect(container.textContent).toContain('安全边界确认暂时无法加载，请重试。');

    const retry = confirmButton('重试加载');
    expect(retry).toBeTruthy();
    act(() => retry!.click());
    await flushAsync();

    expect(getSessionZeroMock).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain('确认当前版本');
  });

  test('stale contract confirm failure keeps panel usable and re-syncs', async () => {
    getSessionZeroMock
      .mockResolvedValueOnce(notConfirmed)
      .mockResolvedValueOnce(notConfirmed);
    confirmSessionZeroMock.mockRejectedValue(new Error('409 stale contract'));

    act(() => root.render(<PlayerLobby roomId="room-1" />));
    await flushAsync();

    const firstButton = confirmButton('确认当前版本');
    act(() => firstButton!.click());
    await flushAsync();

    expect(container.textContent).toContain('安全边界版本已更新，或前置步骤尚未完成');
    // The failed confirm still triggers a server re-sync.
    expect(getSessionZeroMock).toHaveBeenCalledTimes(2);
    // Unconfirmed steps remain actionable for retry.
    expect(container.textContent).toContain('确认当前版本');
  });
});
