function getIssueMessage(issue: unknown) {
  if (typeof issue === 'string') return issue;
  if (!issue || typeof issue !== 'object') return '';
  const record = issue as Record<string, unknown>;
  for (const key of ['message', 'title', 'code']) {
    if (typeof record[key] === 'string' && record[key].trim()) return record[key].trim();
  }
  return '';
}

export function formatAdminApiErrorDetail(detail: unknown, fallback = '操作失败，请稍后重试') {
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (!detail || typeof detail !== 'object') return fallback;

  const record = detail as Record<string, unknown>;
  const message = typeof record.message === 'string' ? record.message.trim() : '';
  const issues = Array.isArray(record.issues)
    ? record.issues.map(getIssueMessage).filter(Boolean).slice(0, 3)
    : [];
  if (message && issues.length) return `${message}：${issues.join('；')}`;
  return message || issues.join('；') || fallback;
}
