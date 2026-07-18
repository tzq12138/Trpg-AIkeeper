import { describe, expect, it } from 'vitest';
import { canExecuteGlobalReset } from '../src/shared/reset-workflow';

describe('canExecuteGlobalReset', () => {
  it('requires a downloaded, verified backup and explicit acknowledgement', () => {
    expect(canExecuteGlobalReset({ backupId: 'b-1', downloaded: true, verified: true, acknowledged: true })).toBe(true);
    expect(canExecuteGlobalReset({ backupId: 'b-1', downloaded: false, verified: true, acknowledged: true })).toBe(false);
    expect(canExecuteGlobalReset({ backupId: 'b-1', downloaded: true, verified: false, acknowledged: true })).toBe(false);
    expect(canExecuteGlobalReset({ backupId: '', downloaded: true, verified: true, acknowledged: true })).toBe(false);
  });
});
