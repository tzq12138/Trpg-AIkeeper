import { describe, expect, test } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { normalizeHud } from '../src/pages/hostStageModel';

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

describe('HostStage HUD normalization', () => {
  test('normalizes camelCase REST HUD payload', () => {
    const hud = normalizeHud({
      roomId: 'room-1',
      engineState: 'idle',
      sceneImageUrl: null,
      queueStatus: { normal: 2, urgent: 1 },
      players: [
        {
          characterId: 'char-1',
          playerName: 'Alice',
          investigatorName: 'Investigator',
          hp: 9,
          hpMax: 10,
          san: 45,
          sanMax: 50,
          mp: 8,
          mpMax: 10,
          luck: 50,
          statusTags: ['ready'],
        },
      ],
    });

    expect(hud.queue_status).toEqual({ normal: 2, urgent: 1 });
    expect(hud.players[0]).toMatchObject({
      character_id: 'char-1',
      player_name: 'Alice',
      hp_max: 10,
      status_tags: ['ready'],
    });
  });
});

describe('HostDirectorConsole', () => {
  test('is read-only for normal flow while keeping pause and exception takeover', async () => {
    const { HostDirectorConsole } = await import('../src/pages/HostStage');
    const html = renderToStaticMarkup(
      React.createElement(HostDirectorConsole, {
        snapshot: {
          currentScene: '码头候车室',
          confirmedFacts: ['门外有湿脚印'],
          pendingTriggers: ['玩家检查窗台'],
          aiEvidence: [{ label: '场景卡', page: 3, scene: '码头', verified: true }],
          stage: 'validating_rules',
          risks: ['SAN 风险'],
          exceptionQueue: ['规则冲突待接管'],
        },
        onPause: () => {},
        onTakeOverException: () => {},
      }),
    );

    expect(html).toContain('只读导演台');
    expect(html).toContain('码头候车室');
    expect(html).toContain('门外有湿脚印');
    expect(html).toContain('规则冲突待接管');
    expect(html).toContain('暂停');
    expect(html).toContain('异常接管');
    expect(html).not.toContain('reveal');
    expect(html).not.toContain('hide');
    expect(html).not.toContain('force move');
    expect(html).not.toContain('重置');
    expect(html).not.toContain('恢复 checkpoint');
    expect(html).not.toContain('直接裁决');
  });
});

describe('HostExceptionQueue', () => {
  test('shows only exceptional actions with auditable resolution controls', async () => {
    const { HostExceptionQueue } = await import('../src/pages/HostStage');
    const html = renderToStaticMarkup(
      React.createElement(HostExceptionQueue, {
        items: [{
          action_id: 'action-1',
          character_id: 'char-1',
          intent_type: 'unknown',
          declared_intent: '我用未知仪式改变现实。',
          status: 'awaiting_host_exception',
          created_at: '2026-07-15T10:00:00Z',
        }],
        resolvingActionId: null,
        onResolve: () => {},
      }),
    );

    expect(html).toContain('异常行动队列');
    expect(html).toContain('我用未知仪式改变现实。');
    expect(html).toContain('请求玩家澄清');
    expect(html).toContain('拒绝行动');
    expect(html).toContain('处理原因');
    expect(html).not.toContain('直接裁决');
  });
});

describe('HostStage read-only runtime surface', () => {
  test('renders runtime director stage without normal-flow mutation entries', async () => {
    const { default: HostStage } = await import('../src/pages/HostStage');
    const html = renderToStaticMarkup(React.createElement(HostStage, {
      roomId: 'room-1',
      initialTab: 'logs',
    }));

    expect(html).toContain('只读导演台');
    expect(html).toContain('暂停');
    expect(html).toContain('异常接管');
    expect(html).not.toContain('checkpoint');
    expect(html).not.toContain('检查点');
    expect(html).not.toContain('创建检查点');
    expect(html).not.toContain('恢复');
    expect(html).not.toContain('重置');
    expect(html).not.toContain('reveal');
    expect(html).not.toContain('force move');
    expect(html).not.toContain('直接裁决');
  });

  test('logs panel in director mode exposes audit timeline only', async () => {
    const { default: HostLogsPanel } = await import('../src/components/HostLogsPanel');
    const html = renderToStaticMarkup(React.createElement(HostLogsPanel, {
      roomId: 'room-1',
      readOnly: true,
    }));

    expect(html).toContain('事件时间线');
    expect(html).toContain('审计时间线');
    expect(html).not.toContain('检查点');
    expect(html).not.toContain('创建检查点');
    expect(html).not.toContain('恢复');
  });
});
