import { describe, expect, test } from 'vitest';
import {
  canSendWhileStatefulActionBusy,
  confirmationImpactSummary,
  inputModeSubmitLabel,
  recordedInputSummary,
} from '../src/shared/player-input-modes';

describe('recorded input summaries', () => {
  test('does not echo private note content into the narrative flow', () => {
    expect(recordedInputSummary('private_note', '真正的秘密')).toBe('已记录私密笔记，仅自己可见，不会进入剧情。');
  });

  test('labels non-state inputs without claiming world state changed', () => {
    expect(recordedInputSummary('speech', '我提醒大家小心。')).toBe('已记录发言，不会改变世界状态。');
    expect(recordedInputSummary('rule_question', '这算侦查吗？')).toBe('已保存规则问题，仅自己可见，不会进入剧情。');
    expect(recordedInputSummary('party_chat', '我们先走。')).toBe('已发送队伍讨论，不会自动变成角色行动。');
    expect(recordedInputSummary('ooc', '我去拿杯水。')).toBe('已发送场外信息，不会进入剧情、规则或世界状态。');
  });

  test('anonymously pauses the engine and reserves resume authority for the triggering player', () => {
    expect(inputModeSubmitLabel('safety')).toBe('发送安全请求');
    expect(recordedInputSummary('safety', '淡出针头描写')).toBe(
      '已匿名暂停引擎；只有你能恢复本次暂停，期间不会结算新的剧情行动。',
    );
  });

  test('allows non-state inputs while a formal action is resolving', () => {
    expect(canSendWhileStatefulActionBusy('action')).toBe(false);
    expect(canSendWhileStatefulActionBusy('combat_action')).toBe(false);
    expect(canSendWhileStatefulActionBusy('party_chat')).toBe(true);
    expect(canSendWhileStatefulActionBusy('ooc')).toBe(true);
    expect(canSendWhileStatefulActionBusy('rule_question')).toBe(true);
    expect(canSendWhileStatefulActionBusy('private_note')).toBe(true);
  });

  test('treats speech as a confirmed dialogue action only when the room enables it', () => {
    expect(inputModeSubmitLabel('speech')).toBe('记录发言');
    expect(inputModeSubmitLabel('speech', true)).toBe('生成对话预览');
    expect(canSendWhileStatefulActionBusy('speech')).toBe(true);
    expect(canSendWhileStatefulActionBusy('speech', true)).toBe(false);
  });

  test('explains confirmed stateful input without promising an outcome', () => {
    expect(confirmationImpactSummary('combat_action')).toBe(
      '确认后加入本轮声明；锁定后将与其他行动统一按规则结算。',
    );
    expect(confirmationImpactSummary('item_action')).toBe(
      '确认后检查物品与目标条件；只有结算成功才会应用资源变化。',
    );
    expect(confirmationImpactSummary('map_move')).toBe(
      '确认后检查路线与可见信息；必要时会进入规则检定。',
    );
    expect(confirmationImpactSummary('speech', true)).toBe(
      '确认后作为角色对话处理，不会先作为队伍讨论发送。',
    );
  });
});
