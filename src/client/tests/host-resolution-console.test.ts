import { describe, expect, test } from 'vitest';
import { normalizeResolutionConsole } from '../src/pages/hostResolutionConsole';

describe('Host resolution console projection', () => {
  test('keeps only reviewed host steps and rule explanation', () => {
    const items = normalizeResolutionConsole({
      items: [{
        actionId: 'action-1',
        canonicalResult: { mutations: [{ path: '/hp', value: 2 }] },
        hostConsole: {
          actionId: 'action-1',
          summaryText: '走廊里的灯光熄灭了。',
          steps: [
            { kind: 'roll', payload: { roll: 42, target: 60 } },
            { kind: 'narrative_text', payload: { text: '走廊里的灯光熄灭了。' } },
            { kind: 'mutation', payload: { path: '/hp', value: 2 } },
          ],
        },
        ruleExplanation: { rulesetVersion: 'coc7-v1' },
      }],
    });

    expect(items).toEqual([{
      actionId: 'action-1',
      summaryText: '走廊里的灯光熄灭了。',
      steps: [
        { kind: 'roll', payload: { roll: 42, target: 60 } },
        { kind: 'narrative_text', payload: { text: '走廊里的灯光熄灭了。' } },
      ],
      ruleExplanation: { rulesetVersion: 'coc7-v1' },
    }]);
  });
});
