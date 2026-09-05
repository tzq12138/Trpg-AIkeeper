import { describe, expect, it } from 'vitest';
import { formatAdminApiErrorDetail } from '../shared/admin-api-error';
import { toggleSelectedResource } from '../shared/admin-resource-selection';

describe('formatAdminApiErrorDetail', () => {
  it('renders structured publish blockers as a readable message', () => {
    expect(formatAdminApiErrorDetail({
      status: 'review_incomplete',
      message: '审核草稿仍有未处理的核心质量问题，不能发布',
      issues: [
        { message: '6个NPC缺少npc_id' },
        { message: '未定义防剧透边界' },
      ],
    })).toBe('审核草稿仍有未处理的核心质量问题，不能发布：6个NPC缺少npc_id；未定义防剧透边界');
  });
});

describe('toggleSelectedResource', () => {
  it('keeps bulk selections unique and removable', () => {
    expect(toggleSelectedResource(['room-a'], 'room-b', true)).toEqual(['room-a', 'room-b']);
    expect(toggleSelectedResource(['room-a', 'room-b'], 'room-a', false)).toEqual(['room-b']);
  });
});
