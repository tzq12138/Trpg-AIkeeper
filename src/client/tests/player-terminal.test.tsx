// @vitest-environment jsdom
import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test, vi } from 'vitest';
import PlayerTerminal from '../src/components/PlayerTerminal';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('PlayerTerminal mobile navigation', () => {
  test('renders journal identity data and keeps mobile destinations interactive', () => {
    const container = document.createElement('div');
    const root = createRoot(container);
    const onTabChange = vi.fn();
    const onToggleReady = vi.fn();

    act(() => {
      root.render(
        <PlayerTerminal
          activeTab="action"
          character={{
            character_id: 'character-1',
            player_name: '桌边玩家',
            investigator_name: '林秋',
            name: '旧版姓名',
            hp: 12,
            max_hp: 12,
            san: 45,
            max_san: 60,
            mp: 8,
            max_mp: 10,
            luck: 50,
            skills: {},
            background: '',
          }}
          onTabChange={onTabChange}
          onToggleReady={onToggleReady}
        >
          <p>内容</p>
        </PlayerTerminal>,
      );
    });

    expect(container.firstElementChild?.classList.contains('bh-player-terminal--journal')).toBe(true);
    expect(container.querySelector('.bh-player-name')?.textContent).toBe('林秋');
    expect(container.querySelector('.bh-avatar img[alt=""][aria-hidden="true"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="生命值 12/12"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="理智值 45/60"]')).not.toBeNull();

    const readyButton = Array.from(container.querySelectorAll('button'))
      .find((button) => button.textContent === '准备');
    expect(readyButton).toBeTruthy();
    act(() => readyButton!.click());
    expect(onToggleReady).toHaveBeenCalledOnce();

    const investigationButton = Array.from(container.querySelectorAll('button'))
      .find((button) => button.textContent?.includes('调查'));
    expect(investigationButton).toBeTruthy();
    act(() => investigationButton!.click());
    expect(onTabChange).toHaveBeenLastCalledWith('logs');

    const moreSummary = Array.from(container.querySelectorAll('summary'))
      .find((summary) => summary.textContent?.includes('更多'));
    expect(moreSummary).toBeTruthy();
    act(() => moreSummary!.click());
    expect((moreSummary!.parentElement as HTMLDetailsElement).open).toBe(true);

    const mapButton = Array.from(container.querySelectorAll('button'))
      .find((button) => button.textContent === '地图');
    expect(mapButton).toBeTruthy();
    act(() => mapButton!.click());
    expect(onTabChange).toHaveBeenLastCalledWith('map');

    act(() => root.unmount());
  });

  test('keeps the four documented companion destinations and folds secondary tools into more', () => {
    const html = renderToStaticMarkup(
      <PlayerTerminal
        activeTab="action"
        character={null}
        onTabChange={() => {}}
      >
        <p>内容</p>
      </PlayerTerminal>,
    );

    expect(html).toContain('aria-label="玩家手机导航"');
    expect(html).toContain('>当前<');
    expect(html).toContain('>调查<');
    expect(html).toContain('>角色<');
    expect(html).toContain('>更多<');
    expect(html).toContain('>回流<');
    expect(html).toContain('>装备<');
    expect(html).toContain('>地图<');
    expect(html).toContain('aria-label="生命值 --/--"');
    expect(html).toContain('aria-label="理智值 --/--"');
  });

  test('keeps the current priority visible outside the action page', () => {
    const html = renderToStaticMarkup(
      <PlayerTerminal
        activeTab="logs"
        character={null}
        onTabChange={() => {}}
        currentPriority={{
          kind: 'waiting',
          title: '正在裁决你的行动',
          detail: '世界状态会保持同步。',
        }}
        pendingTaskCount={3}
      >
        <p>日志内容</p>
      </PlayerTerminal>,
    );

    expect(html).toContain('当前最重要的事');
    expect(html).toContain('正在裁决你的行动');
    expect(html).toContain('另有 2 项待处理。');
    expect(html).toContain('回到当前');
    expect(html).toContain('>CASE<');
  });

  test('opens unread notifications in the investigation log', () => {
    const html = renderToStaticMarkup(
      <PlayerTerminal
        activeTab="home"
        character={null}
        onTabChange={() => {}}
        currentPriority={{
          kind: 'free_action',
          title: '查看新的私密结果',
          detail: '有 1 条仅你可见的结果等待查看。',
          targetTab: 'logs',
          notificationKind: 'private_result',
        }}
      >
        <p>回流内容</p>
      </PlayerTerminal>,
    );

    expect(html).toContain('查看记录');
  });
});
