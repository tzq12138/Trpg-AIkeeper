import { describe, expect, test } from 'vitest';
import { buildHostHeaders } from '../src/shared/host-auth';

describe('host auth headers', () => {
  test('includes admin bearer token alongside owner token', () => {
    expect(buildHostHeaders('owner-1', 'account-1')).toEqual({
      'X-Owner-Token': 'owner-1',
      Authorization: 'Bearer account-1',
    });
  });

  test('adds JSON content type when requested', () => {
    expect(buildHostHeaders('', 'account-1', true)).toEqual({
      'X-Owner-Token': '',
      Authorization: 'Bearer account-1',
      'Content-Type': 'application/json',
    });
  });
});
