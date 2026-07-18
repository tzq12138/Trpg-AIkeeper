export type ReviewIssueSummaryInput = {
  blocking: boolean;
  status: string;
};

export function summarizeReviewIssues(issues: ReviewIssueSummaryInput[]) {
  return issues.reduce(
    (summary, issue) => {
      summary.total += 1;
      if (issue.status === 'not_applicable') summary.notApplicable += 1;
      else if (issue.blocking) summary.blocking += 1;
      else summary.open += 1;
      return summary;
    },
    { total: 0, blocking: 0, open: 0, notApplicable: 0 },
  );
}
