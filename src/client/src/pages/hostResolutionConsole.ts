export interface HostResolutionStep {
  kind: 'roll' | 'status_delta' | 'narrative_text';
  payload: Record<string, unknown>;
}

export interface HostResolutionConsoleItem {
  actionId: string;
  summaryText: string;
  steps: HostResolutionStep[];
  ruleExplanation: Record<string, unknown>;
}

const allowedStepKinds = new Set<HostResolutionStep['kind']>([
  'roll',
  'status_delta',
  'narrative_text',
]);

export function normalizeResolutionConsole(
  payload: { items?: unknown },
): HostResolutionConsoleItem[] {
  if (!Array.isArray(payload.items)) return [];
  return payload.items.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const record = item as Record<string, unknown>;
    const consoleData = record.hostConsole;
    if (!consoleData || typeof consoleData !== 'object') return [];
    const hostConsole = consoleData as Record<string, unknown>;
    const steps = Array.isArray(hostConsole.steps)
      ? hostConsole.steps.flatMap((step) => {
        if (!step || typeof step !== 'object') return [];
        const stepRecord = step as Record<string, unknown>;
        if (!allowedStepKinds.has(stepRecord.kind as HostResolutionStep['kind'])) return [];
        if (!stepRecord.payload || typeof stepRecord.payload !== 'object') return [];
        return [{
          kind: stepRecord.kind as HostResolutionStep['kind'],
          payload: stepRecord.payload as Record<string, unknown>,
        }];
      })
      : [];
    const ruleExplanation = record.ruleExplanation;
    return [{
      actionId: String(record.actionId || hostConsole.actionId || ''),
      summaryText: String(hostConsole.summaryText || ''),
      steps,
      ruleExplanation: ruleExplanation && typeof ruleExplanation === 'object'
        ? ruleExplanation as Record<string, unknown>
        : {},
    }];
  });
}
