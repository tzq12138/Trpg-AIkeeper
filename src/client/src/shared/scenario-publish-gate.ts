export function getScenarioPublishGate(qualityLevel: string): {
  blocked: boolean;
  confirmationRequired: boolean;
} {
  return qualityLevel === 'blocked'
    ? { blocked: true, confirmationRequired: false }
    : { blocked: false, confirmationRequired: true };
}
