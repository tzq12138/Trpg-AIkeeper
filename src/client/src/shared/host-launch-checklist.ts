export type HostLaunchChecklistItem = {
  key: 'scenario' | 'players' | 'ready';
  label: string;
  complete: boolean;
  detail: string;
};

export function buildHostLaunchChecklist({
  scenarioTitle,
  playerCount,
  unreadyPlayerCount,
}: {
  scenarioTitle: string;
  playerCount: number;
  unreadyPlayerCount: number;
}): HostLaunchChecklistItem[] {
  return [
    {
      key: 'scenario',
      label: '可开团剧本',
      complete: Boolean(scenarioTitle),
      detail: scenarioTitle || '请选择已发布剧本',
    },
    {
      key: 'players',
      label: '调查员加入',
      complete: playerCount > 0,
      detail: playerCount > 0 ? `${playerCount} 名调查员已加入` : '等待第一名玩家加入',
    },
    {
      key: 'ready',
      label: '玩家准备',
      complete: playerCount > 0 && unreadyPlayerCount === 0,
      detail: playerCount === 0
        ? '需要至少一名调查员'
        : unreadyPlayerCount === 0
          ? '全员已准备'
          : `${unreadyPlayerCount} 名玩家尚未准备`,
    },
  ];
}
