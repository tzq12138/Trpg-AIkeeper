import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import PlayerActionComposer from '../src/components/PlayerActionComposer';
import type { ActionDraftDTO, ActionReceiptDTO } from '../src/shared/types';


const highRiskDraft: ActionDraftDTO = {
  draft_id: 'draft-1',
  revision: 1,
  base_state_version: 7,
  status: 'awaiting_confirmation',
  intent_type: 'combat_action',
  declared_intent: '我用手枪射击怪物',
  params: { actionKind: 'attack', skillName: '射击' },
  understanding_summary: '你想发起战斗行动：射击怪物',
  risk: 'high',
  suggested_skill: '射击',
  difficulty: 'regular',
  resource_impacts: [{ kind: 'ammo', direction: 'decrease' }],
  visibility: 'public',
  movement_target: null,
  confirmation_requirements: ['attack', 'state_change'],
  requires_confirmation: true,
  confidence: 0.92,
  citations: [{ label: '规则依据', page: 4, scene: '战斗', verified: true }],
  analysis_source: 'configured_provider',
  resolution_route: 'ai',
  ephemeral: false,
};

const receipt: ActionReceiptDTO = {
  action_id: 'action-1',
  draft_id: 'draft-1',
  status: 'completed',
  declared_intent: '我用手枪射击怪物',
  revision: 1,
  result: {},
  timeline: [
    { status: 'queued', created_at: '2026-07-11T10:00:00Z', metadata: {} },
    { status: 'resolving', created_at: '2026-07-11T10:00:01Z', metadata: {} },
    { status: 'completed', created_at: '2026-07-11T10:00:02Z', metadata: {} },
  ],
  can_cancel: false,
  can_review: true,
  rule_explanation: {
    authoritative_inputs: {
      skill_name: '射击',
      skill_value: 60,
      target: 60,
      raw_rolls: [{ dice: 'd100', result: 42 }],
      success_level: 'hard',
    },
    modifiers: { difficulty: 'regular', bonus_dice: 0 },
    hidden_sources: [{ source: 'hidden', effect: '1 penalty die' }],
    formula: 'd100 <= 60',
    state_before: { luck: 40 },
    state_after: { mutations: [] },
    rule_set_version: 'coc7-v1',
    citations: [{ label: '规则依据', page: 4, scene: '战斗', verified: true }],
    verification_receipt: { action_id: 'action-1', signature: 'signed' },
  },
};


describe('PlayerActionComposer', () => {
  test('renders idle action input with mobile-safe controls', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText=""
        phase="idle"
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('描述你的行动');
    expect(html).toContain('生成行动预览');
    expect(html).toContain('bh-action-composer');
  });

  test('renders explicit high-risk confirmation preview', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText={highRiskDraft.declared_intent}
        phase="awaiting_confirmation"
        draft={highRiskDraft}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('高风险');
    expect(html).toContain(highRiskDraft.understanding_summary);
    expect(html).toContain('射击');
    expect(html).toContain('attack');
    expect(html).toContain('确认并提交');
    expect(html).toContain('放弃草稿');
  });

  test('does not render a second primary action button while the server requires clarification', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText={highRiskDraft.declared_intent}
        phase="analyzing"
        draft={{
          ...highRiskDraft,
          status: 'analyzing',
          requires_confirmation: false,
          confirmation_requirements: [],
        }}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect((html.match(/bh-button--yellow/g) || []).length).toBe(1);
  });

  test('renders authoritative timeline and expandable rule receipt', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText=""
        phase="completed"
        receipt={receipt}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('queued');
    expect(html).toContain('resolving');
    expect(html).toContain('completed');
    expect(html).toContain('d100 &lt;= 60');
    expect(html).toContain('coc7-v1');
    expect(html).toContain('技能');
    expect(html).toContain('目标值');
    expect(html).toContain('难度');
    expect(html).toContain('骰点');
    expect(html).toContain('成功等级');
    expect(html).toContain('d100 42');
    expect(html).toContain('hard');
    expect(html).toContain('隐藏来源');
    expect(html).toContain('1 penalty die');
    expect(html).toContain('依据已校验');
    expect(html).toContain('规则依据');
    expect(html).not.toContain('撤回行动');
  });

  test('redacts raw citation fields from collapsed and expanded receipts', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText=""
        phase="completed"
        receipt={{
          ...receipt,
          rule_explanation: {
            ...receipt.rule_explanation!,
            citations: [{
              label: '图书馆场景',
              page: 12,
              scene: '图书馆',
              verified: true,
              source_ref: 'secret-module.pdf#raw=keeper',
              raw: 'the murderer is hidden here',
            } as any],
          },
        }}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('依据已校验');
    expect(html).toContain('图书馆场景');
    expect(html).toContain('第 12 页');
    expect(html).not.toContain('secret-module.pdf');
    expect(html).not.toContain('murderer');
    expect(html).not.toContain('source_ref');
  });

  test('shows cancel action only when server receipt allows it', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText=""
        phase="queued"
        receipt={{ ...receipt, status: 'queued', can_cancel: true, can_review: false }}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('撤回行动');
  });
});
