import { useState, useEffect, useCallback } from 'react';
import { getSlotValue } from '../shared/identity';
import { buildRoomWsUrl } from '../shared/ws-url';
import HostCampaignControls from '../components/HostCampaignControls';

// ── types ──────────────────────────────────────────────────────────

interface LobbyPlayer {
  character_id: string;
  player_name: string;
  investigator_name: string;
  is_ready: boolean;
  status?: string;
}

interface RoomData {
  room_id: string;
  status: string;
  scenario_id: string | null;
  scenario_title?: string;
  players: LobbyPlayer[];
}

interface ScenarioOption {
  scenario_id: string;
  title: string;
  import_status?: string;
}

function normalizePlayer(p: Record<string, any>): LobbyPlayer {
  return {
    character_id: p.character_id || p.characterId || '',
    player_name: p.player_name || p.playerName || '未命名玩家',
    investigator_name: p.investigator_name || p.investigatorName || '',
    is_ready: p.is_ready ?? p.isReady ?? false,
    status: p.status || 'joined',
  };
}

// ── component ──────────────────────────────────────────────────────

export default function HostLobby({ roomId }: { roomId: string }) {
  const [room, setRoom] = useState<RoomData | null>(null);
  const [players, setPlayers] = useState<LobbyPlayer[]>([]);
  const [scenarioTitle, setScenarioTitle] = useState('');
  const [scenarioOptions, setScenarioOptions] = useState<ScenarioOption[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [savingScenario, setSavingScenario] = useState(false);
  const [startError, setStartError] = useState('');
  const [notReadyList, setNotReadyList] = useState<LobbyPlayer[]>([]);
  const [loading, setLoading] = useState(true);

  // ── data fetching ────────────────────────────────────────────────

  const loadRoom = useCallback(() => {
    fetch(`/api/rooms/${roomId}`)
      .then((r) => r.json())
      .then((data: RoomData) => {
        setRoom(data);
        setLoading(false);
        if (data.players) setPlayers(data.players.map(normalizePlayer));
        setScenarioTitle(data.scenario_title || '');
      })
      .catch(() => setLoading(false));
  }, [roomId]);

  useEffect(() => { loadRoom(); }, [loadRoom]);

  const loadScenarioOptions = () => {
    fetch(`/api/rooms/${roomId}/scenario-options`, {
      headers: { 'X-Owner-Token': getSlotValue('owner_token') || '' },
    })
      .then((r) => r.json())
      .then((d) => setScenarioOptions(d.scenarios || []))
      .catch(() => {});
  };

  const saveScenario = async () => {
    if (!selectedScenarioId) return;
    setSavingScenario(true);
    try {
      const res = await fetch(`/api/rooms/${roomId}/scenario`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-Owner-Token': getSlotValue('owner_token') || '',
        },
        body: JSON.stringify({ scenario_id: selectedScenarioId }),
      });
      if (res.ok) {
        const updated = await res.json();
        setScenarioTitle(updated.scenario_title || selectedScenarioId);
      }
    } catch { /* ignore */ }
    setSavingScenario(false);
  };

  // ── WebSocket with reconnect ──────────────────────────────────────

  useEffect(() => {
    const ownerToken = getSlotValue('owner_token') || '';
    if (!ownerToken) return;

    let wsRef: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = 1000;
    const maxDelay = 30000;
    let mounted = true;

    function connect() {
      if (!mounted) return;
      wsRef = new WebSocket(buildRoomWsUrl(window.location, {
        roomId,
        role: 'host',
        ownerToken,
      }));

      wsRef.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data);
          const type = event.type || event.eventType;
          if (type === 's2c_room_lobby_snapshot' || type === 's2c_host_snapshot') {
            const payload = event.payload || {};
            if (payload.players) setPlayers(payload.players.map(normalizePlayer));
          }
        } catch { /* ignore */ }
      };

      wsRef.onopen = () => {
        reconnectDelay = 1000;
      };

      wsRef.onclose = () => {
        if (!mounted) return;
        reconnectTimer = setTimeout(() => {
          connect();
          reconnectDelay = Math.min(reconnectDelay * 1.5 + Math.random() * 1000, maxDelay);
        }, reconnectDelay);
      };

      wsRef.onerror = () => {
        // onclose will fire after this, triggering reconnect
      };
    }

    connect();

    return () => {
      mounted = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef?.close();
    };
  }, [roomId]);

  // ── game start ───────────────────────────────────────────────────

  const startGame = async (force?: boolean) => {
    const token = getSlotValue('owner_token') || '';
    setStartError('');
    setNotReadyList([]);

    try {
      const res = await fetch(`/api/rooms/${roomId}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
        body: JSON.stringify({ force_start: !!force }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        window.location.href = `/host/${roomId}/stage`;
      } else if (data.status === 'not_ready') {
        setNotReadyList(data.not_ready_players || []);
        setStartError('有玩家未准备');
      } else {
        setStartError(String(data.detail || '开始失败'));
      }
    } catch {
      setStartError('网络错误');
    }
  };

  // ── derived ──────────────────────────────────────────────────────

  const ownerToken = getSlotValue('owner_token') || '';
  const unreadyPlayers = players.filter((p) => !p.is_ready);
  const canStart = players.length > 0 && !!scenarioTitle && unreadyPlayers.length === 0;

  let disabledReason = '';
  if (!scenarioTitle) disabledReason = '请先选择剧本再开始游戏';
  else if (players.length === 0) disabledReason = '等待玩家加入房间';
  else if (unreadyPlayers.length > 0)
    disabledReason = `${unreadyPlayers.length} 名玩家未准备: ${unreadyPlayers.map((p) => p.player_name).join('、')}`;

  // ── missing token ────────────────────────────────────────────────

  if (!ownerToken) {
    return (
      <div className="bh-page bh-page--narrow">
        <div className="bh-home">
          <section className="bh-panel" style={{ textAlign: 'center', padding: 40 }}>
            <span className="bh-eyebrow">HOST</span>
            <h2 className="bh-panel-title">需要房主身份</h2>
            <p className="bh-panel-desc">请从创建房间页进入，或确认当前身份拥有房主权证。</p>
            <a href="/host/create" className="bh-button bh-button--yellow" style={{ marginTop: 12 }}>
              创建房间
            </a>
          </section>
        </div>
      </div>
    );
  }

  // ── loading ──────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="bh-page bh-page--narrow">
        <div className="bh-home">
          <div className="bh-muted-box">加载房间数据...</div>
        </div>
      </div>
    );
  }

  // ── render ───────────────────────────────────────────────────────

  return (
    <div className="bh-page" style={{ padding: 0 }}>
      <div className="bh-lobby">
        {/* Room code bar */}
        <div className="bh-lobby-room-bar">
          <span>HOST</span>
          <span style={{ flex: 1, textAlign: 'center', letterSpacing: 4 }}>{roomId}</span>
        </div>

        <div className="bh-lobby-layout">
          {/* LEFT: Scenario + Start */}
          <section className="bh-panel">
            <span className="bh-eyebrow">SCENARIO</span>
            <h2 className="bh-panel-title">
              {scenarioTitle || '未选择剧本'}
            </h2>

            {room?.status === 'lobby' && (
              <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
                <select
                  className="bh-input"
                  style={{ flex: 1 }}
                  value={selectedScenarioId}
                  onChange={(e) => setSelectedScenarioId(e.target.value)}
                  onFocus={() => { if (scenarioOptions.length === 0) loadScenarioOptions(); }}
                >
                  <option value="">-- 选择剧本 --</option>
                  {scenarioOptions.map((s) => (
                    <option key={s.scenario_id} value={s.scenario_id}>{s.title}</option>
                  ))}
                </select>
                <button
                  className="bh-button bh-button--yellow"
                  disabled={!selectedScenarioId || savingScenario}
                  onClick={saveScenario}
                >
                  {savingScenario ? '保存中...' : '保存'}
                </button>
              </div>
            )}

            {/* Start button + reason */}
            {room?.status === 'lobby' && (
              <div style={{ marginTop: 24 }}>
                <button
                  className="bh-button bh-button--yellow"
                  style={{ width: '100%', padding: '16px 0', fontSize: 20, fontWeight: 900 }}
                  disabled={!canStart}
                  onClick={() => startGame()}
                >
                  开始游戏
                </button>
                {disabledReason && (
                  <p className="bh-start-reason">{disabledReason}</p>
                )}

                {/* Force start when server returns not_ready */}
                {startError && notReadyList.length > 0 && (
                  <div style={{ marginTop: 12, padding: 12, border: '3px solid var(--bh-red)', background: 'var(--bh-yellow)' }}>
                    <p style={{ fontWeight: 900, fontSize: 14 }}>{startError}</p>
                    <p style={{ fontSize: 12, marginTop: 4 }}>
                      未准备: {notReadyList.map((p: any) => p.player_name || p.character_id).join('、')}
                    </p>
                    <button
                      className="bh-button"
                      style={{ marginTop: 8, background: 'var(--bh-red)', color: '#fff' }}
                      onClick={() => startGame(true)}
                    >
                      强制开始 (跳过准备检查)
                    </button>
                  </div>
                )}

                {startError && notReadyList.length === 0 && (
                  <p className="bh-start-reason" style={{ borderColor: 'var(--bh-red)' }}>{startError}</p>
                )}
              </div>
            )}

            {/* Enter stage when active */}
            {room?.status === 'active' && (
              <div style={{ marginTop: 24, textAlign: 'center' }}>
                <p style={{ fontWeight: 900, color: 'var(--bh-yellow)', marginBottom: 8 }}>游戏进行中</p>
                <a
                  className="bh-button bh-button--yellow"
                  href={`/host/${roomId}/stage`}
                  style={{ display: 'block', textAlign: 'center', padding: 16, fontSize: 18 }}
                >
                  进入舞台
                </a>
              </div>
            )}
          </section>
          <HostCampaignControls roomId={roomId} />

          {/* RIGHT: Player list + room info */}
          <section className="bh-panel">
            <span className="bh-eyebrow">INVESTIGATORS</span>
            <h2 className="bh-panel-title">
              调查员 ({players.length})
            </h2>

            {players.length === 0 && (
              <p style={{ fontSize: 13, color: 'var(--bh-dim)', padding: '12px 0' }}>
                等待玩家加入...
              </p>
            )}

            {players.map((p) => (
              <div key={p.character_id} className="bh-lobby-player-item">
                <div className="bh-lobby-avatar">
                  {(p.player_name || '?')[0]}
                </div>
                <div className="bh-lobby-player-info">
                  <div className="bh-lobby-player-name">{p.player_name}</div>
                  <div className="bh-lobby-investigator">
                    {p.investigator_name || '调查员'}
                  </div>
                </div>
                <span className={`bh-ready-badge ${p.is_ready ? 'bh-ready-badge--ready' : 'bh-ready-badge--waiting'}`}>
                  {p.is_ready ? '已准备' : '未准备'}
                </span>
              </div>
            ))}

            {/* Room status footer */}
            <div style={{
              marginTop: 16, padding: 12,
              border: '3px solid var(--bh-black)',
              background: 'var(--bh-paper)',
              fontSize: 13, fontWeight: 700,
            }}>
              <div>
                状态: <strong>{room?.status === 'lobby' ? '大厅等待中' : room?.status === 'active' ? '进行中' : room?.status || '未知'}</strong>
              </div>
              <div style={{ marginTop: 4, fontSize: 28, fontWeight: 900, letterSpacing: 6 }}>
                {roomId}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
