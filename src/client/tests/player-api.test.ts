import { beforeAll, beforeEach, describe, expect, test, vi } from 'vitest';

function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    clear() { store.clear(); },
    getItem(key: string) { return store.get(key) ?? null; },
    key(index: number) { return Array.from(store.keys())[index] ?? null; },
    removeItem(key: string) { store.delete(key); },
    setItem(key: string, value: string) { store.set(key, value); },
  };
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: createStorageMock(),
    configurable: true,
  });
  Object.defineProperty(globalThis, 'sessionStorage', {
    value: createStorageMock(),
    configurable: true,
  });
});

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('player_token', 'player-token');
  vi.restoreAllMocks();
});

describe('player V2 API', () => {
  test('shares a private evidence card through the dedicated copy endpoint', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      evidence_card_id: 'party-copy-1',
      visibility: 'party',
    }), { status: 201, headers: { 'Content-Type': 'application/json' } }));
    const { shareEvidence } = await import('../src/shared/player-api');

    await shareEvidence('room-1', 'private-card-1', '给队伍的推测', '请留意馆长的停顿。');

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/rooms/room-1/evidence/private-card-1/share',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ title: '给队伍的推测', body: '请留意馆长的停顿。' }),
      }),
    );
  });

  test('adds a comment to a shared hypothesis through the dedicated endpoint', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      evidence_card_id: 'party-copy-1',
      body: '护士的证词支持这个推测。',
      author_name: '第二位调查员',
    }), { status: 201, headers: { 'Content-Type': 'application/json' } }));
    const { createEvidenceComment } = await import('../src/shared/player-api');

    await createEvidenceComment('room-1', 'party-copy-1', '护士的证词支持这个推测。');

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/rooms/room-1/evidence/party-copy-1/comments',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ body: '护士的证词支持这个推测。' }),
      }),
    );
  });

  test('analyzes an ephemeral draft without changing the payload', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      draft_id: null,
      status: 'awaiting_confirmation',
      declared_intent: '我查看门框',
      risk: 'low',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { analyzeActionDraft } = await import('../src/shared/player-api');

    await analyzeActionDraft({
      declared_intent: '我查看门框',
      intent_type: 'dialogue',
      params: {},
      ephemeral: true,
      base_state_version: 7,
    });

    expect(fetchMock).toHaveBeenCalledWith('/api/player/action-drafts/analyze', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'X-Room-Token': 'player-token',
      }),
      body: JSON.stringify({
        declared_intent: '我查看门框',
        intent_type: 'dialogue',
        params: {},
        ephemeral: true,
        base_state_version: 7,
      }),
    }));
  });

  test('records an immutable client action envelope before analysis', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      actionId: 'client-action-1',
      inputMode: 'action',
      status: 'received',
      requiresAnalysis: true,
      receivedAt: '2026-07-19T12:00:00Z',
    }), { status: 201, headers: { 'Content-Type': 'application/json' } }));
    const { receiveActionSubmission } = await import('../src/shared/player-api');

    await receiveActionSubmission({
      actionId: 'client-action-1',
      rawText: '我检查门锁。',
      inputMode: 'action',
      clientSequence: 1,
      baseStateVersion: 7,
    });

    expect(fetchMock).toHaveBeenCalledWith('/api/player/action-submissions', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'X-Room-Token': 'player-token',
        'X-Device-Id': expect.stringMatching(/^[A-Za-z0-9._:-]+$/),
      }),
      body: JSON.stringify({
        actionId: 'client-action-1',
        rawText: '我检查门锁。',
        inputMode: 'action',
        clientSequence: 1,
        baseStateVersion: 7,
      }),
    }));
  });

  test('loads the current confirmation draft after a refresh', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      draft_id: 'draft-1',
      status: 'awaiting_confirmation',
      declared_intent: '我检查车尾的行李架',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { getCurrentActionDraft } = await import('../src/shared/player-api');

    await expect(getCurrentActionDraft()).resolves.toEqual(expect.objectContaining({
      draft_id: 'draft-1',
      status: 'awaiting_confirmation',
    }));
    expect(fetchMock).toHaveBeenCalledWith('/api/player/action-drafts/current', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
    }));
  });

  test('keeps collaboration invitation creation, response, and cancellation as separate requests', async () => {
    const contract = {
      contractId: 'contract-1',
      roomId: 'room-1',
      initiatorCharacterId: 'character-1',
      sharedIntent: '我撬锁，请你警戒走廊。',
      status: 'pending',
      participantCharacterIds: ['character-1', 'character-2'],
      pendingCharacterIds: ['character-2'],
      linkedDrafts: [],
      expiresAt: '2026-07-19T22:35:00Z',
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify(contract), { status: 201, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(contract), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...contract, status: 'canceled' }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const {
      cancelCollaborationContract,
      createCollaborationContract,
      respondToCollaborationContract,
    } = await import('../src/shared/player-api');

    await createCollaborationContract('我撬锁，请你警戒走廊。', ['character-2']);
    await respondToCollaborationContract('contract-1', 'accept');
    await cancelCollaborationContract('contract-1');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/player/collaboration-contracts', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ sharedIntent: '我撬锁，请你警戒走廊。', inviteeCharacterIds: ['character-2'] }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/player/collaboration-contracts/contract-1/responses', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ decision: 'accept' }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/player/collaboration-contracts/contract-1/cancel', expect.objectContaining({
      method: 'POST',
    }));
  });

  test('keeps unfinished action submissions available to the reconnect flow', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      character: { character_id: 'character-1' },
      recent_events: [],
      pending_actions: [],
      pending_submissions: [{
        action_id: 'resume-own-action',
        input_mode: 'action',
        raw_text: '我想重新检查那扇门。',
        requested_visibility: 'public',
        client_sequence: 9,
        base_state_version: 4,
        status: 'received',
      }],
      last_sequence: 12,
      stateVersion: 4,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { reconnectPlayer } = await import('../src/shared/player-api');

    await expect(reconnectPlayer()).resolves.toEqual(expect.objectContaining({
      pending_submissions: [expect.objectContaining({
        action_id: 'resume-own-action',
        raw_text: '我想重新检查那扇门。',
      })],
    }));
    expect(fetchMock).toHaveBeenCalledWith('/api/player/reconnect', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
    }));
  });

  test('confirms a draft with a stable idempotency key', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      action_id: 'action-1',
      draft_id: 'draft-1',
      status: 'queued',
      timeline: [],
      can_cancel: true,
      can_review: false,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { confirmActionDraft } = await import('../src/shared/player-api');

    await confirmActionDraft('draft-1', ['movement'], 'confirm-draft-1');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/player/action-drafts/draft-1/confirm',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Idempotency-Key': 'confirm-draft-1',
          'X-Device-Id': expect.stringMatching(/^[A-Za-z0-9._:-]+$/),
        }),
        body: JSON.stringify({ confirmations: ['movement'] }),
      }),
    );
  });

  test('claims a stable browser device before it submits actions', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      device_id: 'device-test',
      controller: true,
      status: 'active',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { claimPlayerDevice, getPlayerDeviceId } = await import('../src/shared/player-api');

    const deviceId = getPlayerDeviceId();
    await claimPlayerDevice();

    expect(deviceId).toMatch(/^[A-Za-z0-9._:-]+$/);
    expect(fetchMock).toHaveBeenCalledWith('/api/player/device-sessions/claim', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId, takeover: false }),
    }));
  });

  test('preserves structured API error details', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'sync_required', current_state_version: 9 },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
    const { analyzeActionDraft, PlayerApiError } = await import('../src/shared/player-api');

    await expect(analyzeActionDraft({
      declared_intent: '过时行动',
      ephemeral: false,
      base_state_version: 3,
    })).rejects.toEqual(expect.objectContaining({
      name: PlayerApiError.name,
      status: 409,
      detail: { code: 'sync_required', current_state_version: 9 },
    }));
  });

  test('normalizes action hint examples to the shared hints contract', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      examples: ['检查窗台', '询问售票员', '整理线索'],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { getActionHints } = await import('../src/shared/player-api');

    await expect(getActionHints()).resolves.toEqual({
      hints: ['检查窗台', '询问售票员', '整理线索'],
    });
    expect(fetchSpy).toHaveBeenCalledWith('/api/player/action-hints', expect.objectContaining({
      method: 'POST',
    }));
  });

  test('loads and resolves a pending solo combat reaction through dedicated endpoints', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({
        reaction: {
          reactionId: 'reaction-1',
          encounterId: 'encounter-1',
          roundNumber: 1,
          attackIndex: 1,
          attackName: '爪击',
          choices: ['dodge', 'counterattack'],
          status: 'pending',
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        reaction: { reactionId: 'reaction-1', status: 'resolved' },
        result: { damageToPlayer: 0 },
        nextReaction: null,
        idempotent: false,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { getPendingEncounterReaction, resolveEncounterReaction } = await import('../src/shared/player-api');

    await expect(getPendingEncounterReaction()).resolves.toEqual(expect.objectContaining({
      reaction: expect.objectContaining({ reactionId: 'reaction-1' }),
    }));
    await resolveEncounterReaction('reaction-1', 'dodge');

    expect(fetchSpy).toHaveBeenNthCalledWith(1, '/api/player/encounter-reactions/pending', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
    }));
    expect(fetchSpy).toHaveBeenNthCalledWith(2, '/api/player/encounter-reactions/reaction-1/resolve', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ choice: 'dodge' }),
    }));
  });

  test('declares an explicit idle combat round without sending tactical details', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      status: 'declared_idle',
      turnId: 'combat-turn-1',
      actionId: 'idle-action-1',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { declareCombatRoundIdle } = await import('../src/shared/player-api');

    await expect(declareCombatRoundIdle()).resolves.toEqual({
      status: 'declared_idle',
      turnId: 'combat-turn-1',
      actionId: 'idle-action-1',
    });
    expect(fetchSpy).toHaveBeenCalledWith('/api/player/combat-round/idle', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
    }));
  });

  test('uses the explicit preview, confirmation, explanation and reopen contracts for party questions', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ question: { evidence_card_id: 'question-1' } }), { status: 200 }))
      .mockResolvedValue(new Response(JSON.stringify({ card: { evidence_card_id: 'question-1', question_status: 'closed' } }), { status: 200 }))
      .mockResolvedValue(new Response(JSON.stringify({ card: { evidence_card_id: 'question-1', question_status: 'explained' } }), { status: 200 }))
      .mockResolvedValue(new Response(JSON.stringify({ card: { evidence_card_id: 'question-1', question_status: 'investigating' } }), { status: 200 }));
    const {
      previewPartyQuestionClose,
      closePartyQuestion,
      markPartyQuestionExplained,
      reopenPartyQuestion,
    } = await import('../src/shared/player-api');

    await previewPartyQuestionClose('room-1', 'question-1');
    await closePartyQuestion('room-1', 'question-1');
    await markPartyQuestionExplained('room-1', 'question-1');
    await reopenPartyQuestion('room-1', 'question-1');

    expect(fetchSpy).toHaveBeenNthCalledWith(1, '/api/rooms/room-1/evidence/question-1/question-close-preview', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
    }));
    expect(fetchSpy).toHaveBeenNthCalledWith(2, '/api/rooms/room-1/evidence/question-1/question-close', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
    }));
    expect(fetchSpy).toHaveBeenNthCalledWith(3, '/api/rooms/room-1/evidence/question-1/question-explanation', expect.objectContaining({ method: 'POST' }));
    expect(fetchSpy).toHaveBeenNthCalledWith(4, '/api/rooms/room-1/evidence/question-1/question-reopen', expect.objectContaining({ method: 'POST' }));
  });

  test('uses explicit player-controlled status and revert contracts for shared hypotheses', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({
        card: { evidence_card_id: 'hypothesis-1', hypothesis_status: 'disproved' },
        undo_available: true,
        changed: true,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        card: { evidence_card_id: 'hypothesis-1', hypothesis_status: 'discussing' },
        undo_available: false,
        changed: true,
      }), { status: 200 }));
    const { updateSharedHypothesisStatus, revertSharedHypothesisStatus } = await import('../src/shared/player-api');

    await updateSharedHypothesisStatus('room-1', 'hypothesis-1', 'disproved');
    await revertSharedHypothesisStatus('room-1', 'hypothesis-1');

    expect(fetchSpy).toHaveBeenNthCalledWith(1, '/api/rooms/room-1/evidence/hypothesis-1/hypothesis-status', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ hypothesis_status: 'disproved' }),
    }));
    expect(fetchSpy).toHaveBeenNthCalledWith(2, '/api/rooms/room-1/evidence/hypothesis-1/hypothesis-status/revert', expect.objectContaining({
      method: 'POST',
    }));
  });

  test('requests an AI disproof suggestion without sending a status update', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      suggestion: { suggestedStatus: 'possible_disproved', factIds: ['fact-1'] },
      reason: null,
    }), { status: 200 }));
    const { suggestSharedHypothesisDisproof } = await import('../src/shared/player-api');

    await suggestSharedHypothesisDisproof('room-1', 'hypothesis-1');

    expect(fetchSpy).toHaveBeenCalledWith('/api/rooms/room-1/evidence/hypothesis-1/hypothesis-disproof-suggestion', expect.objectContaining({
      method: 'POST',
    }));
  });

  test('loads a detail and creates a private note linked to the viewed evidence', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ summary: { evidence_card_id: 'clue-1' } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ note_id: 'note-1', visibility: 'private' }), { status: 201 }));
    const { getEvidenceDetail, createEvidenceNote } = await import('../src/shared/player-api');

    await getEvidenceDetail('room-1', 'clue-1');
    await createEvidenceNote('room-1', 'clue-1', '我的判断', '先检查地下室入口。');

    expect(fetchSpy).toHaveBeenNthCalledWith(1, '/api/rooms/room-1/evidence/clue-1/detail', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
    }));
    expect(fetchSpy).toHaveBeenNthCalledWith(2, '/api/rooms/room-1/evidence/clue-1/notes', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ title: '我的判断', body: '先检查地下室入口。' }),
    }));
  });

  test('loads the safe combat declaration projection for the current player', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      hasCombat: true,
      encounterId: 'combat-1',
      roundNumber: 2,
      phase: 'declaration',
      turnId: 'turn-2',
      declaration: { submitted: false, locked: false, submittedCount: 1, totalPlayers: 4 },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { getPlayerCombatRound } = await import('../src/shared/player-api');

    await expect(getPlayerCombatRound()).resolves.toEqual(expect.objectContaining({
      hasCombat: true,
      declaration: expect.objectContaining({ totalPlayers: 4 }),
    }));
    expect(fetchSpy).toHaveBeenCalledWith('/api/player/combat-round', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
    }));
  });

  test('loads and updates the documented absence policy through player settings', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({
        room_id: 'room-1',
        character_id: 'character-1',
        draft_analysis_enabled: true,
        absent_policy: 'idle',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        room_id: 'room-1',
        character_id: 'character-1',
        draft_analysis_enabled: true,
        absent_policy: 'maintain_existing',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { getPlayerSettings, updatePlayerSettings } = await import('../src/shared/player-api');

    await expect(getPlayerSettings()).resolves.toEqual(expect.objectContaining({
      absent_policy: 'idle',
    }));
    await expect(updatePlayerSettings({ absent_policy: 'maintain_existing' })).resolves.toEqual(
      expect.objectContaining({ absent_policy: 'maintain_existing' }),
    );

    expect(fetchSpy).toHaveBeenNthCalledWith(1, '/api/player/settings', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
    }));
    expect(fetchSpy).toHaveBeenNthCalledWith(2, '/api/player/settings', expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ absent_policy: 'maintain_existing' }),
    }));
  });

  test('updates a private note through the owner-only patch route', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      note_id: 'note-1',
      title: '修订后的推测',
      body: '新的私密内容。',
      visibility: 'private',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { updatePlayerNote } = await import('../src/shared/player-api');

    await expect(updatePlayerNote('note-1', '修订后的推测', '新的私密内容。')).resolves.toEqual(
      expect.objectContaining({ note_id: 'note-1', visibility: 'private' }),
    );
    expect(fetchSpy).toHaveBeenCalledWith('/api/player/notes/note-1', expect.objectContaining({
      method: 'PATCH',
      headers: expect.objectContaining({ 'X-Room-Token': 'player-token' }),
      body: JSON.stringify({ title: '修订后的推测', body: '新的私密内容。' }),
    }));
  });
});
