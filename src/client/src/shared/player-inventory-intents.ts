export function describeItemUse(itemName: string): string {
  return `我想使用${itemName}，并说明它在当前场景中的作用。`;
}

export function describeClueShare(clueText: string): string {
  return `我想把线索“${clueText}”分享给队伍。`;
}
