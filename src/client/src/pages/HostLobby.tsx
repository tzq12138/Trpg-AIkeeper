import { useState, useEffect, useCallback } from 'react';
import { getSlotValue } from '../shared/identity';
import { buildRoomWsUrl } from '../shared/ws-url';
import { buildHostLaunchChecklist } from '../shared/host-launch-checklist';
import { updatePublicSceneTime } from '../shared/public-scene-time';
import { buildStageClientUrl } from '../shared/stage-client';
import HostCampaignControls from '../components/HostCampaignControls';
import OwnerRecoveryPanel from '../components/OwnerRecoveryPanel';

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
  speech_routing?: 'party_message' | 'npc_dialogue';
  host_autonomy_policy?: HostAutonomyPolicy;
  session_mode?: string;
  players: LobbyPlayer[];
}

type HostAutonomyPolicy = 'host_required' | 'conservative' | 'delegated';

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

const SESSION_ZERO_MISSING_LABELS: Record<string, string> = {
  players: '至少一名玩家',
  character_rules: '角色规则确认',
  safety: '安全边界确认',
  ai_host: 'AI / Host 裁决方式确认',
  private_data: '私人数据确认',
  connection: '连接与设备确认',
  risk_contract: '安全边界（最新版）',
  ready: '准备就绪',
};

export interface SessionZeroMissingEntry {
  character_id: string;
  missing: string[];
}

/**
 * Render the structured AI_ONLY_SESSION_ZERO_INCOMPLETE 409 body without ever
 * stringifying the detail object (which would display "[object Object]").
 */
export function SessionZeroMissingBlock({
  entries,
  players,
}: {
  entries: SessionZeroMissingEntry[];
  players: LobbyPlayer[];
}) {
  const nameFor = (characterId: string) => {
    const player = players.find((p) => p.character_id === characterId);
    return player?.player_name || player?.investigator_name || characterId;
  };
  return (
    <div style={{ marginTop: 12, padding: 12, border: '3px solid var(--bh-red)', background: 'var(--bh-yellow)' }}>
      <p style={{ fontWeight: 900, fontSize: 14 }}>开始被拒绝：以下准备项尚未完成</p>
      {entries.map((entry) => (
        <p key={entry.character_id} style={{ fontSize: 13, marginTop: 6 }}>
          <strong>{nameFor(entry.character_id)}</strong>：
          {entry.missing
            .map((item) => SESSION_ZERO_MISSING_LABELS[item] || item)
            .join('、') || '未知缺项'}
        </p>
      ))}
    </div>
  );
}

export function HostAutonomyPolicyControl({
  policy,
  disabled,
  onChange,
}: {
  policy: HostAutonomyPolicy;
  disabled: boolean;
  onChange: (policy: HostAutonomyPolicy) => void;
}) {
  return (
    <div className="bh-muted-box" style={{ marginTop: 12 }}>
      <label className="bh-field-label" htmlFor="host-autonomy-policy">Host 计划离线策略</label>
      <select
        id="host-autonomy-policy"
        className="bh-input"
        value={policy}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as HostAutonomyPolicy)}
      >
        <option value="host_required">默认：Host 不在线时等待复核</option>
        <option value="conservative">保守：仅低风险公开观察可继续</option>
        <option value="delegated">已委托：普通检定、已揭示范围移动和普通物品使用</option>
      </select>
      <p style={{ marginTop: 6, fontSize: 12 }}>
        战斗、秘密行动、幸运消耗和重大结果仍会等待 Host；断线不会让 AI 自动选择战术或公开幕后信息。
      </p>
    </div>
  );
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
  const [sessionZeroMissing, setSessionZeroMissing] = useState<SessionZeroMissingEntry[]>([]);
  const [savingSpeechRouting, setSavingSpeechRouting] = useState(false);
  const [savingHostAutonomyPolicy, setSavingHostAutonomyPolicy] = useState(false);
  const [sceneTime, setSceneTime] = useState('');
  const [savingSceneTime, setSavingSceneTime] = useState(false);
  const [sceneTimeError, setSceneTimeError] = useState('');
  const [loading, setLoading] = useState(true);
  const [stageToken, setStageToken] = useState('');

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

  const fetchStageToken = useCallback(async () => {
    const ownerToken = getSlotValue('owner_token') || '';
    if (!ownerToken) return '';
    try {
      const response = await fetch(`/api/rooms/${roomId}/stage-access`, {
        headers: { 'X-Owner-Token': ownerToken },
      });
      if (!response.ok) return '';
      const payload = await response.json() as { stage_token?: string };
      const token = payload.stage_token || '';
      if (token) setStageToken(token);
      return token;
    } catch {
      return '';
    }
  }, [roomId]);

  useEffect(() => { void fetchStageToken(); }, [fetchStageToken]);

  useEffect(() => {
    const ownerToken = getSlotValue('owner_token') || '';
    if (!ownerToken) return;
    fetch(`/api/host/${roomId}/hud`, { headers: { 'X-Owner-Token': ownerToken } })
      .then((response) => response.ok ? response.json() : null)
      .then((hud) => {
        if (hud?.sceneTime && hud.sceneTime !== '时间未定') setSceneTime(hud.sceneTime);
      })
      .catch(() => {});
  }, [roomId]);

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

  const updateSpeechRouting = async (speechRouting: 'party_message' | 'npc_dialogue') => {
    setSavingSpeechRouting(true);
    try {
      const response = await fetch(`/api/rooms/${roomId}/action-settings`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-Owner-Token': getSlotValue('owner_token') || '',
        },
        body: JSON.stringify({ speech_routing: speechRouting }),
      });
      if (!response.ok) {
        setStartError('发言策略保存失败，请稍后重试。');
        return;
      }
      setRoom((current) => current ? { ...current, speech_routing: speechRouting } : current);
      setStartError('');
    } catch {
      setStartError('发言策略保存失败，请检查网络连接。');
    } finally {
      setSavingSpeechRouting(false);
    }
  };

  const updateHostAutonomyPolicy = async (hostAutonomyPolicy: HostAutonomyPolicy) => {
    setSavingHostAutonomyPolicy(true);
    try {
      const response = await fetch(`/api/rooms/${roomId}/action-settings`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-Owner-Token': getSlotValue('owner_token') || '',
        },
        body: JSON.stringify({ host_autonomy_policy: hostAutonomyPolicy }),
      });
      if (!response.ok) {
        setStartError('离线策略保存失败，请稍后重试。');
        return;
      }
      setRoom((current) => current ? { ...current, host_autonomy_policy: hostAutonomyPolicy } : current);
      setStartError('');
    } catch {
      setStartError('离线策略保存失败，请检查网络连接。');
    } finally {
      setSavingHostAutonomyPolicy(false);
    }
  };

  const savePublicSceneTime = async () => {
    const nextSceneTime = sceneTime.trim();
    if (!nextSceneTime) {
      setSceneTimeError('请填写玩家可以看到的场景时间。');
      return;
    }
    setSavingSceneTime(true);
    setSceneTimeError('');
    try {
      const result = await updatePublicSceneTime(roomId, getSlotValue('owner_token') || '', nextSceneTime);
      setSceneTime(result.sceneTime);
    } catch {
      setSceneTimeError('公开场景时间保存失败，请检查网络或房主身份。');
    } finally {
      setSavingSceneTime(false);
    }
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
    setSessionZeroMissing([]);

    try {
      const res = await fetch(`/api/rooms/${roomId}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
        body: JSON.stringify({ force_start: !!force }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        // The room is running regardless of Stage availability: enter the host
        // operations console. Stage is an optional link from here on — a
        // missing/expired Stage token must never reverse a successful start.
        window.location.href = `/host/${roomId}/console`;
      } else if (data.status === 'not_ready') {
        setNotReadyList(data.not_ready_players || []);
        setStartError('有玩家未准备');
      } else if (data.detail && typeof data.detail === 'object') {
        const code = (data.detail as any).code;
        if (code === 'AI_ONLY_SESSION_ZERO_INCOMPLETE') {
          setSessionZeroMissing((data.detail as any).missing || []);
          setStartError('请先补齐准备缺项');
        } else {
          setStartError(String((data.detail as any).reason || '开始失败'));
        }
      } else {
        setStartError(String(data.detail || '开始失败'));
      }
    } catch {
      setStartError('网络错误');
    }
  };

  // ── derived ──────────────────────────────────────────────────────

  const ownerToken = getSlotValue('owner_token') || '';
  const isAiOnlyRoom = room?.session_mode === 'ai_only';
  const stageUrl = buildStageClientUrl(roomId, stageToken);
  const unreadyPlayers = players.filter((p) => !p.is_ready);
  const canStart = players.length > 0 && !!scenarioTitle && unreadyPlayers.length === 0;
  const launchChecklist = buildHostLaunchChecklist({
    scenarioTitle,
    playerCount: players.length,
    unreadyPlayerCount: unreadyPlayers.length,
  });

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

        {/* R7: Owner-only system recovery + normal termination console */}
        <OwnerRecoveryPanel roomId={roomId} />

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

            <div className="bh-preparation-checklist" aria-label="开团检查清单">
              {launchChecklist.map((item) => (
                <div key={item.key} className={`bh-preparation-item ${item.complete ? 'bh-preparation-item--complete' : ''}`}>
                  <strong>{item.complete ? '✓' : '○'} {item.label}</strong>
                  <span>{item.detail}</span>
                </div>
              ))}
            </div>

            <div className="bh-muted-box" style={{ marginTop: 12 }}>
              <label className="bh-field-label" htmlFor="public-scene-time">公共场景时间</label>
              <div className="bh-action-row bh-action-row--responsive">
                <input
                  id="public-scene-time"
                  className="bh-input"
                  value={sceneTime}
                  maxLength={120}
                  placeholder="例如：1924-10-14 23:40"
                  onChange={(event) => setSceneTime(event.target.value)}
                />
                <button
                  className="bh-button"
                  disabled={savingSceneTime}
                  onClick={() => void savePublicSceneTime()}
                >
                  {savingSceneTime ? '保存中...' : '更新公开时间'}
                </button>
              </div>
              <p style={{ marginTop: 6, fontSize: 12 }}>
                这项会显示在公共舞台；不要填写幕后倒计时、隐藏线索或未公开事件。
              </p>
              {sceneTimeError && <p className="bh-start-reason" style={{ borderColor: 'var(--bh-red)' }}>{sceneTimeError}</p>}
            </div>

            <div className="bh-muted-box" style={{ marginTop: 12 }}>
              <label className="bh-field-label" htmlFor="speech-routing">角色发言处理</label>
              <select
                id="speech-routing"
                className="bh-input"
                value={room?.speech_routing || 'party_message'}
                disabled={savingSpeechRouting}
                onChange={(event) => void updateSpeechRouting(
                  event.target.value as 'party_message' | 'npc_dialogue',
                )}
              >
                <option value="party_message">队伍频道：只记录发言，不进入剧情</option>
                <option value="npc_dialogue">NPC 对话：生成预览后由玩家确认</option>
              </select>
              <p style={{ marginTop: 6, fontSize: 12 }}>
                对话裁决仍遵循草稿、风险确认和规则校验；不会自动改变世界状态。
              </p>
            </div>

            {!isAiOnlyRoom && (
              <HostAutonomyPolicyControl
                policy={room?.host_autonomy_policy || 'host_required'}
                disabled={savingHostAutonomyPolicy}
                onChange={(policy) => void updateHostAutonomyPolicy(policy)}
              />
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

                {/* Structured AI_ONLY_SESSION_ZERO_INCOMPLETE detail */}
                {sessionZeroMissing.length > 0 && (
                  <SessionZeroMissingBlock entries={sessionZeroMissing} players={players} />
                )}

                {/* Force start when server returns not_ready (non-ai_only rooms) */}
                {startError && !isAiOnlyRoom && notReadyList.length > 0 && (
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

                {startError && notReadyList.length === 0 && sessionZeroMissing.length === 0 && (
                  <p className="bh-start-reason" style={{ borderColor: 'var(--bh-red)' }}>{startError}</p>
                )}
              </div>
            )}

            {/* Enter stage when active */}
            {room?.status === 'active' && (
              <div style={{ marginTop: 24, textAlign: 'center' }}>
                <p style={{ fontWeight: 900, color: 'var(--bh-yellow)', marginBottom: 8 }}>游戏进行中</p>
                <div className="bh-action-row bh-action-row--responsive">
                  <a
                    className="bh-button bh-button--yellow"
                    href={`/host/${roomId}/console`}
                    style={{ flex: 1, textAlign: 'center', padding: 16, fontSize: 18 }}
                  >
                    打开导演控制台
                  </a>
                  <a
                    className="bh-button"
                    href={stageUrl}
                    style={{ flex: 1, textAlign: 'center', padding: 16, fontSize: 18 }}
                  >
                    打开公共舞台
                  </a>
                </div>
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
