import { describe, expect, it } from 'vitest';
import { getScenarioPublishGate } from '../src/shared/scenario-publish-gate';

describe('getScenarioPublishGate', () => {
  it('blocks a quality-blocked version instead of allowing an admin override', () => {
    expect(getScenarioPublishGate('blocked')).toEqual({ blocked: true, confirmationRequired: false });
  });

  it('requires review confirmation for a non-blocked draft', () => {
    expect(getScenarioPublishGate('warning')).toEqual({ blocked: false, confirmationRequired: true });
  });
});
