import { useState, useEffect } from 'react';
import { getSlotValue } from '../shared/identity';

interface RoomData {
  room_id: string;
  status: string;
  scenario_id: string | null;
}

interface PlayerInfo {
  character_id: string;
  player_name: string;
  investigator_name: string;
  is_ready: boolean;
}

interface HUDResponse {
  room_id: string;
  players: Array<{
    character_id: string;
    characterId?: string;
    player_name: string;
    investigator_name?: string;
    playerName?: string;
    investigatorName?: string;
    hp: number;
    hp_max: number;
    san: number;
    san_max: number;
  }>;
  scene_image_url: string | null;
  engine_state: string;
  queue_status: { normal: number; urgent: number };
}

export default function HostLobby({ roomId }: { roomId: string }) {
  const [room, setRoom] = useState<RoomData | null>(null);
  const [players, setPlayers] = useState<PlayerInfo[]>([]);
  const [scenarioTitle, setScenarioTitle] = useState<string | null>(null);
  const [scenarioOptions, setScenarioOptions] = useState<any[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [savingScenario, setSavingScenario] = useState(false);

  const loadRoom = () => {
    fetch(`/api/rooms/${roomId}`)
      .then((r) => r.json())
      .then((data) => {
        setRoom(data);
        if (data.scenario_title) {
          setScenarioTitle(data.scenario_title);
        } else if (data.scenario_id) {
          setScenarioTitle(data.scenario_id);
        }
      })
      .catch(() => {});
  };

  useEffect(() => { loadRoom(); }, [roomId]);

  const loadScenarioOptions = () => {
    fetch(`/api/rooms/${roomId}/scenario-options`, {
      headers: { 'X-Owner-Token': getSlotValue('owner_token') || '' },
    })
      .then((r) => r.json())
      .then((d) => { setScenarioOptions(d.scenarios || []); setSelectedScenarioId(room?.scenario_id || ''); })
      .catch(() => {});
  };

  const saveScenario = async () => {
    if (!selectedScenarioId) return;
    setSavingScenario(true);
    try {
      const res = await fetch(`/api/rooms/${roomId}/scenario`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': getSlotValue('owner_token') || '' },
        body: JSON.stringify({ scenario_id: selectedScenarioId }),
      });
      if (res.ok) {
        const updated = await res.json();
        setRoom(updated);
        setScenarioTitle(updated.scenario_title || selectedScenarioId);
      }
    } catch {}
    setSavingScenario(false);
  };

  useEffect(() => {
    if (!roomId) return;
    const ws = new WebSocket(`ws://${window.location.hostname}:3001/ws?room=${roomId}&role=host`);
    ws.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data);
        if (event.type === 's2c_room_lobby_snapshot' || event.type === 's2c_host_snapshot') {
          const payload = event.payload;
          if (payload.players) {
            setPlayers(payload.players.map(normalizePlayer));
          }
        }
      } catch { /* ignore parse errors */ }
    };
    ws.onerror = () => {
      // fallback to polling on WS failure
      const poll = setInterval(() => {
        fetch(`/api/host/${roomId}/hud`)
          .then((r) => r.json())
          .then((data: HUDResponse) => {
            setPlayers(data.players.map(normalizePlayer));
          })
          .catch(() => {});
      }, 5000);
      (ws as unknown as { _poll: ReturnType<typeof setInterval> })._poll = poll;
    };
    return () => {
      const pollId = (ws as unknown as { _poll?: ReturnType<typeof setInterval> })._poll;
      if (pollId) clearInterval(pollId);
      ws.close();
    };
  }, [roomId]);

  const [startError, setStartError] = useState('');
  const [notReadyList, setNotReadyList] = useState<any[]>([]);

  const startGame = async (force?: boolean) => {
    const token = getSlotValue('owner_token') || '';
    setStartError('');
    const res = await fetch(`/api/rooms/${roomId}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
      body: JSON.stringify({ force_start: !!force }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setRoom((r) => r ? { ...r, status: 'active' } : r);
      window.location.href = `/host/${roomId}/stage`;
    } else if (data.status === 'not_ready') {
      setNotReadyList(data.not_ready_players || []);
      setStartError('有玩家未准备');
    } else {
      setStartError(data.detail || '开始失败');
    }
  };

  if (!room) return <p style={{ color: '#aaa', textAlign: 'center', marginTop: 40 }}>加载中...</p>;

  return (
    <div style={{ maxWidth: 480, margin: '0 auto', padding: 16, fontFamily: 'sans-serif' }}>
      <h2 style={{ marginBottom: 4 }}>大厅 — {roomId}</h2>
      <div style={{
        background: '#1a1a2e',
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
        color: '#ccc',
      }}>
        <div style={{ fontSize: 13, color: '#888', marginBottom: 4 }}>剧本</div>
        <div style={{ fontSize: 18, fontWeight: 'bold' }}>{scenarioTitle || '未选择剧本'}</div>
        {room?.status !== 'active' && (
          <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
            <select className="bh-input" style={{ flex: 1 }} value={selectedScenarioId}
              onChange={(e) => setSelectedScenarioId(e.target.value)}
              onFocus={() => { if (scenarioOptions.length === 0) loadScenarioOptions(); }}>
              <option value="">-- 选择剧本 --</option>
              {scenarioOptions.map((s: any) => (
                <option key={s.scenario_id} value={s.scenario_id}>{s.title}</option>
              ))}
            </select>
            <button className="bh-button bh-button--yellow" disabled={!selectedScenarioId || savingScenario}
              onClick={saveScenario}>
              {savingScenario ? '保存中...' : '保存'}
            </button>
          </div>
        )}
      </div>

      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 14, color: '#888', marginBottom: 8 }}>
          已加入玩家 ({players.length})
        </div>
        {players.length === 0 && (
          <div style={{ color: '#555', fontSize: 13, padding: '12px 0' }}>
            等待玩家加入...
          </div>
        )}
        {players.map((p) => (
          <div key={p.character_id} style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '10px 12px',
            background: 'rgba(255,255,255,0.04)',
            borderRadius: 8,
            marginBottom: 6,
          }}>
            <div style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: '#3f51b5',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 14,
              fontWeight: 'bold',
            }}>
              {p.player_name.charAt(0)}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 'bold', fontSize: 14 }}>{p.player_name}</div>
              {p.investigator_name && (
                <div style={{ color: '#777', fontSize: 12 }}>调查员：{p.investigator_name}</div>
              )}
            </div>
            <div style={{
              fontSize: 11,
              color: p.is_ready ? '#4caf50' : '#888',
              padding: '2px 8px',
              borderRadius: 4,
              background: p.is_ready ? 'rgba(76,175,80,0.15)' : 'rgba(255,255,255,0.05)',
            }}>
              {p.is_ready ? '已准备' : '未准备'}
            </div>
          </div>
        ))}
      </div>

      <div style={{
        padding: 12,
        background: 'rgba(255,255,255,0.03)',
        borderRadius: 8,
        marginBottom: 16,
        fontSize: 13,
        color: '#888',
      }}>
        <div>房间状态: <span style={{ color: '#eee' }}>{room.status === 'lobby' ? '大厅等待中' : '进行中'}</span></div>
        <div style={{ marginTop: 4 }}>房间码: <strong style={{ color: '#eee', fontSize: 20 }}>{roomId}</strong></div>
      </div>

      {room.status === 'lobby' && <>
        <button
          onClick={() => startGame()}
          disabled={players.length === 0 || !scenarioTitle}
          style={{
            width: '100%',
            padding: '14px 0',
            fontSize: 18,
            fontWeight: 'bold',
            borderRadius: 10,
            border: 'none',
            background: players.length > 0 && scenarioTitle ? '#3f51b5' : '#333',
            color: players.length > 0 && scenarioTitle ? '#fff' : '#666',
            cursor: players.length > 0 && scenarioTitle ? 'pointer' : 'not-allowed',
          }}
        >
          {!scenarioTitle ? '请先选择剧本' : players.length === 0 ? '等待玩家加入' : '开始游戏'}
        </button>
        {startError ? (
          <div style={{ marginTop: 8, padding: 8, border: '2px solid var(--bh-yellow)', background: 'var(--bh-paper)' }}>
            <p style={{ fontWeight: 700, fontSize: 13 }}>{startError}</p>
            {notReadyList.length > 0 ? (
              <>
                <p style={{ fontSize: 11, marginTop: 4 }}>未准备玩家：{notReadyList.map((p: any) => p.player_name || p.character_id).join('、')}</p>
                <button className="bh-button bh-button--yellow" style={{ marginTop: 6 }} onClick={() => startGame(true)}>强制开始</button>
              </>
            ) : null}
          </div>
        ) : null}
      </>}
      {room.status === 'active' && (
        <a href={`/host/${roomId}/stage`} style={{
          display: 'block',
          width: '100%',
          padding: '14px 0',
          fontSize: 18,
          fontWeight: 'bold',
          borderRadius: 10,
          background: '#4caf50',
          color: '#fff',
          textAlign: 'center',
          textDecoration: 'none',
        }}>
          进入舞台
        </a>
      )}
    </div>
  );
}

function normalizePlayer(p: {
  character_id?: string;
  characterId?: string;
  player_name?: string;
  playerName?: string;
  investigator_name?: string;
  investigatorName?: string;
  is_ready?: boolean;
  isReady?: boolean;
}): PlayerInfo {
  return {
    character_id: p.character_id || p.characterId || '',
    player_name: p.player_name || p.playerName || '未命名玩家',
    investigator_name: p.investigator_name || p.investigatorName || '',
    is_ready: p.is_ready ?? p.isReady ?? false,
  };
}
