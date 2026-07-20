const TARGET_HEADER = /^\[本轮行动 · 目标：([^\]\r\n]+)\](?:\r?\n)?/;
const MAX_TARGET_TAGS = 2;

function splitCombatTargetDraft(inputText: string): { targetTags: string[]; body: string } {
  const match = inputText.match(TARGET_HEADER);
  if (!match) return { targetTags: [], body: inputText };
  const targetTags = match[1]
    .split('、')
    .map((label) => label.trim())
    .filter((label, index, labels) => Boolean(label) && labels.indexOf(label) === index)
    .slice(0, MAX_TARGET_TAGS);
  return { targetTags, body: inputText.slice(match[0].length) };
}

export function getCombatTargetTags(inputText: string): string[] {
  return splitCombatTargetDraft(inputText).targetTags;
}

export function isCombatTargetOnlyDraft(inputText: string): boolean {
  const { targetTags, body } = splitCombatTargetDraft(inputText);
  return targetTags.length > 0 && !body.trim();
}

export function toggleCombatTargetTag(
  inputText: string,
  targetLabel: string,
): { inputText: string; targetTags: string[]; changed: boolean } {
  const label = targetLabel.trim();
  const { targetTags, body } = splitCombatTargetDraft(inputText);
  if (!label) return { inputText, targetTags, changed: false };

  const isSelected = targetTags.includes(label);
  if (!isSelected && targetTags.length >= MAX_TARGET_TAGS) {
    return { inputText, targetTags, changed: false };
  }

  const nextTags = isSelected
    ? targetTags.filter((tag) => tag !== label)
    : [...targetTags, label];
  const nextInputText = nextTags.length > 0
    ? `[本轮行动 · 目标：${nextTags.join('、')}]${body ? `\n${body}` : ''}`
    : body;
  return { inputText: nextInputText, targetTags: nextTags, changed: true };
}
