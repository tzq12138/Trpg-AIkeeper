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

describe('player narrative shell components', () => {
  test('PlayerActionPage renders the action-first composer without legacy solo controls', async () => {
    const { default: PlayerActionPage } = await import('../src/pages/PlayerActionPage');
    const html = renderToStaticMarkup(<PlayerActionPage roomId="room-1" initialTab="action" />);
    const defaultHtml = renderToStaticMarkup(<PlayerActionPage roomId="room-1" />);

    expect(html).toContain('叙事对话流');
    expect(html).toContain('自然语言行动');
    expect(html).toContain('给我一些行动灵感');
    expect(html).toContain('bh-player-narrative-layout--mobile-safe');
    expect(html).toContain('data-safe-widths="360 390 430"');
    expect(html).not.toContain('targetNodeId');
    expect(html).not.toContain('secretMove');
    expect(html).not.toContain('转到条目');
    expect(html).not.toContain('原版条目');
    expect(defaultHtml).toContain('自然语言行动');
    expect(defaultHtml).toContain('本局资料');
    expect(defaultHtml).toContain('打开地图');
  });

  test('puts the narrative feed before auxiliary folded panels', async () => {
    const { NarrativeFeed, PlayerAuxiliarySidebar } = await import('../src/pages/PlayerActionPage');
    const html = renderToStaticMarkup(
      <main className="bh-player-narrative-layout bh-player-narrative-layout--mobile-safe">
        <NarrativeFeed
          items={[
            { id: 'n1', kind: 'kp_narration', text: '雾从码头漫上来。' },
            { id: 'n2', kind: 'environment_change', text: '煤气灯忽明忽暗。' },
            { id: 'n3', kind: 'open_question', text: '你接下来想调查哪里？' },
          ]}
          recoveryText="已从行动时间线恢复。"
        />
        <PlayerAuxiliarySidebar activeTab="map" />
      </main>,
    );

    expect(html.indexOf('叙事对话流')).toBeGreaterThanOrEqual(0);
    expect(html.indexOf('叙事对话流')).toBeLessThan(html.indexOf('辅助面板'));
    expect(html).toContain('雾从码头漫上来。');
    expect(html).toContain('煤气灯忽明忽暗。');
    expect(html).toContain('你接下来想调查哪里？');
    expect(html).toContain('已从行动时间线恢复。');
    expect(html).toContain('<details');
    expect(html).toContain('bh-player-narrative-layout--mobile-safe');
  });

  test('renders AI stage and recovery states from canonical progress', async () => {
    const { AiStageIndicator } = await import('../src/pages/PlayerActionPage');
    const html = renderToStaticMarkup(
      <AiStageIndicator
        progress={{ stage: 'recovering', status: 'active', label: '恢复中', detail: '连接中断后恢复裁决。' }}
      />,
    );

    expect(html).toContain('retrieving');
    expect(html).toContain('directing');
    expect(html).toContain('validating_rules');
    expect(html).toContain('narrating');
    expect(html).toContain('recovering');
    expect(html).toContain('completed');
    expect(html).toContain('连接中断后恢复裁决。');
  });

  test('manual inspiration applies text without auto-submitting', async () => {
    const { applyActionInspiration } = await import('../src/pages/PlayerActionPage');

    expect(applyActionInspiration('检查窗台上的泥印')).toEqual({
      inputText: '检查窗台上的泥印',
      shouldSubmit: false,
    });
  });

  test('ignores stale ephemeral analysis after manual preview starts', async () => {
    const { shouldApplyEphemeralAnalysis } = await import('../src/pages/PlayerActionPage');

    expect(shouldApplyEphemeralAnalysis(4, 5)).toBe(false);
    expect(shouldApplyEphemeralAnalysis(5, 5)).toBe(true);
  });

  test('turns narration completion details into visible follow-up cards', async () => {
    const { narrationFollowUpItems } = await import('../src/pages/PlayerActionPage');

    expect(narrationFollowUpItems({
      environmentChanges: ['长途车的车门在身后合上。'],
      interactableObjects: ['司机', '车顶行李架'],
      openQuestion: '你准备在车上先做什么？',
    }, 'n1')).toEqual([
      { id: 'n1-environment-0', kind: 'environment_change', text: '长途车的车门在身后合上。' },
      { id: 'n1-interactable-0', kind: 'interactable_object', text: '可交互：司机、车顶行李架' },
      { id: 'n1-question', kind: 'open_question', text: '你准备在车上先做什么？' },
    ]);
  });

  test('replaces repeated follow-up details with the latest narration event', async () => {
    const { mergeNarrationDetails } = await import('../src/pages/PlayerActionPage');

    expect(mergeNarrationDetails(
      [
        { id: 'old-environment', kind: 'environment_change', text: '你已抵达新的可见场景。' },
        { id: 'old-question', kind: 'open_question', text: '你准备先检查什么？' },
      ],
      [
        { id: 'new-environment', kind: 'environment_change', text: '你已抵达新的可见场景。' },
        { id: 'new-interactable', kind: 'interactable_object', text: '可交互：村庄小路' },
        { id: 'new-question', kind: 'open_question', text: '你想如何继续观察当前环境？' },
      ],
    )).toEqual([
      { id: 'new-environment', kind: 'environment_change', text: '你已抵达新的可见场景。' },
      { id: 'new-interactable', kind: 'interactable_object', text: '可交互：村庄小路' },
      { id: 'new-question', kind: 'open_question', text: '你想如何继续观察当前环境？' },
    ]);
  });
});
