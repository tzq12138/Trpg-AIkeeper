// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import PlayerSceneHeader from '../src/components/PlayerSceneHeader';
import type { CampaignHomeDTO } from '../src/shared/types';

/// <summary>每个测试独立挂载的实际组件容器。</summary>
let container: HTMLDivElement;
/// <summary>用于更新和卸载组件的 React 根。</summary>
let root: Root;
/// <summary>只含玩家授权字段的场景样本。</summary>
const scene: NonNullable<CampaignHomeDTO['current_scene']> = {
  title: '旅馆走廊', text_preview: '门后传来轻响。', choice_count: 0,
  citation: { label: '场景', verified: true }, image_asset_id: 'scene/one',
};

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('player_token', 'test-player-token');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.stubGlobal('fetch', vi.fn());
  URL.createObjectURL = vi.fn(() => 'blob:authorized-scene');
  URL.revokeObjectURL = vi.fn();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe('player scene artwork', () => {
  test('loads artwork through the authenticated player asset endpoint', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: true, blob: async () => new Blob(['image'], { type: 'image/png' }) } as Response);
    await act(async () => root.render(<PlayerSceneHeader scene={scene} />));
    expect(fetch).toHaveBeenCalledWith('/api/player/assets/scene%2Fone', expect.objectContaining({
      headers: { 'X-Room-Token': 'test-player-token' }, signal: expect.any(AbortSignal),
    }));
    expect(container.querySelector('img')?.getAttribute('src')).toBe('blob:authorized-scene');
    expect(container.querySelector('img')?.getAttribute('alt')).toContain('旅馆走廊');
  });

  test('keeps scene text and a decorative fallback when asset access is denied', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 403 } as Response);
    await act(async () => root.render(<PlayerSceneHeader scene={scene} />));
    expect(container.textContent).toContain('旅馆走廊');
    expect(container.querySelector('img')?.getAttribute('alt')).toBe('');
    expect(container.querySelector('img')?.getAttribute('src')).not.toContain('scene%2Fone');
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  test('never shows a previous scene image while a different scene is loading', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, blob: async () => new Blob(['image'], { type: 'image/png' }) } as Response);
    await act(async () => root.render(<PlayerSceneHeader scene={scene} />));
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(() => {}));
    await act(async () => root.render(<PlayerSceneHeader scene={{ ...scene, title: '码头', image_asset_id: 'new-scene' }} />));
    expect(container.querySelector('img')?.getAttribute('src')).not.toBe('blob:authorized-scene');
    expect(container.textContent).toContain('码头');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:authorized-scene');
  });

  test('uses neutral decorative art without inventing a scene when data is absent', async () => {
    await act(async () => root.render(<PlayerSceneHeader scene={null} />));
    expect(fetch).not.toHaveBeenCalled();
    expect(container.querySelector('img')?.getAttribute('alt')).toBe('');
    expect(container.textContent).not.toContain('旅馆');
  });
});
