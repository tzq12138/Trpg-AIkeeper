import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import AbsentPolicyControl from '../src/components/AbsentPolicyControl';

describe('AbsentPolicyControl', () => {
  test('explains both documented policies without suggesting autonomous tactics', () => {
    const html = renderToStaticMarkup(
      <AbsentPolicyControl policy="idle" onChange={() => {}} />,
    );

    expect(html).toContain('缺席策略');
    expect(html).toContain('本轮暂不主动行动');
    expect(html).toContain('维持既有持续行为');
    expect(html).toContain('不会自动攻击、选目标、花资源或承担额外风险');
    expect(html).toContain('aria-pressed="true"');
  });
});
