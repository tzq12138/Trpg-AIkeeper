import { describe, expect, it } from 'vitest';
import { SCENARIO_WORKFLOW_STEPS } from '../src/shared/scenario-workflow';

describe('SCENARIO_WORKFLOW_STEPS', () => {
  it('keeps import, review, asset binding and publish in an explicit order', () => {
    expect(SCENARIO_WORKFLOW_STEPS.map((step) => step.key)).toEqual(['import', 'review', 'assets', 'publish']);
  });
});
