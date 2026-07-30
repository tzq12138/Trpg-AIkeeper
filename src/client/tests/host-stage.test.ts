import { describe, expect, test } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { normalizeHud } from '../src/pages/hostStageModel';
import { normalizePublicStage, normalizePublicStagePresentation } from '../src/pages/publicStageModel';

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

describe('public stage normalization', () => {
  test('accepts only the safe projection fields', () => {
    const stage = normalizePublicStage({
      roomId: 'room-1',
      sceneImageUrl: '/assets/warehouse.png',
      statusText: 'KP 正在演绎结果',
      players: [{
        characterId: 'char-1',
        playerName: 'Alice',
        investigatorName: 'Ada',
        condition: '受伤',
        conditionTone: 'warning',
      }],
      recentEvents: [{ text: '警笛靠近。', issuedAt: '2026-07-19T12:00:00Z' }],
    });

    expect(stage.players[0]).toEqual({
      character_id: 'char-1',
      player_name: 'Alice',
      investigator_name: 'Ada',
      condition: '受伤',
      condition_tone: 'warning',
    });
    expect(JSON.stringify(stage)).not.toContain('hp');
    expect(JSON.stringify(stage)).not.toContain('san');
    expect(JSON.stringify(stage)).not.toContain('queue');
  });

  test('limits a malformed public-stage payload to six player cards', () => {
    const stage = normalizePublicStage({
      roomId: 'room-1',
      players: Array.from({ length: 7 }, (_, index) => ({
        characterId: `char-${index + 1}`,
        playerName: `Player ${index + 1}`,
        investigatorName: `Investigator ${index + 1}`,
        condition: '情况稳定',
        conditionTone: 'stable',
      })),
    });

    expect(stage.players.map((player) => player.character_id)).toEqual([
      'char-1',
      'char-2',
      'char-3',
      'char-4',
      'char-5',
      'char-6',
    ]);
  });

  test('accepts only released public narration from the presentation projection', () => {
    const presentation = normalizePublicStagePresentation({
      available: true,
      version: 4,
      kind: 'narrative_text',
      narrativeText: '雨声压过了远处的汽笛。',
      actionId: 'must-not-reach-stage',
      secretRoll: 7,
      hostConsole: { hiddenReason: 'must-not-reach-stage' },
    });

    expect(presentation).toEqual({
      available: true,
      version: 4,
      kind: 'narrative_text',
      narrative_text: '雨声压过了远处的汽笛。',
    });
    expect(JSON.stringify(presentation)).not.toContain('must-not-reach-stage');
    expect(JSON.stringify(presentation)).not.toContain('secretRoll');
  });

  test('normalizes only safe live combat progress', () => {
    const stage = normalizePublicStage({
      roomId: 'room-1',
      combatRound: {
        roundNumber: 4,
        phase: 'resolution',
        submittedCount: 3,
        totalPlayers: 4,
        currentConflict: '走廊入口的争夺',
        actionIds: ['must-not-reach-stage'],
        secretTarget: '安娜',
      },
    });

    expect(stage.combat_round).toEqual({
      round_number: 4,
      phase: 'resolution',
      submitted_count: 3,
      total_players: 4,
      current_conflict: '走廊入口的争夺',
    });
    expect(JSON.stringify(stage.combat_round)).not.toContain('must-not-reach-stage');
    expect(JSON.stringify(stage.combat_round)).not.toContain('secretTarget');
  });

  test('normalizes only explicitly observed combat units', () => {
    const stage = normalizePublicStage({
      roomId: 'room-1',
      combatRound: {
        roundNumber: 4,
        phase: 'declaration',
        submittedCount: 0,
        totalPlayers: 1,
        publicUnits: [
          {
            label: '走廊中的人影',
            kind: 'observed_enemy',
            healthSegments: 3,
            condition: '重伤',
            distanceBand: 'near',
            hp: 3,
            exactInitiative: 68,
          },
          {
            label: '黑暗中的枪手',
            kind: 'observed_enemy',
            condition: '失去踪迹',
            lastObservedAt: '走廊北侧',
            currentPosition: '隐藏位置',
          },
          {
            label: '格式错误单位',
            kind: 'enemy',
            healthSegments: 8,
            condition: '满血',
          },
        ],
      },
    });

    expect(stage.combat_round?.public_units).toEqual([
      {
        label: '走廊中的人影',
        kind: 'observed_enemy',
        health_segments: 3,
        condition: '重伤',
        distance_band: 'near',
      },
      {
        label: '黑暗中的枪手',
        kind: 'observed_enemy',
        condition: '失去踪迹',
        last_observed_at: '走廊北侧',
      },
    ]);
    expect(JSON.stringify(stage.combat_round)).not.toContain('exactInitiative');
    expect(JSON.stringify(stage.combat_round)).not.toContain('currentPosition');
  });
});

describe('HostDirectorConsole', () => {
  test('is read-only for normal flow while keeping pause and exception takeover', async () => {
    const { HostDirectorConsole } = await import('../src/pages/HostConsole');
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
    const { HostExceptionQueue } = await import('../src/pages/HostConsole');
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

describe('HostProjectionRecoveryQueue', () => {
  test('offers only a saved-projection replay control without player result content', async () => {
    const { HostProjectionRecoveryQueue } = await import('../src/pages/HostConsole');
    const html = renderToStaticMarkup(
      React.createElement(HostProjectionRecoveryQueue, {
        items: [{ action_id: 'action-projection-1', character_id: 'character-1' }],
        replayingActionId: null,
        onReplay: () => {},
      }),
    );

    expect(html).toContain('投影恢复队列');
    expect(html).toContain('action-projection-1');
    expect(html).toContain('重放已保存投影');
    expect(html).toContain('不会重新裁决或改写世界状态');
  });
});

describe('HostReviewPacketQueue', () => {
  test('renders an auditable host-only review packet without receipt secrets or direct adjudication', async () => {
    const { HostReviewPacketQueue } = await import('../src/pages/HostConsole');
    const html = renderToStaticMarkup(React.createElement(HostReviewPacketQueue, {
      items: [{
        review_request_id: 'review-1',
        action_id: 'action-1',
        character_id: 'character-1',
        original_intent: '我想检查门框。',
        original_action_text: '我原本想侦查门框。',
        objection: '结算对象理解错了。',
        intent_contract: {
          intentType: 'skill_check',
          understandingSummary: '检查门框。',
          risk: 'high',
          visibility: 'party',
          confirmationRequirements: ['dice_roll'],
        },
        rule_plan: {
          ruleSetVersion: 'coc7-v1',
          authoritativeInputs: { skillName: '侦查', skillValue: 60, rawRolls: [{ result: 42 }] },
          modifiers: { difficulty: 'regular' },
          formula: 'd100 <= 60',
        },
        state_diff: { before: { san: 50 }, after: { san: 48 } },
        citations: [{ source: 'CoC7 基础规则', page: 55, location: '技能检定' }],
      }],
    }));

    expect(html).toContain('行动复核');
    expect(html).toContain('我原本想侦查门框。');
    expect(html).toContain('d100 &lt;= 60');
    expect(html).toContain('CoC7 基础规则');
    expect(html).toContain('SAN: 50 → 48');
    expect(html).not.toContain('signature');
    expect(html).not.toContain('直接裁决');
  });
});

describe('HostPresentationControls', () => {
  test('exposes playback controls without direct rule or state mutation actions', async () => {
    const { HostPresentationControls } = await import('../src/pages/HostConsole');
    const html = renderToStaticMarkup(React.createElement(HostPresentationControls, {
      state: {
        transactionId: 'transaction-1',
        currentStepIndex: 1,
        totalSteps: 3,
        paused: false,
        completed: false,
        queuedTransactions: 0,
        canSkipVisual: true,
      },
      pendingCommand: null,
      onCommand: () => {},
    }));

    expect(html).toContain('演出控制');
    expect(html).toContain('暂停演出');
    expect(html).toContain('下一步');
    expect(html).toContain('跳过视觉步骤');
    expect(html).toContain('重放公开步骤');
    expect(html).not.toContain('直接裁决');
    expect(html).not.toContain('修改 HP');
    expect(html).not.toContain('修改 SAN');
  });
});

describe('HostSafetyRequests', () => {
  test('renders an anonymous pause without exposing player identity or raw text', async () => {
    const { HostSafetyRequests } = await import('../src/pages/HostConsole');
    const html = renderToStaticMarkup(React.createElement(HostSafetyRequests, {
      items: [{
        actionId: 'safety-1',
        createdAt: '2026-07-19T00:00:00Z',
      }],
      onRefresh: () => {},
      onExtend: () => {},
      onEndSession: () => {},
    }));

    expect(html).toContain('匿名安全暂停');
    expect(html).toContain('只有触发者可以恢复');
    expect(html).not.toContain('character-1');
    expect(html).not.toContain('请淡出针头描写。');
  });
});

describe('HostStage public runtime surface', () => {
  test('renders a public projection without director controls or exact resources', async () => {
    const { default: HostStage } = await import('../src/pages/HostStage');
    const html = renderToStaticMarkup(React.createElement(HostStage, {
      roomId: 'room-1',
    }));

    expect(html).toContain('公共舞台');
    expect(html).toContain('等待调查员行动');
    expect(html).not.toContain('只读导演台');
    expect(html).not.toContain('暂停');
    expect(html).not.toContain('异常接管');
    expect(html).not.toContain('HP');
    expect(html).not.toContain('SAN');
    expect(html).not.toContain('bh-cursor');
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
