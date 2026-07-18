import { useEffect, useState, useRef, useCallback } from 'react';
import { getSlotValue } from '../shared/identity';
import { apiFetch, authHeaders } from '../shared/api';
import { PlayerWS } from '../shared/ws';
import { buildPlayerLobbyChecklist } from '../shared/lobby-checklist';

// ── types ──────────────────────────────────────────────────────────

interface LobbyPlayer {
  character_id: string;
  player_name: string;
  investigator_name: string;
  status: string;
  is_ready: boolean;
}

interface LobbySnapshot {
  room_id: string;
  room_status: string;
  scenario_title: string;
  players: LobbyPlayer[];
}

interface ChatMsg {
  messageId: string;
  characterId: string;
  playerName: string;
  investigatorName: string;
  text: string;
  createdAt: string;
}

interface CampaignEnding {
  ending_type: 'victory' | 'defeat' | 'mixed' | 'abandoned';
  summary: string;
  highlights: string[];
}

interface CampaignSummary {
  ending: CampaignEnding | null;
}

// ── helpers ────────────────────────────────────────────────────────

function playerToken(): string {
  return getSlotValue('player_token') || '';
}

// ── component ──────────────────────────────────────────────────────

export default function PlayerLobby({ roomId }: { roomId: string }) {
  const [snapshot, setSnapshot] = useState<LobbySnapshot | null>(null);
  const [myCharId, setMyCharId] = useState('');
  const [isReady, setIsReady] = useState(false);
  const [myStatus, setMyStatus] = useState('joined');
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [error, setError] = useState('');
  const [campaignEnding, setCampaignEnding] = useState<CampaignEnding | null>(null);
  const [entering, setEntering] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<PlayerWS | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seenMsgIds = useRef<Set<string>>(new Set());
  const chatEndRef = useRef<HTMLDivElement>(null);

  // ── auto-scroll chat ───────────────────────────────────────────────

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // ── fetch helpers ────────────────────────────────────────────────

  const fetchCharacter = useCallback(async () => {
    const c = await apiFetch<any>('/api/player/character', { headers: authHeaders() });
    setMyCharId(c.character_id);
    setIsReady(c.is_ready || c.status === 'ready');
    setMyStatus(c.status || 'joined');
    if (c.room_status === 'active' && c.status !== 'pending_approval') {
      window.location.href = `/player/${roomId}`;
    }
    return c;
  }, [roomId]);

  const fetchLobby = useCallback(async () => {
    const data = await apiFetch<LobbySnapshot>(
      `/api/player/rooms/${roomId}/join-info`,
      { headers: { 'X-Room-Token': playerToken() } },
    );
    setSnapshot(data);
    return data;
  }, [roomId]);

  // ── initial load ─────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const c = await fetchCharacter();
        if (cancelled) return;
        await fetchLobby();
      } catch (e: any) {
        if (!cancelled) setError(e.message || '加载失败');
      }
    })();
    return () => { cancelled = true; };
  }, [roomId, fetchCharacter, fetchLobby]);

  useEffect(() => {
    if (snapshot?.room_status !== 'completed') {
      setCampaignEnding(null);
      return;
    }
    let cancelled = false;
    apiFetch<CampaignSummary>(`/api/rooms/${roomId}/campaign`, {
      headers: { 'X-Room-Token': playerToken() },
    })
      .then((campaign) => {
        if (!cancelled) setCampaignEnding(campaign.ending);
      })
      .catch(() => {
        if (!cancelled) setCampaignEnding(null);
      });
    return () => { cancelled = true; };
  }, [roomId, snapshot?.room_status]);

  // ── WebSocket ────────────────────────────────────────────────────

  useEffect(() => {
    const token = playerToken();
    if (!token) return;

    const ws = new PlayerWS(roomId);
    wsRef.current = ws;

    ws.onStatus((status) => {
      setIsConnected(status === 'open');
    });

    ws.onEvent((event: any) => {
      const type = event.eventType || event.type;
      const payload = event.payload || {};

      if (type === 's2c_room_lobby_snapshot') {
        setSnapshot(payload as LobbySnapshot);
        const currentPlayer = (payload.players || []).find(
          (player: LobbyPlayer) => player.character_id === myCharId,
        );
        if (currentPlayer?.status) setMyStatus(currentPlayer.status);
        // Auto-enter when game starts
        if (
          payload.room_status === 'active'
          && currentPlayer?.status !== 'pending_approval'
          && !entering
        ) {
          setEntering(true);
          setTimeout(() => {
            window.location.href = `/player/${roomId}`;
          }, 2000);
        }
      }

      if (type === 's2c_team_message') {
        const msg = payload as ChatMsg;
        // Deduplicate: skip if we already have this message (optimistic + WS echo)
        if (seenMsgIds.current.has(msg.messageId)) return;
        seenMsgIds.current.add(msg.messageId);
        setChatMessages((prev) => [...prev.slice(-99), msg]);
      }
    });

    ws.connect(token);

    return () => {
      setIsConnected(false);
      ws.disconnect();
    };
  }, [roomId, entering, myCharId]);

  // ── polling fallback ─────────────────────────────────────────────

  useEffect(() => {
    pollRef.current = setInterval(() => {
      // Only poll if WS might be down — refresh lobby state
      fetchLobby().catch(() => {});
      fetchCharacter().catch(() => {});
    }, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchCharacter, fetchLobby]);

  // ── actions ──────────────────────────────────────────────────────

  const toggleReady = async () => {
    const newReady = !isReady;
    setIsReady(newReady); // optimistic
    try {
      await apiFetch('/api/player/intent', {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_id: crypto.randomUUID(),
          intent_type: 'ready_toggle',
          declared_intent: newReady ? '准备就绪' : '取消准备',
        }),
      });
    } catch {
      setIsReady(!newReady); // rollback
    }
  };

  const sendChat = async () => {
    const text = chatInput.trim();
    if (!text) return;
    setChatInput('');

    // Optimistic local message (with dedup ID so WS echo is skipped)
    const msgId = crypto.randomUUID();
    seenMsgIds.current.add(msgId);
    const optimistic: ChatMsg = {
      messageId: msgId,
      characterId: myCharId,
      playerName: '',
      investigatorName: '',
      text,
      createdAt: new Date().toISOString(),
    };
    setChatMessages((prev) => [...prev, optimistic]);

    try {
      await apiFetch('/api/player/team-message', {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
    } catch {
      // Remove optimistic message on failure
      setChatMessages((prev) => prev.filter((m) => m.messageId !== optimistic.messageId));
      setError('发送失败');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  };

  // ── derived ──────────────────────────────────────────────────────

  const players = snapshot?.players || [];
  const roomStatus = snapshot?.room_status || 'lobby';
  const scenarioTitle = snapshot?.scenario_title || '';
  const preparationChecklist = buildPlayerLobbyChecklist({
    scenarioTitle,
    hasCharacter: Boolean(myCharId),
    isReady,
    isConnected,
    roomStatus,
  });

  if (myStatus === 'pending_approval') {
    return (
      <div className="bh-page">
        <section className="bh-panel" style={{ maxWidth: 640, margin: '8vh auto' }}>
          <span className="bh-eyebrow">HOST APPROVAL</span>
          <h2 className="bh-panel-title">等待 Host 批准加入</h2>
          <p className="bh-panel-desc">
            房间已经开始。你的角色和连接预检已保存，Host 批准后会自动进入游戏。
          </p>
          <div className="bh-muted-box" role="status">
            房间 {roomId} · 实时连接保持中 · 请勿重复提交角色
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="bh-page" style={{ padding: 0 }}>
      <div className="bh-lobby">
        {/* Room bar */}
        <div className="bh-lobby-room-bar">
          <span>ROOM</span>
          <span style={{ flex: 1, textAlign: 'center', letterSpacing: 4 }}>{roomId}</span>
        </div>

        {/* Two-column layout */}
        <div className="bh-lobby-layout">
          {roomStatus === 'completed' && (
            <section className="bh-panel" role="status" style={{ gridColumn: '1 / -1' }}>
              <span className="bh-eyebrow">ADVENTURE COMPLETE</span>
              <h2 className="bh-panel-title">本次冒险已结束</h2>
              <p className="bh-panel-desc">
                {campaignEnding?.summary || '结局条件已验证，战报正在整理。'}
              </p>
              {campaignEnding?.highlights.map((highlight) => (
                <p key={highlight} style={{ fontSize: 13, color: 'var(--bh-dim)' }}>{highlight}</p>
              ))}
            </section>
          )}
          {/* LEFT: Player list */}
          <section className="bh-panel">
            <span className="bh-eyebrow">SESSION PREP</span>
            <h2 className="bh-panel-title">
              开局准备台
            </h2>
            <div className="bh-preparation-checklist" aria-label="开局准备状态">
              {preparationChecklist.map((item) => (
                <div key={item.key} className={`bh-preparation-item ${item.complete ? 'bh-preparation-item--complete' : ''}`}>
                  <strong>{item.complete ? '✓' : '○'} {item.label}</strong>
                  <span>{item.detail}</span>
                </div>
              ))}
            </div>

            <div className="bh-lobby-section-heading">
              <span className="bh-eyebrow">INVESTIGATORS</span>
              <span>{players.length} 名调查员</span>
            </div>

            {players.length === 0 && (
              <p style={{ fontSize: 13, color: 'var(--bh-dim)' }}>
                等待其他玩家加入...
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
                    {p.character_id === myCharId ? ' (你)' : ''}
                  </div>
                </div>
                <span className={`bh-ready-badge ${p.is_ready ? 'bh-ready-badge--ready' : 'bh-ready-badge--waiting'}`}>
                  {p.is_ready ? '已准备' : '未准备'}
                </span>
              </div>
            ))}

            {/* Ready button for current player */}
            <button
              className={`bh-lobby-ready-button ${isReady ? 'bh-lobby-ready-button--ready' : 'bh-lobby-ready-button--not-ready'}`}
              onClick={toggleReady}
              style={{ marginTop: 16 }}
            >
              {isReady ? '✅ 已准备 — 点击取消' : '❌ 点击准备'}
            </button>
          </section>

          {/* RIGHT: Chat + Enter game */}
          <section className="bh-panel" style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="bh-eyebrow">TEAM CHANNEL</span>
            <h2 className="bh-panel-title">队内频道</h2>

            {/* Chat messages */}
            <div className="bh-lobby-chat">
              {chatMessages.length === 0 && (
                <p style={{ fontSize: 12, color: 'var(--bh-dim)', textAlign: 'center', padding: 24 }}>
                  在队内频道跟队友交流
                </p>
              )}
              {chatMessages.map((m) => (
                <div
                  key={m.messageId}
                  className={`bh-lobby-chat-msg ${m.characterId === myCharId ? 'bh-lobby-chat-msg--self' : ''}`}
                >
                  <div style={{ fontWeight: 900, fontSize: 11, opacity: 0.6 }}>
                    {m.playerName || '我'}
                  </div>
                  <div>{m.text}</div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Chat input */}
            <div className="bh-lobby-chat-input" style={{ display: 'flex', gap: 6, marginTop: 'auto' }}>
              <textarea
                className="bh-input"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入消息，Enter 发送..."
                rows={2}
                style={{ flex: 1, resize: 'none' }}
              />
              <button
                className="bh-button bh-button--yellow"
                onClick={sendChat}
                disabled={!chatInput.trim()}
                style={{ alignSelf: 'stretch' }}
              >
                发送
              </button>
            </div>

            {/* Enter game button */}
            {roomStatus === 'active' && (
              <div style={{ marginTop: 16, textAlign: 'center' }}>
                <p style={{ fontWeight: 900, color: 'var(--bh-yellow)', marginBottom: 8 }}>
                  🎲 游戏已开始！
                </p>
                <a
                  className="bh-button bh-button--yellow"
                  href={`/player/${roomId}`}
                  style={{ display: 'block', textAlign: 'center', padding: 16, fontSize: 18 }}
                >
                  进入游戏
                </a>
              </div>
            )}

            {entering && (
              <div style={{ marginTop: 16, textAlign: 'center' }}>
                <p style={{ fontWeight: 900, fontSize: 18 }}>Game starting!</p>
                <p style={{ fontSize: 12, color: 'var(--bh-dim)' }}>正在进入游戏...</p>
              </div>
            )}
          </section>
        </div>

        {/* Error banner */}
        {error && (
          <div className="bh-error" style={{ marginTop: 12, padding: 12, border: '2px solid var(--bh-red)', background: 'var(--bh-yellow)' }}>
            {error}
            <button style={{ marginLeft: 12, fontWeight: 900 }} onClick={() => setError('')}>✕</button>
          </div>
        )}
      </div>
    </div>
  );
}
