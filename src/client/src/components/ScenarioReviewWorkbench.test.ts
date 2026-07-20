import { describe, expect, it } from 'vitest';
import { resolveAiDraftIssueId, summarizeReviewIssues } from '../shared/scenario-review-workbench';

describe('summarizeReviewIssues', () => {
  it('keeps unwaivable core work separate from ordinary and waived work', () => {
    const result = summarizeReviewIssues([
      { blocking: true, status: 'open' },
      { blocking: false, status: 'open' },
      { blocking: false, status: 'not_applicable' },
    ]);

    expect(result).toEqual({ total: 3, blocking: 1, open: 1, notApplicable: 1 });
  });
});

describe('resolveAiDraftIssueId', () => {
  it('uses the clicked issue instead of the stale selected issue', () => {
    expect(resolveAiDraftIssueId('spoiler-boundaries', 'missing-npc-ids')).toBe('spoiler-boundaries');
  });
});
