import { describe, expect, it } from 'vitest';
import { imageTargetLabel, normalizeImageSuggestion, partyVisibleImageNotice } from './scenario-review-images';

describe('scenario review image helpers', () => {
  it('keeps AI image suggestions host-only until an administrator changes visibility', () => {
    const suggestion = normalizeImageSuggestion({
      scene_id: 'cellar',
      image_summary: '潮湿石阶通向地下室。',
      prompt: '地下室氛围图。',
      citation: { source_part_id: 'part-1' },
    });

    expect(suggestion.visibility).toBe('host_only');
    expect(suggestion.target_type).toBe('scene');
    expect(suggestion.target_key).toBe('cellar');
    expect(suggestion.style).toContain('调查');
  });

  it('keeps the reviewed target type for NPC, item, and clue suggestions', () => {
    const suggestion = normalizeImageSuggestion({
      target_type: 'npc',
      target_key: 'librarian',
      image_summary: '疲惫的图书管理员。',
      prompt: '图书管理员肖像。',
      citation: { source_part_id: 'part-1' },
    });

    expect(suggestion.target_type).toBe('npc');
    expect(imageTargetLabel(suggestion.target_type)).toBe('NPC');
  });

  it('explains that party-visible images are regenerated from public scene information', () => {
    expect(partyVisibleImageNotice('party')).toContain('公开描述');
    expect(partyVisibleImageNotice('host_only')).toBe('');
  });
});
