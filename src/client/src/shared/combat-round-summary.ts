export function combatRoundSummaryText(payload: Record<string, unknown>): string | null {
  const summary = payload.combat_summary;
  if (!summary || typeof summary !== 'object') return null;
  const record = summary as Record<string, unknown>;
  const title = typeof record.title === 'string' ? record.title.trim() : '';
  const publicFacts = Array.isArray(record.public_facts)
    ? record.public_facts.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : [];
  const currentSituation = typeof record.current_situation === 'string' ? record.current_situation.trim() : '';
  const lastPublicFact = publicFacts.length ? publicFacts[publicFacts.length - 1].trim() : '';
  const finalSituation = currentSituation === lastPublicFact ? '' : currentSituation;
  const parts = [title, ...publicFacts, finalSituation].filter(Boolean);
  return parts.length ? parts.join('\n') : null;
}
