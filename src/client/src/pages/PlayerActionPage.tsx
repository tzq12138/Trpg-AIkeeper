import { useEffect, useState, useCallback } from 'react';
import PlayerCharacter from './PlayerCharacter';
import PlayerInventory from './PlayerInventory';
import { getSlotValue } from '../shared/identity';
import TacticalButtons from '../components/TacticalButtons';
import PlayerTerminal from '../components/PlayerTerminal';
import VoiceInput from '../components/VoiceInput';
import { PlayerWS } from '../ws';
import { apiFetch, authHeaders } from '../api';
import type { CharacterSheet, EngineEvent, PlayerChatMessage, SkillCheckResult, TacticalAction } from '../types';
import type { PlayerTabKey } from '../navigation';

function buildEncounterActions(encounterType: string): TacticalAction[] {
  if (encounterType === 'combat') {
    return [
      { action_id: 'cmb-atk', label: '⚔️ 攻击', intent_type: 'combat_action', params: { actionKind: 'attack', skillName: '斗殴' } },
      { action_id: 'cmb-dod', label: '🛡️ 闪避', intent_type: 'combat_action', params: { actionKind: 'dodge' } },
      { action_id: 'cmb-def', label: '🛡️ 防御', intent_type: 'combat_action', params: { actionKind: 'defend' } },
      { action_id: 'cmb-ast', label: '🤝 协助', intent_type: 'combat_action', params: { actionKind: 'assist' } },
      { action_id: 'cmb-fle', label: '🏃 逃跑', intent_type: 'combat_action', params: { actionKind: 'flee' } },
      { action_id: 'cmb-wat', label: '⏳ 等待', intent_type: 'combat_action', params: { actionKind: 'wait' } },
    ];
  }
  return [
    { action_id: 'chs-pur', label: '🏃 追击', intent_type: 'chase_action', params: { actionKind: 'pursue', skillName: '运动' } },
    { action_id: 'chs-esc', label: '💨 逃脱', intent_type: 'chase_action', params: { actionKind: 'escape', skillName: '运动' } },
    { action_id: 'chs-blk', label: '🚧 路障', intent_type: 'chase_action', params: { actionKind: 'block' } },
    { action_id: 'chs-det', label: '🔄 绕路', intent_type: 'chase_action', params: { actionKind: 'detour', skillName: '导航' } },
    { action_id: 'chs-ast', label: '🤝 协助', intent_type: 'chase_action', params: { actionKind: 'assist' } },
    { action_id: 'chs-wat', label: '⏳ 等待', intent_type: 'chase_action', params: { actionKind: 'wait' } },
  ];
}

export default function PlayerActionPage({ roomId }: { roomId: string }) {
  const [tab, setTab] = useState<PlayerTabKey>('action');
  const [character, setCharacter] = useState<CharacterSheet | null>(null);
  const [inputText, setInputText] = useState('');
  const [actionStatus, setActionStatus] = useState<string>('idle');
  const [messages, setMessages] = useState<PlayerChatMessage[]>([]);
  const [pendingActions, setPendingActions] = useState<TacticalAction[]>([]);
  const [claimOpen, setClaimOpen] = useState(false);
  const [claimedItemName, setClaimedItemName] = useState('');
  const [claimJustification, setClaimJustification] = useState('');
  const [claimStatus, setClaimStatus] = useState('');
  const [lastSkillCheckResult, setLastSkillCheckResult] = useState<SkillCheckResult | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [charStatus, setCharStatus] = useState('joined');
  const [mapRefresh, setMapRefresh] = useState(0);

  // Check character status from API
  useEffect(() => {
    apiFetch<any>('/api/player/character', { headers: authHeaders() })
      .then((c) => {
        // Redirect to lobby if the game hasn't started yet
        if (c.room_status && c.room_status !== 'active') {
          window.location.href = `/player/${roomId}/lobby`;
          return;
        }
        setIsReady(c.is_ready || c.status === 'ready');
        setCharStatus(c.status || 'joined');
      })
      .catch(() => {});
  }, [roomId]);

  const toggleReady = async () => {
    const actionId = crypto.randomUUID();
    try {
      await fetch('/api/player/intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Room-Token': getSlotValue('player_token') || '' },
        body: JSON.stringify({ action_id: actionId, intent_type: 'ready_toggle', declared_intent: '切换准备状态' }),
      });
      setIsReady(!isReady);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    apiFetch<CharacterSheet>('/api/player/character', { headers: authHeaders() })
      .then(setCharacter)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const token = getSlotValue('player_token') || '';
    const ws = new PlayerWS(roomId);
    ws.onEvent((event: EngineEvent) => {
      if (event.type === 's2c_tactical_prompt') {
        const payload = event.payload as { text?: string; actions?: TacticalAction[] };
        const msg: PlayerChatMessage = {
          id: crypto.randomUUID(),
          sender: 'kp',
          text: payload.text || '请选择行动',
          actions: payload.actions,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev.slice(-49), msg]);
        if (payload.actions && payload.actions.length > 0) {
          setPendingActions(payload.actions);
        }
      } else if (event.type === 's2c_action_completed') {
        setActionStatus('idle');
        setPendingActions([]);
        // Try to extract skill check result for PlayerCharacter
        const payload = event.payload as Record<string, unknown>;
        if (payload && (payload.skill_name || payload.skillName)) {
          const rawLevel = String(payload.success_level ?? payload.successLevel ?? 'regular');
          const validLevels = ['critical', 'extreme', 'hard', 'regular', 'failure', 'fumble'] as const;
          type ValidLevel = typeof validLevels[number];
          const successLevel: ValidLevel = validLevels.includes(rawLevel as ValidLevel) ? (rawLevel as ValidLevel) : 'regular';
          setLastSkillCheckResult({
            skill_name: String(payload.skill_name || payload.skillName || ''),
            skill_value: Number(payload.skill_value ?? payload.skillValue ?? 0),
            roll: Number(payload.roll ?? 0),
            difficulty: String(payload.difficulty ?? 'regular'),
            success_level: successLevel,
            detail: String(payload.detail ?? ''),
          });
        }
      } else if (event.type === 's2c_public_observation') {
        const payload = event.payload as { text?: string };
        if (payload.text) {
          setMessages((prev) => [...prev.slice(-49), {
            id: crypto.randomUUID(),
            sender: 'kp',
            text: payload.text || '',
            timestamp: Date.now(),
          }]);
        }
      } else if (event.type === 's2c_state_patch') {
        const payload = event.payload as { patches?: Array<{ op?: string; path?: string; value?: { name?: string } }> };
        const added = payload.patches?.find((p) => p.op === 'add' && p.path === '/inventory/-');
        const itemName = added?.value?.name;
        if (itemName) {
          setMessages((prev) => [...prev.slice(-49), {
            id: crypto.randomUUID(),
            sender: 'system',
            text: `已加入背包：${itemName}`,
            timestamp: Date.now(),
          }]);
        }
      } else if (event.type === 's2c_map_updated' || event.type === 's2c_player_moved' || event.type === 's2c_map_revealed') {
        setMapRefresh((n) => n + 1);
      } else if (event.type === 's2c_encounter_started') {
        const payload = event.payload as { encounter?: { type?: string }; participants?: any[] };
        // Show encounter tactical buttons
        if (payload?.encounter?.type) {
          const actions = buildEncounterActions(payload.encounter.type);
          setPendingActions(actions);
        }
      } else if (event.type === 's2c_encounter_updated') {
        const payload2 = event.payload as { encounter?: { type?: string } };
        if (payload2?.encounter?.type) {
          const actions = buildEncounterActions(payload2.encounter.type);
          setPendingActions(actions);
        }
      } else if (event.type === 's2c_encounter_resolved') {
        setPendingActions([]);
      } else if (event.type === 's2c_team_message') {
        const p = event.payload as Record<string, unknown>;
        if (p.text && typeof p.text === 'string') {
          setMessages((prev) => [...prev.slice(-49), {
            id: crypto.randomUUID(),
            sender: 'team',
            text: `${p.playerName || p.investigatorName || '队友'}: ${p.text}`,
            timestamp: Date.now(),
          }]);
        }
      }
    });
    ws.connect(token);
    return () => ws.disconnect();
  }, [roomId]);

  const submitAction = async () => {
    if (!inputText.trim() || actionStatus !== 'idle') return;
    setActionStatus('submitting');
    const actionId = crypto.randomUUID();
    const declaredIntent = inputText.trim();
    try {
      const res = await fetch('/api/player/intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Room-Token': getSlotValue('player_token') || '' },
        body: JSON.stringify({
          action_id: actionId,
          intent_type: 'dialogue',
          declared_intent: declaredIntent,
        }),
      });
      if (res.ok) {
        setActionStatus('resolving');
        setMessages((prev) => [...prev.slice(-49), {
          id: actionId,
          sender: 'player',
          text: declaredIntent,
          timestamp: Date.now(),
        }]);
        setInputText('');
      } else {
        setActionStatus('idle');
      }
    } catch {
      setActionStatus('idle');
    }
  };

  const submitRetroClaim = async () => {
    if (!claimedItemName.trim() || actionStatus !== 'idle') return;
    setClaimStatus('提交中...');
    const actionId = crypto.randomUUID();
    const itemName = claimedItemName.trim();
    const justification = claimJustification.trim() || `我主张角色背景中应有${itemName}`;
    try {
      const res = await fetch('/api/player/intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Room-Token': getSlotValue('player_token') || '' },
        body: JSON.stringify({
          action_id: actionId,
          intent_type: 'retroactive_item_claim',
          declared_intent: justification,
          params: {
            claimedItemName: itemName,
            justificationText: justification,
          },
        }),
      });
      if (res.ok) {
        setClaimStatus('主张已提交');
        setMessages((prev) => [...prev.slice(-49), {
          id: actionId,
          sender: 'player',
          text: `主张物品：${itemName}`,
          timestamp: Date.now(),
        }]);
        setClaimedItemName('');
        setClaimJustification('');
        setClaimOpen(false);
      } else {
        const data = await res.json().catch(() => ({}));
        setClaimStatus(String(data.detail || '主张未通过'));
      }
    } catch {
      setClaimStatus('提交失败');
    }
  };

  return (
    <PlayerTerminal activeTab={tab} character={character} onTabChange={setTab} isReady={isReady} charStatus={charStatus} onToggleReady={toggleReady}>
      {tab === 'action' && (
        <ActionPanel
          actionStatus={actionStatus}
          claimJustification={claimJustification}
          claimOpen={claimOpen}
          claimStatus={claimStatus}
          claimedItemName={claimedItemName}
          inputText={inputText}
          messages={messages}
          pendingActions={pendingActions}
          onClaimJustificationChange={setClaimJustification}
          onClaimOpenChange={setClaimOpen}
          onClaimStatusChange={setClaimStatus}
          onClaimedItemNameChange={setClaimedItemName}
          onInputTextChange={setInputText}
          onSubmitAction={submitAction}
          onSubmitRetroClaim={submitRetroClaim}
          onTacticalSubmitted={() => setActionStatus('resolving')}
        />
      )}
      {tab === 'character' && <PlayerCharacter externalResult={lastSkillCheckResult} onResultConsumed={() => setLastSkillCheckResult(null)} />}
      {tab === 'inventory' && <PlayerInventory />}
      {tab === 'logs' && <PlayerLogsPanel messages={messages} />}
      {tab === 'map' && <PlayerMapPanel roomId={roomId} mapRefresh={mapRefresh} />}
    </PlayerTerminal>
  );
}

interface ActionPanelProps {
  actionStatus: string;
  claimJustification: string;
  claimOpen: boolean;
  claimStatus: string;
  claimedItemName: string;
  inputText: string;
  messages: PlayerChatMessage[];
  pendingActions: TacticalAction[];
  onClaimJustificationChange: (value: string) => void;
  onClaimOpenChange: (value: boolean) => void;
  onClaimStatusChange: (value: string) => void;
  onClaimedItemNameChange: (value: string) => void;
  onInputTextChange: (value: string) => void;
  onSubmitAction: () => void;
  onSubmitRetroClaim: () => void;
  onTacticalSubmitted: () => void;
}

function ActionPanel({
  actionStatus,
  claimJustification,
  claimOpen,
  claimStatus,
  claimedItemName,
  inputText,
  messages,
  pendingActions,
  onClaimJustificationChange,
  onClaimOpenChange,
  onClaimStatusChange,
  onClaimedItemNameChange,
  onInputTextChange,
  onSubmitAction,
  onSubmitRetroClaim,
  onTacticalSubmitted,
}: ActionPanelProps) {
  const isIdle = actionStatus === 'idle';

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">TACTICAL CHANNEL</span>
      <h2 className="bh-panel-title">玩家行动终端</h2>

      <div className="bh-message-list" aria-live="polite">
        {messages.length === 0 && (
          <div className="bh-message">等待 KP 指令，或主动描述你的下一步行动。</div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`bh-message ${msg.sender === 'player' ? 'bh-message--player' : ''} ${msg.sender === 'system' ? 'bh-message--system' : ''}`}
          >
            {msg.text}
            {msg.actions && msg.actions.length > 0 && (
              <TacticalButtons
                actions={msg.actions}
                disabled={!isIdle}
                onSubmitted={onTacticalSubmitted}
              />
            )}
          </div>
        ))}
      </div>

      {pendingActions.length > 0 && isIdle && (
        <div className="bh-panel" style={{ marginTop: 16 }}>
          <span className="bh-eyebrow">QUICK ACTIONS</span>
          <TacticalButtons
            actions={pendingActions}
            disabled={false}
            onSubmitted={onTacticalSubmitted}
          />
        </div>
      )}

      <VoiceInput
        onSendToTeam={(text, source) => {
          fetch('/api/player/team-message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Room-Token': getSlotValue('player_token') || '' },
            body: JSON.stringify({ text, source }),
          }).catch(() => {});
        }}
        onSubmitAction={(text) => {
          onInputTextChange(text);
          onSubmitAction();
        }}
      />

      <div className="bh-action-box">
        <textarea
          className="bh-textarea"
          value={inputText}
          onChange={(e) => onInputTextChange(e.target.value)}
          placeholder="描述你的行动..."
          disabled={!isIdle}
        />
        <div className="bh-action-row">
          <button className="bh-button bh-button--yellow" type="button" onClick={onSubmitAction} disabled={!isIdle}>
            {isIdle ? '提交行动' : '等待结算...'}
          </button>
          <button
            className="bh-button"
            type="button"
            onClick={() => {
              onClaimOpenChange(!claimOpen);
              onClaimStatusChange('');
            }}
            disabled={!isIdle}
          >
            主张物品
          </button>
        </div>

        {claimOpen && (
          <div className="bh-claim-box">
            <input
              className="bh-input"
              value={claimedItemName}
              onChange={(e) => onClaimedItemNameChange(e.target.value)}
              placeholder="物品名，例如：医用胶带"
            />
            <input
              className="bh-input"
              value={claimJustification}
              onChange={(e) => onClaimJustificationChange(e.target.value)}
              placeholder="理由，例如：我是医生，随身带着"
            />
            <button
              className="bh-button bh-button--blue"
              type="button"
              onClick={onSubmitRetroClaim}
              disabled={!claimedItemName.trim() || !isIdle}
            >
              提交主张
            </button>
            {claimStatus && <div className="bh-error">{claimStatus}</div>}
          </div>
        )}
      </div>
    </section>
  );
}

function PlayerLogsPanel({ messages }: { messages: PlayerChatMessage[] }) {
  const [archive, setArchive] = useState<any[]>([]);
  const [archiveType, setArchiveType] = useState('all');

  useEffect(() => {
    const token = getSlotValue('player_token') || '';
    const params = new URLSearchParams({ type: archiveType, limit: '50' });
    fetch(`/api/player/archive?${params}`, {
      headers: { 'X-Room-Token': token },
    })
      .then((r) => r.json())
      .then((d) => setArchive(d.entries || []))
      .catch(() => {});
  }, [archiveType]);

  const archiveRows = archive.map((e: any) => ({
    id: String(e.sequence || Math.random()),
    sender: (e.is_public ? 'kp' : 'system') as 'kp' | 'system',
    text: e.data?.text || JSON.stringify(e.data || {}).slice(0, 80),
    timestamp: Date.now(),
  }));

  const localRows = archiveRows.length > 0 ? archiveRows : messages.length > 0 ? messages.slice(-8).reverse() : [
    { id: 'empty', sender: 'system' as const, text: '暂无历史记录。跑团开始后此处将显示事件日志。', timestamp: Date.now() },
  ];

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">INVESTIGATION LOGS</span>
      <h2 className="bh-panel-title">调查日志</h2>
      <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
        {['all', 'narrative', 'actions', 'clues', 'skill_checks'].map((t) => (
          <button key={t} className={`bh-button${archiveType === t ? ' bh-button--yellow' : ''}`}
                  style={{ padding: '2px 8px', fontSize: 10 }}
                  onClick={() => setArchiveType(t)}>
            {t === 'all' ? '全部' : t === 'narrative' ? '剧情' : t === 'actions' ? '行动' : t === 'clues' ? '线索' : '检定'}
          </button>
        ))}
      </div>
      <div className="bh-log-list">
        {localRows.slice(0, 12).map((msg) => (
          <div key={msg.id} className="bh-log-entry">
            <strong>{msg.sender.toUpperCase()}</strong>
            <p>{msg.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

interface MapTileData {
  nodeId: string; name: string; description: string;
  explored: boolean; isCurrent: boolean; isAdjacent: boolean;
  hasClues: boolean; hasNpcs: boolean;
  npcsPresent: string[]; cluesAvailable: string[];
  position: { x: number; y: number };
}

function PlayerMapPanel({ roomId, mapRefresh }: { roomId: string; mapRefresh: number }) {
  const [tiles, setTiles] = useState<MapTileData[]>([]);
  const [currentTile, setCurrentTile] = useState<string | null>(null);
  const [hiddenCount, setHiddenCount] = useState(0);
  const [mapStatus, setMapStatus] = useState('no_map');
  const [loading, setLoading] = useState(true);
  const [movePending, setMovePending] = useState(false);

  const fetchMap = () => {
    const token = getSlotValue('player_token') || '';
    fetch(`/api/map/${encodeURIComponent(roomId)}`, {
      headers: { 'X-Room-Token': token },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Record<string, any> | null) => {
        if (data) {
          setTiles((data.nodes || []) as MapTileData[]);
          setCurrentTile((data.currentNodeId || null) as string | null);
          setHiddenCount(Number(data.hiddenCount || 0));
          setMapStatus(String(data.mapStatus || 'no_map'));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchMap();
  }, [roomId, mapRefresh]);

  const handleMove = async (nodeId: string) => {
    setMovePending(true);
    const token = getSlotValue('player_token') || '';
    try {
      const res = await fetch(`/api/map/${encodeURIComponent(roomId)}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Room-Token': token },
        body: JSON.stringify({ target_node_id: nodeId }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'submitted') {
          // Move submitted — position will update via WS event
        }
      }
    } catch { /* ignore */ }
    // Move pending flag auto-clears on next map refresh (WS event)
    setTimeout(() => setMovePending(false), 5000);
  };

  // No map state
  if (!loading && mapStatus === 'no_map') {
    return (
      <section className="bh-panel">
        <span className="bh-eyebrow">MAP</span>
        <h2 className="bh-panel-title">调查区域地图</h2>
        <div className="bh-muted-box" style={{ padding: 32, textAlign: 'center' }}>
          <p style={{ fontWeight: 700, marginBottom: 8 }}>暂无地图配置</p>
          <p style={{ fontSize: 12, color: 'var(--bh-dim)' }}>
            房主尚未为本房间配置地图。请等待房主初始化地图后刷新页面。
          </p>
        </div>
      </section>
    );
  }

  // Loading state
  if (loading) {
    return (
      <section className="bh-panel">
        <span className="bh-eyebrow">MAP</span>
        <h2 className="bh-panel-title">调查区域地图</h2>
        <div className="bh-muted-box">加载地图中...</div>
      </section>
    );
  }

  const current = tiles.find((t) => t.nodeId === currentTile);

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">INVESTIGATION MAP</span>
      <h2 className="bh-panel-title">
        {current ? current.name : '调查区域地图'}
        {hiddenCount > 0 && <span className="bh-eyebrow" style={{ fontSize: 9, marginLeft: 8 }}>+{hiddenCount} 未探索</span>}
      </h2>

      {movePending && (
        <div className="bh-muted-box" style={{ marginBottom: 8 }}>
          移动已提交，等待本轮结算...
        </div>
      )}

      <div className="bh-map-grid">
        {tiles.map((tile) => {
          const isCurrent = tile.nodeId === currentTile;
          const isClickable = tile.isAdjacent && !isCurrent && !movePending;

          // Use position from data, fall back to circle layout
          const posX = tile.position?.x ?? 50;
          const posY = tile.position?.y ?? 50;

          let className = 'bh-map-node';
          if (isCurrent) className += ' bh-map-node--current';
          if (tile.explored) className += ' bh-map-node--explored';
          if (tile.isAdjacent) className += ' bh-map-node--adjacent';
          if (!tile.explored && !tile.isAdjacent) className += ' bh-map-node--hidden';

          return (
            <button
              key={tile.nodeId}
              className={className}
              style={{ position: 'absolute', left: `${posX}%`, top: `${posY}%` }}
              onClick={() => isClickable && handleMove(tile.nodeId)}
              disabled={!isClickable}
              title={tile.explored ? tile.description : '???'}
            >
              <span className="bh-map-node-name">{tile.name}</span>
              {tile.hasClues && <span className="bh-map-node-badge">🔍</span>}
              {tile.hasNpcs && <span className="bh-map-node-badge">👤</span>}
            </button>
          );
        })}
      </div>

      {current && (
        <div className="bh-map-info" style={{ marginTop: 12 }}>
          <p style={{ fontWeight: 700 }}>{current.explored ? current.description : '???'}</p>
          {current.hasClues && <span className="bh-eyebrow" style={{ fontSize: 9 }}>HAS CLUES</span>}
          {current.hasNpcs && <span className="bh-eyebrow" style={{ fontSize: 9, marginLeft: 8 }}>HAS NPCs</span>}
        </div>
      )}
    </section>
  );
}
