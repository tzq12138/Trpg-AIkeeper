import { describe, expect, test } from 'vitest';
import { buildEncounterActions } from '../src/shared/encounter-actions';

describe('encounter action declarations', () => {
  test('binds every combat declaration to the server encounter id', () => {
    const actions = buildEncounterActions('combat', 'encounter-1');

    expect(actions).toHaveLength(6);
    expect(actions.every((action) => action.params?.encounterId === 'encounter-1')).toBe(true);
  });

  test('does not produce submit-ready actions without an encounter id', () => {
    expect(buildEncounterActions('combat', '')).toEqual([]);
  });
});
