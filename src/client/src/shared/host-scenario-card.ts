export function getScenarioLaunchBadge({
  quality_level,
  risk_warning,
}: {
  quality_level?: string;
  risk_warning?: string;
}): { label: string; detail: string } {
  if (risk_warning || quality_level === 'warning' || quality_level === 'highRisk') {
    return { label: '可开团 · 需留意', detail: risk_warning || '该剧本带有质量警告' };
  }
  return { label: '已发布 · 可开团', detail: '版本与开团门禁已通过' };
}
