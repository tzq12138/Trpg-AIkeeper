import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import PlayerTerminal from '../src/components/PlayerTerminal';

describe('PlayerTerminal mobile navigation', () => {
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
