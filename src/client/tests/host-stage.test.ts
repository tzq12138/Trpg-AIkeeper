import { describe, expect, test } from 'vitest';
import { normalizeHud } from '../src/pages/hostStageModel';

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
