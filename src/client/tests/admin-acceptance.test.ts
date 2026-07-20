import { describe, expect, it } from 'vitest';
import { canAccessAcceptance } from '../src/shared/admin-acceptance';

describe('canAccessAcceptance', () => {
  it('allows only administrator accounts into the acceptance center', () => {
    expect(canAccessAcceptance('admin')).toBe(true);
    expect(canAccessAcceptance('host')).toBe(false);
    expect(canAccessAcceptance(undefined)).toBe(false);
  });
});
