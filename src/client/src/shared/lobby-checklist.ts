export type PlayerLobbyChecklistItem = {
  key: 'scenario' | 'character' | 'connection' | 'ready';
  label: string;
  complete: boolean;
  detail: string;
};

export function buildPlayerLobbyChecklist({
  scenarioTitle,
  hasCharacter,
  isReady,
  isConnected,
  roomStatus,
}: {
  scenarioTitle: string;
  hasCharacter: boolean;
  isReady: boolean;
  isConnected: boolean;
  roomStatus: string;
}): PlayerLobbyChecklistItem[] {
  const gameStarted = roomStatus === 'active';
  return [
    {
      key: 'scenario',
      label: '剧本已确认',
      complete: Boolean(scenarioTitle),
      detail: scenarioTitle || '等待 Host 选择剧本',
    },
    {
      key: 'character',
      label: '角色已确认',
      complete: hasCharacter,
      detail: hasCharacter ? '可随时调整准备状态' : '等待角色加入结果',
    },
    {
      key: 'connection',
      label: '实时连接',
      complete: isConnected,
      detail: isConnected ? '连接正常' : '正在恢复连接',
    },
    {
      key: 'ready',
      label: gameStarted ? '游戏已开始' : '准备开局',
      complete: gameStarted || isReady,
      detail: gameStarted ? '可以进入 KP 叙事' : isReady ? '已通知 Host' : '确认后通知 Host',
    },
  ];
}
