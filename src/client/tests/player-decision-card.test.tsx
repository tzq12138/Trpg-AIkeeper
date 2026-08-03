import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import PlayerDecisionCard from '../src/components/PlayerDecisionCard';
import type {
  ActionConsentDTO,
  ActionDraftDTO,
  ActionReceiptDTO,
  RuntimeIntegrityDTO,
} from '../src/shared/types';


const draft: ActionDraftDTO = {
  draft_id: 'draft-1',
  revision: 3,
  base_state_version: 7,
  status: 'awaiting_confirmation',
  intent_type: 'combat_action',
  declared_intent: '我向走廊里的怪物开枪。',
  params: { actionKind: 'attack' },
  understanding_summary: '你要向走廊里的怪物开枪。',
  risk: 'high',
  suggested_skill: '射击',
  alternative_skills: [],
  composite_steps: [],
  difficulty: 'regular',
  resource_impacts: [{ label: '弹药', dice: '1' }],
  visibility: 'public',
  movement_target: null,
  confirmation_requirements: ['attack', 'state_change'],
  requires_confirmation: true,
  confidence: 0.94,
  citations: [{ label: '战斗规则', page: 102, scene: null, verified: true }],
  analysis_source: 'configured_provider',
  resolution_route: 'ai',
  ephemeral: false,
};

const receipt: ActionReceiptDTO = {
  action_id: 'action-receipt-1',
  transaction_id: 'tx-1',
  state_version: 8,
  draft_id: 'draft-1',
  status: 'completed',
  declared_intent: draft.declared_intent,
  revision: 3,
  result: { final_delta: { hp: -1 } },
  timeline: [{ status: 'completed', created_at: '2026-08-02T10:00:00Z', metadata: {} }],
  can_cancel: false,
  can_review: true,
  rule_explanation: {
    authoritative_inputs: {
      skill_name: '射击',
      target: 60,
      raw_rolls: [{ dice: 'd100', result: 42 }],
      success_level: 'hard',
    },
    modifiers: { difficulty: 'regular', bonus_dice: 1 },
    hidden_sources: [{ source: 'hidden', effect: 'keeper-only monster weakness' }],
    formula: 'd100 <= 60',
    state_before: { hp: 10, luck: 40 },
    state_after: { hp: 9, luck: 40 },
    rule_set_version: 'coc7-v2',
    citations: [{ label: '战斗规则', page: 102, scene: null, verified: true }],
    verification_receipt: { receipt_id: 'roll-receipt-1', purpose: 'skill_check.initial' },
  },
};


describe('PlayerDecisionCard', () => {
  test('renders the authoritative risk confirmation', () => {
    const html = renderToStaticMarkup(<PlayerDecisionCard draft={draft} />);

    expect(html).toContain('高风险');
    expect(html).toContain('你要向走廊里的怪物开枪');
    expect(html).toContain('确认并提交');
    expect(html).toContain('草稿版本：3');
  });

  test('requires one of two or three clarification options before applying it', () => {
    const html = renderToStaticMarkup(
      <PlayerDecisionCard
        draft={{
          ...draft,
          status: 'analyzing',
          requires_confirmation: false,
          confirmation_requirements: [],
          candidate_interpretations: [
            { label: '先检查门锁', replacement_intent: '我先检查门锁。' },
            { label: '先观察窗户', replacement_intent: '我先观察窗户。' },
          ],
        }}
      />,
    );

    expect(html).toContain('先检查门锁');
    expect(html).toContain('先观察窗户');
    expect(html).toContain('disabled="">应用选择并重新分析');
    expect(html).not.toContain('确认并提交');
  });

  test('explains a forbidden private mechanical action and offers a public reproposal', () => {
    const html = renderToStaticMarkup(
      <PlayerDecisionCard
        draft={{
          ...draft,
          status: 'analyzing',
          visibility: 'private',
          params: { policyOutcome: 'reject', policyReason: 'private_mechanical_action_forbidden' },
          requires_confirmation: false,
          confirmation_requirements: [],
          candidate_interpretations: [
            { label: '公开提出前往地下室', interpreted_intent: 'public_reproposal', visibility: 'public' },
            { label: '取消行动，不产生任何效果', interpreted_intent: 'cancel_action', visibility: 'private' },
          ],
        }}
      />,
    );

    expect(html).toContain('私密机械行动不能直接改变世界状态');
    expect(html).toContain('公开提出前往地下室');
    expect(html).toContain('重新分析');
    expect(html).not.toContain('确认并提交');
  });

  test('shows accept and reject only for a server-projected affected-player consent', () => {
    const consent: ActionConsentDTO = {
      consentId: 'consent-1',
      actionId: 'pvp-action-1',
      requesterCharacterId: 'character-2',
      consentKind: 'pvp_attack',
      decision: 'pending',
      declaredIntent: '玩家二试图夺走你的钥匙。',
      expiresAt: '2026-08-02T10:05:00Z',
    };
    const pending = renderToStaticMarkup(<PlayerDecisionCard pendingConsent={consent} />);
    const rejected = renderToStaticMarkup(
      <PlayerDecisionCard consentOutcome={{ accepted: false, actionStatus: 'rejected' }} />,
    );

    expect(pending).toContain('玩家二试图夺走你的钥匙');
    expect(pending).toContain('接受影响');
    expect(pending).toContain('拒绝影响');
    expect(rejected).toContain('你已拒绝，本行动不产生机械效果');
  });

  test('renders exact luck cost and pushed-roll risk from the existing receipt', () => {
    const html = renderToStaticMarkup(
      <PlayerDecisionCard
        receipt={{
          ...receipt,
          status: 'awaiting_player_choice',
          result: {
            metadata: {
              follow_up: {
                status: 'pending',
                allowed_decisions: ['spend_luck', 'push', 'decline'],
                luck: { available: true, required: 5, current: 40 },
                push: {
                  available: true,
                  risk_level: 'high',
                  affected_scope: ['scene'],
                  warning: '再次失败会惊动整栋建筑。',
                },
                expires_at: '2026-08-02T10:05:00Z',
              },
            },
          },
        }}
      />,
    );

    expect(html).toContain('消耗 5 点幸运');
    expect(html).toContain('再次失败会惊动整栋建筑');
    expect(html).toContain('确认推骰');
    expect(html).toContain('保留原失败');
  });

  test('renders a redacted rule receipt with final delta and no hidden source text', () => {
    const html = renderToStaticMarkup(<PlayerDecisionCard receipt={receipt} />);

    expect(html).toContain('回执：action-receipt-1');
    expect(html).toContain('规则版本：coc7-v2');
    expect(html).toContain('d100 42');
    expect(html).toContain('奖励骰 1');
    expect(html).toContain('HP 9');
    expect(html).toContain('已应用 1 项隐藏机械影响');
    expect(html).not.toContain('keeper-only monster weakness');
  });

  test.each([
    [{ status: 'read_only_recovery', reasonCode: 'checkpoint_hash_mismatch' }, '只读恢复'],
    [{ status: 'paused_provider', reasonCode: 'provider_unavailable' }, 'AI 服务连续失败'],
  ] as Array<[RuntimeIntegrityDTO, string]>)('renders a mechanical pause: %s', (integrity, message) => {
    const html = renderToStaticMarkup(<PlayerDecisionCard runtimeIntegrity={integrity} />);

    expect(html).toContain(message);
    expect(html).toContain('机械行动已暂停');
  });
});
