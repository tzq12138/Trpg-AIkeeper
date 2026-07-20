import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';

import CollaborationContractPanel from '../src/components/CollaborationContractPanel';


describe('CollaborationContractPanel', () => {
  test('shows a shared intent invitation with explicit accept or decline actions', () => {
    const html = renderToStaticMarkup(
      <CollaborationContractPanel
        currentCharacterId="character-invitee"
        participants={[
          { characterId: 'character-initiator', playerName: '安娜' },
          { characterId: 'character-invitee', playerName: '陈默' },
        ]}
        contracts={[
          {
            contractId: 'contract-1',
            roomId: 'room-1',
            initiatorCharacterId: 'character-initiator',
            sharedIntent: '我负责撬锁，请你警戒走廊。',
            status: 'pending',
            participantCharacterIds: ['character-initiator', 'character-invitee'],
            pendingCharacterIds: ['character-invitee'],
            linkedDrafts: [],
            expiresAt: '2026-07-19T22:35:00Z',
          },
        ]}
        disabled={false}
        onCreate={() => {}}
        onRespond={() => {}}
        onCancel={() => {}}
      />,
    );

    expect(html).toContain('协同行动邀请');
    expect(html).toContain('我负责撬锁，请你警戒走廊。');
    expect(html).toContain('接受');
    expect(html).toContain('拒绝');
    expect(html).toContain('邀请队友');
  });
});
