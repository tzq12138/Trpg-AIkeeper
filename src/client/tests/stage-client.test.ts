import { describe, expect, test } from 'vitest';
import {
  buildStageClientHeaders,
  buildStageClientUrl,
} from '../src/shared/stage-client';

describe('StageClient credentials', () => {
  test('uses a distinct read-only header and a fragment-scoped stage URL', () => {
    expect(buildStageClientHeaders('stage-secret')).toEqual({
      'X-Stage-Token': 'stage-secret',
    });
    expect(buildStageClientUrl('room-1', 'stage-secret')).toBe(
      '/host/room-1/stage#stage_token=stage-secret',
    );
  });
});
