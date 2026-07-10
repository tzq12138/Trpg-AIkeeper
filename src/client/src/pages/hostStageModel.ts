export interface PlayerStatus {
  character_id: string;
  player_name: string;
  investigator_name: string;
  hp: number;
  hp_max: number;
  san: number;
  san_max: number;
  mp: number;
  mp_max: number;
  luck: number;
  status_tags: string[];
}

export interface HUDData {
  room_id: string;
  players: PlayerStatus[];
  scene_image_url: string | null;
  engine_state: string;
  queue_status: { normal: number; urgent: number };
}

export function normalizeHud(raw: Record<string, unknown>): HUDData {
  const queue = (raw.queue_status || raw.queueStatus || {}) as { normal?: number; urgent?: number };
  const players = ((raw.players as Array<Record<string, unknown>> | undefined) || []).map((player) => ({
    character_id: String(player.character_id || player.characterId || ''),
    player_name: String(player.player_name || player.playerName || '未命名玩家'),
    investigator_name: String(player.investigator_name || player.investigatorName || ''),
    hp: Number(player.hp || 0),
    hp_max: Number(player.hp_max ?? player.hpMax ?? 0),
    san: Number(player.san || 0),
    san_max: Number(player.san_max ?? player.sanMax ?? 0),
    mp: Number(player.mp || 0),
    mp_max: Number(player.mp_max ?? player.mpMax ?? 0),
    luck: Number(player.luck || 0),
    status_tags: (player.status_tags || player.statusTags || []) as string[],
  }));
  return {
    room_id: String(raw.room_id || raw.roomId || ''),
    players,
    scene_image_url: (raw.scene_image_url ?? raw.sceneImageUrl ?? null) as string | null,
    engine_state: String(raw.engine_state || raw.engineState || 'idle'),
    queue_status: {
      normal: Number(queue.normal || 0),
      urgent: Number(queue.urgent || 0),
    },
  };
}
