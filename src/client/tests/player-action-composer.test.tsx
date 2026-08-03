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
  alternative_skills: [],
  composite_steps: [],
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
  transaction_id: 'tx-action-1',
  state_version: 42,
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

    expect(html).toContain('描述你现在想说或想做的事');
    expect(html).toContain('生成行动预览');
    expect(html).toContain('bh-action-composer');
  });

  test('shows explicit input modes without clearing the current text', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText="我先提醒队友注意脚印。"
        inputMode="speech"
        phase="typing"
        onInputChange={() => {}}
        onInputModeChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('行动');
    expect(html).toContain('发言');
    expect(html).toContain('队伍讨论');
    expect(html).toContain('场外信息');
    expect(html).toContain('规则问题');
    expect(html).toContain('私密笔记');
    expect(html).not.toContain('分享线索');
    expect(html).toContain('我先提醒队友注意脚印。');
    expect(html).toContain('记录发言');
  });

  test('disables stateful input during an anonymous safety pause', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText="我继续调查"
        inputMode="action"
        phase="typing"
        safetyPaused
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('textarea');
    expect(html).toContain('disabled');
  });

  test('disables mechanical input while the server runtime is paused', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText="我继续调查"
        inputMode="action"
        phase="typing"
        runtimeIntegrity={{ status: 'paused_provider', reasonCode: 'provider_unavailable' }}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('AI 服务连续失败');
    expect(html).toContain('textarea');
    expect(html).toContain('disabled');
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
    expect(html).toContain('结果不会在确认前写入世界状态');
    expect(html).toContain('放弃草稿');
  });

  test('renders the player-safe intent contract in the confirmation preview', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText={highRiskDraft.declared_intent}
        phase="analyzing"
        draft={{
          ...highRiskDraft,
          status: 'analyzing',
          requires_confirmation: false,
          confirmation_requirements: [],
          intent_contract: {
            target: '门后的怪物',
            method: '射击',
            object: null,
            constraints: [],
            resources: [],
            conditions: ['如果怪物靠近'],
            visibility: 'public',
            ambiguities: ['目标距离待确认'],
          },
        }}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('目标');
    expect(html).toContain('门后的怪物');
    expect(html).toContain('方法');
    expect(html).toContain('如果怪物靠近');
    expect(html).toContain('待澄清');
    expect(html).toContain('修改描述');
  });

  test('requires an explicit choice when AI offers alternative skills', () => {
    const draft = {
      ...highRiskDraft,
      suggested_skill: '侦查',
      alternative_skills: ['图书馆使用'],
    } as ActionDraftDTO & { alternative_skills: string[] };
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText={draft.declared_intent}
        phase="awaiting_confirmation"
        draft={draft}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('选择采用的技能');
    expect(html).toContain('侦查');
    expect(html).toContain('图书馆使用');
    expect(html).toContain('bh-button bh-button--yellow" type="button" disabled="">确认并提交');
  });

  test('renders a two-step composite declaration and its fixed failure policy', () => {
    const draft: ActionDraftDTO = {
      ...highRiskDraft,
      composite_steps: [
        {
          step_id: 'step_1',
          summary: '朝走廊中的人影开枪',
          declared_intent: '朝走廊中的人影开枪',
          intent_type: 'combat_action',
          params: { actionKind: 'attack' },
          execution_condition: 'always',
          on_previous_failure: 'cancel',
        },
        {
          step_id: 'step_2',
          summary: '掩护安娜退向北侧铁门',
          declared_intent: '掩护安娜退向北侧铁门',
          intent_type: 'move',
          params: { targetNodeId: 'north-door' },
          execution_condition: 'previous_step_success',
          on_previous_failure: 'ask',
        },
      ],
    };
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText={draft.declared_intent}
        phase="awaiting_confirmation"
        draft={draft}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('组合行动（同一回合，仅消耗一次行动）');
    expect(html).toContain('朝走廊中的人影开枪');
    expect(html).toContain('掩护安娜退向北侧铁门');
    expect(html).toContain('仅在第一步成功时执行；第一步失败时：询问你是否继续');
    expect(html).toContain('调整顺序');
  });

  test('renders teammate-only dependency controls for a collaboration confirmation', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText={highRiskDraft.declared_intent}
        phase="awaiting_confirmation"
        draft={{
          ...highRiskDraft,
          params: {
            collaborationContractId: 'contract-1',
            dependsOnCharacterIds: ['character-ben'],
          },
          visibility: 'party',
        }}
        collaborationParticipants={[
          { characterId: 'character-ada', playerName: 'Ada' },
          { characterId: 'character-ben', playerName: 'Ben' },
        ]}
        currentCharacterId="character-ada"
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
        onUpdateCollaborationDependencies={() => {}}
      />,
    );

    expect(html).toContain('协同行动顺序');
    expect(html).toContain('等待 Ben 的行动');
    expect(html).not.toContain('等待 Ada 的行动');
    expect(html).toContain('checked=""');
  });

  test('offers a player-controlled continuation after a composite first-stage failure', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText=""
        phase="awaiting_player_choice"
        receipt={{
          ...receipt,
          status: 'awaiting_player_choice',
          result: {
            metadata: {
              composite_action: {
                awaiting_choice: {
                  step_id: 'step_2',
                  question: '第一步未成功，仍要继续下一步吗？',
                },
              },
            },
          },
        }}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
        onResolveCompositeChoice={() => {}}
      />,
    );

    expect(html).toContain('第一步未成功，仍要继续下一步吗？');
    expect(html).toContain('继续下一步');
    expect(html).toContain('到此为止');
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

  test('shows a primary-target clarification instead of silently truncating three steps', () => {
    const html = renderToStaticMarkup(
      <PlayerActionComposer
        inputText={highRiskDraft.declared_intent}
        phase="analyzing"
        draft={{
          ...highRiskDraft,
          status: 'analyzing',
          requires_confirmation: false,
          confirmation_requirements: [],
          candidate_interpretations: [{
            label: '主要事项 1：朝人影射击',
            replacement_intent: '我本回合优先朝人影射击。',
          }],
        } as ActionDraftDTO & { candidate_interpretations: Array<Record<string, string>> }}
        onInputChange={() => {}}
        onAnalyze={() => {}}
        onConfirm={() => {}}
        onDiscard={() => {}}
        onCancelAction={() => {}}
      />,
    );

    expect(html).toContain('请先选择本回合的主要事项');
    expect(html).toContain('主要事项 1：朝人影射击');
    expect(html).toContain('保留并重新分析');
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

    expect(html).toContain('已进入队列');
    expect(html).toContain('正在裁决');
    expect(html).toContain('已完成');
    expect(html).not.toContain('>queued<');
    expect(html).not.toContain('>resolving<');
    expect(html).not.toContain('>completed<');
    expect(html).toContain('d100 &lt;= 60');
    expect(html).toContain('coc7-v1');
    expect(html).toContain('技能');
    expect(html).toContain('事务：tx-action-1');
    expect(html).toContain('状态版本：42');
    expect(html).toContain('目标值');
    expect(html).toContain('难度');
    expect(html).toContain('骰点');
    expect(html).toContain('成功等级');
    expect(html).toContain('d100 42');
    expect(html).toContain('hard');
    expect(html).toContain('已应用 1 项隐藏机械影响');
    expect(html).not.toContain('1 penalty die');
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
