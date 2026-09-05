import { describe, expect, it } from 'vitest';

import { getPlayerInputModePolicy } from './player-input-mode';


describe('getPlayerInputModePolicy', () => {
  it('keeps party discussion, OOC, rules, and private notes out of formal actions', () => {
    expect(getPlayerInputModePolicy('party_chat').createsFormalAction).toBe(false);
    expect(getPlayerInputModePolicy('ooc').createsFormalAction).toBe(false);
    expect(getPlayerInputModePolicy('rule_question').createsFormalAction).toBe(false);
    expect(getPlayerInputModePolicy('private_note').createsFormalAction).toBe(false);
  });

  it('requires the action pipeline for in-world action and speech modes', () => {
    expect(getPlayerInputModePolicy('action').createsFormalAction).toBe(true);
    expect(getPlayerInputModePolicy('speech').createsFormalAction).toBe(true);
  });
});
