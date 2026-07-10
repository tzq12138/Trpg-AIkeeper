import { describe, expect, test } from 'vitest';
import { getSkillAllocationIncrement } from '../src/components/CharSheet/SkillAllocator';

describe('getSkillAllocationIncrement', () => {
  test('uses the remaining points when fewer than five remain', () => {
    expect(getSkillAllocationIncrement(1)).toBe(1);
    expect(getSkillAllocationIncrement(4)).toBe(4);
  });

  test('caps a normal click at five points', () => {
    expect(getSkillAllocationIncrement(5)).toBe(5);
    expect(getSkillAllocationIncrement(12)).toBe(5);
  });
});
