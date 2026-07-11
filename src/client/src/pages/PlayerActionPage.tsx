import { useEffect, useRef, useState } from 'react';
import PlayerCharacter from './PlayerCharacter';
import PlayerInventory from './PlayerInventory';
import { getSlotValue } from '../shared/identity';
import TacticalButtons from '../components/TacticalButtons';
import PlayerTerminal from '../components/PlayerTerminal';
import VoiceInput from '../components/VoiceInput';
import PlayerActionComposer from '../components/PlayerActionComposer';
import CampaignHomePanel from '../components/CampaignHomePanel';
import { PlayerWS, type PlayerWSStatus } from '../ws';
import { apiFetch, authHeaders } from '../api';
import {
  analyzeActionDraft,
  cancelAction,
  claimPlayerDevice,
  confirmActionDraft,
  deleteActionDraft,
  getActionReceipt,
  PlayerApiError,
  reconnectPlayer,
} from '../shared/player-api';
import {
  createConfirmIdempotencyKey,
  isActionInFlight,
  mergeAuthoritativeReceipt,
  shouldAutoConfirmDraft,
} from '../shared/player-action-controller';
import type {
  ActionDraftDTO,
  ActionReceiptDTO,
  ActionStatus,
  CharacterSheet,
  EngineEvent,
  PlayerChatMessage,
  SkillCheckResult,
  TacticalAction,
} from '../types';
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
  const [tab, setTab] = useState<PlayerTabKey>('home');
  const [character, setCharacter] = useState<CharacterSheet | null>(null);
  const [inputText, setInputText] = useState('');
  const [actionStatus, setActionStatus] = useState<ActionStatus>('idle');
  const [draft, setDraft] = useState<ActionDraftDTO | null>(null);
  const [ephemeralPreview, setEphemeralPreview] = useState<ActionDraftDTO | null>(null);
  const [receipt, setReceipt] = useState<ActionReceiptDTO | null>(null);
  const [actionError, setActionError] = useState('');
  const [stateVersion, setStateVersion] = useState(0);
  const [connectionStatus, setConnectionStatus] = useState<PlayerWSStatus>('connecting');
  const wsRef = useRef<PlayerWS | null>(null);
  const restoredSequence = useRef(0);
  const lastEphemeralText = useRef('');
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
  const [deviceControl, setDeviceControl] = useState<boolean | null>(null);
  const localDraftKey = `aikeeper_action_draft:${roomId}`;

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(localDraftKey) || 'null') as {
        text?: string;
        updatedAt?: number;
      } | null;
      if (saved?.text && saved.updatedAt && Date.now() - saved.updatedAt <= 30 * 24 * 60 * 60 * 1000) {
        setInputText(saved.text);
        setActionStatus('typing');
      } else if (saved) {
        localStorage.removeItem(localDraftKey);
      }
    } catch {
      localStorage.removeItem(localDraftKey);
    }
  }, [localDraftKey]);

  useEffect(() => {
    let cancelled = false;
    reconnectPlayer()
      .then(async (data) => {
        if (cancelled) return;
        setStateVersion(data.stateVersion || 0);
        if (data.sceneState?.currentScene) {
          setMapRefresh((value) => value + 1);
        }
        restoredSequence.current = data.last_sequence || 0;
        wsRef.current?.setLastSequence(restoredSequence.current);
        const pending = data.pending_actions?.[0];
        if (pending?.action_id) {
          const authoritative = await getActionReceipt(pending.action_id);
          if (cancelled) return;
          setReceipt(authoritative);
          setActionStatus(authoritative.status);
          const savedDraft = localStorage.getItem(localDraftKey);
          if (savedDraft) {
            setActionError('服务器行动优先；你的本地草稿已保留，当前行动结束后可继续编辑。');
          }
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [localDraftKey, roomId]);

  useEffect(() => {
    let mounted = true;
    const claim = async () => {
      try {
        const session = await claimPlayerDevice();
        if (mounted) setDeviceControl(session.controller);
      } catch (error) {
        if (mounted && error instanceof PlayerApiError && error.status === 409) {
          setDeviceControl(false);
        }
      }
    };
    void claim();
    const heartbeat = window.setInterval(() => { void claim(); }, 15 * 60 * 1000);
    return () => {
      mounted = false;
      window.clearInterval(heartbeat);
    };
  }, [roomId]);

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
    const text = inputText.trim();
    if (!text || draft || (receipt && isActionInFlight(receipt.status))) return;
    if (!['idle', 'typing'].includes(actionStatus) || lastEphemeralText.current === text) return;
    const timer = window.setTimeout(async () => {
      lastEphemeralText.current = text;
      setActionStatus('analyzing');
      try {
        const preview = await analyzeActionDraft({
          declared_intent: text,
          base_state_version: stateVersion,
          ephemeral: true,
        });
        setEphemeralPreview(preview);
      } catch (error) {
        if (!(error instanceof PlayerApiError && error.status === 403)) {
          setActionError(formatPlayerApiError(error));
        }
      } finally {
        setActionStatus('typing');
      }
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [actionStatus, draft, inputText, receipt, stateVersion]);

  useEffect(() => {
    const token = getSlotValue('player_token') || '';
    const ws = new PlayerWS(roomId);
    wsRef.current = ws;
    ws.setLastSequence(restoredSequence.current);
    ws.onStatus((status) => {
      setConnectionStatus(status);
      if (status === 'unauthorized') {
        setActionError('玩家凭证已失效，请重新从邀请链接进入房间。');
      }
    });
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
      } else if (event.type === 's2c_action_queued' || event.type === 's2c_action_batched') {
        const payload = event.payload as { actionId?: string; status?: ActionStatus };
        setActionStatus(payload.status || (event.type === 's2c_action_queued' ? 'queued' : 'batched'));
        if (payload.actionId) {
          getActionReceipt(payload.actionId)
            .then((incoming) => setReceipt((current) => mergeAuthoritativeReceipt(current, incoming)))
            .catch(() => {});
        }
      } else if (
        event.type === 's2c_action_completed'
        || event.type === 's2c_action_choice_requested'
        || event.type === 's2c_action_review_resolved'
      ) {
        const eventPayload = event.payload as { actionId?: string; status?: ActionStatus };
        setActionStatus(eventPayload.status || (
          event.type === 's2c_action_choice_requested' ? 'awaiting_player_choice' : 'completed'
        ));
        if (eventPayload.actionId) {
          getActionReceipt(eventPayload.actionId)
            .then((incoming) => {
              setReceipt((current) => mergeAuthoritativeReceipt(current, incoming));
              setActionStatus(incoming.status);
            })
            .catch(() => {});
        }
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
        const payload = event.payload as {
          patches?: Array<{ op?: string; path?: string; value?: { name?: string } }>;
          nextStateVersion?: number;
          stateVersion?: number;
        };
        const nextVersion = payload.stateVersion ?? payload.nextStateVersion;
        if (typeof nextVersion === 'number') setStateVersion(nextVersion);
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
    return () => {
      wsRef.current = null;
      ws.disconnect();
    };
  }, [roomId]);

  const confirmDraft = async (nextDraft: ActionDraftDTO) => {
    if (!nextDraft.draft_id) return;
    if (deviceControl === false) {
      setActionError('此设备为只读。请先接管主控设备，再提交行动。');
      return;
    }
    setActionError('');
    try {
      const nextReceipt = await confirmActionDraft(
        nextDraft.draft_id,
        nextDraft.confirmation_requirements,
        createConfirmIdempotencyKey(nextDraft),
      );
      setDraft(null);
      setEphemeralPreview(null);
      setReceipt(nextReceipt);
      setActionStatus(nextReceipt.status);
      setMessages((prev) => [...prev.slice(-49), {
        id: nextReceipt.action_id,
        sender: 'player',
        text: nextDraft.declared_intent,
        timestamp: Date.now(),
      }]);
      setInputText('');
      localStorage.removeItem(localDraftKey);
    } catch (error) {
      setActionError(formatPlayerApiError(error));
      if (error instanceof PlayerApiError && error.detail && typeof error.detail === 'object'
        && 'code' in error.detail && error.detail.code === 'sync_required') {
        setActionStatus('sync_required');
      } else {
        setActionStatus('awaiting_confirmation');
      }
    }
  };

  const submitAction = async (
    overrideText?: string,
    intentType = 'dialogue',
    params: Record<string, unknown> = {},
  ) => {
    const declaredIntent = (overrideText ?? inputText).trim();
    if (!declaredIntent || draft || (receipt && isActionInFlight(receipt.status))) return;
    if (deviceControl === false) {
      setActionError('此设备为只读。请先接管主控设备，再提交行动。');
      return;
    }
    setActionError('');
    setActionStatus('analyzing');
    try {
      const analyzed = await analyzeActionDraft({
        declared_intent: declaredIntent,
        intent_type: intentType,
        params,
        base_state_version: stateVersion,
        ephemeral: false,
      });
      setEphemeralPreview(null);
      if (shouldAutoConfirmDraft(analyzed)) {
        await confirmDraft(analyzed);
      } else {
        setDraft(analyzed);
        setActionStatus('awaiting_confirmation');
      }
    } catch (error) {
      setActionError(formatPlayerApiError(error));
      setActionStatus('typing');
    }
  };

  const updateInputText = (value: string) => {
    setInputText(value);
    setDraft(null);
    setEphemeralPreview(null);
    lastEphemeralText.current = '';
    setActionStatus(value.trim() ? 'typing' : 'idle');
    if (value.trim()) {
      localStorage.setItem(localDraftKey, JSON.stringify({ text: value, updatedAt: Date.now() }));
    } else {
      localStorage.removeItem(localDraftKey);
    }
  };

  const discardDraft = async () => {
    if (draft?.draft_id) {
      await deleteActionDraft(draft.draft_id).catch(() => {});
    }
    setDraft(null);
    setEphemeralPreview(null);
    setActionStatus(inputText.trim() ? 'typing' : 'idle');
  };

  const cancelSubmittedAction = async () => {
    if (!receipt?.can_cancel) return;
    if (deviceControl === false) {
      setActionError('此设备为只读。请先接管主控设备，再撤回行动。');
      return;
    }
    try {
      const canceled = await cancelAction(receipt.action_id);
      setReceipt(canceled);
      setActionStatus(canceled.status);
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const submitTacticalAction = (action: TacticalAction) => {
    setInputText(action.label);
    void submitAction(action.label, action.intent_type, action.params);
  };

  const submitRetroClaim = () => {
    if (!claimedItemName.trim() || actionStatus !== 'idle') return;
    const itemName = claimedItemName.trim();
    const justification = claimJustification.trim() || `我主张角色背景中应有${itemName}`;
    const text = `主张物品：${itemName}。${justification}`;
    setClaimStatus('请确认行动预览');
    setInputText(text);
    setClaimOpen(false);
    void submitAction(text, 'retroactive_item_claim', {
      claimedItemName: itemName,
      justificationText: justification,
    });
  };

  const takeOverDevice = async () => {
    try {
      const session = await claimPlayerDevice(true);
      setDeviceControl(session.controller);
      setActionError('');
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  return (
    <PlayerTerminal activeTab={tab} character={character} onTabChange={setTab} isReady={isReady} charStatus={charStatus} onToggleReady={toggleReady}>
      {tab === 'home' && <CampaignHomePanel roomId={roomId} />}
      {tab === 'action' && (
        <ActionPanel
          actionStatus={actionStatus}
          connectionStatus={connectionStatus}
          actionError={actionError}
          claimJustification={claimJustification}
          claimOpen={claimOpen}
          claimStatus={claimStatus}
          claimedItemName={claimedItemName}
          inputText={inputText}
          draft={draft}
          ephemeralPreview={ephemeralPreview}
          receipt={receipt}
          messages={messages}
          pendingActions={pendingActions}
          deviceControl={deviceControl}
          onClaimJustificationChange={setClaimJustification}
          onClaimOpenChange={setClaimOpen}
          onClaimStatusChange={setClaimStatus}
          onClaimedItemNameChange={setClaimedItemName}
          onInputTextChange={updateInputText}
          onSubmitAction={submitAction}
          onConfirmAction={() => draft && void confirmDraft(draft)}
          onDiscardAction={() => void discardDraft()}
          onCancelAction={() => void cancelSubmittedAction()}
          onSubmitRetroClaim={submitRetroClaim}
          onTacticalSelect={submitTacticalAction}
          onTakeOverDevice={() => void takeOverDevice()}
        />
      )}
      {tab === 'character' && <PlayerCharacter externalResult={lastSkillCheckResult} onResultConsumed={() => setLastSkillCheckResult(null)} />}
      {tab === 'inventory' && <PlayerInventory />}
      {tab === 'logs' && <PlayerLogsPanel messages={messages} />}
      {tab === 'map' && (
        <PlayerMapPanel
          roomId={roomId}
          mapRefresh={mapRefresh}
          onMoveIntent={(text, params) => {
            setInputText(text);
            setTab('action');
            void submitAction(text, 'move', params);
          }}
        />
      )}
    </PlayerTerminal>
  );
}

interface ActionPanelProps {
  actionStatus: ActionStatus;
  connectionStatus: PlayerWSStatus;
  actionError: string;
  claimJustification: string;
  claimOpen: boolean;
  claimStatus: string;
  claimedItemName: string;
  inputText: string;
  draft: ActionDraftDTO | null;
  ephemeralPreview: ActionDraftDTO | null;
  receipt: ActionReceiptDTO | null;
  messages: PlayerChatMessage[];
  pendingActions: TacticalAction[];
  deviceControl: boolean | null;
  onClaimJustificationChange: (value: string) => void;
  onClaimOpenChange: (value: boolean) => void;
  onClaimStatusChange: (value: string) => void;
  onClaimedItemNameChange: (value: string) => void;
  onInputTextChange: (value: string) => void;
  onSubmitAction: (text?: string) => void;
  onConfirmAction: () => void;
  onDiscardAction: () => void;
  onCancelAction: () => void;
  onSubmitRetroClaim: () => void;
  onTacticalSelect: (action: TacticalAction) => void;
  onTakeOverDevice: () => void;
}

function formatPlayerApiError(error: unknown): string {
  if (!(error instanceof PlayerApiError)) return '行动提交失败，请稍后重试。';
  if (error.detail && typeof error.detail === 'object' && 'code' in error.detail) {
    const code = String(error.detail.code);
    const messages: Record<string, string> = {
      action_already_submitted: '本回合已有一条有效行动，请先撤回或等待结算。',
      confirmation_required: '仍有风险项未确认。',
      draft_analysis_disabled: '本房间已关闭停顿分析，你仍可手动生成行动预览。',
      sync_required: '世界状态已变化，请同步后重新确认行动。',
      v2_action_draft_required: '此房间必须通过行动预览提交。',
    };
    return messages[code] || `行动处理失败：${code}`;
  }
  return `行动处理失败（${error.status}）`;
}

function ActionPanel({
  actionStatus,
  connectionStatus,
  actionError,
  claimJustification,
  claimOpen,
  claimStatus,
  claimedItemName,
  inputText,
  draft,
  ephemeralPreview,
  receipt,
  messages,
  pendingActions,
  deviceControl,
  onClaimJustificationChange,
  onClaimOpenChange,
  onClaimStatusChange,
  onClaimedItemNameChange,
  onInputTextChange,
  onSubmitAction,
  onConfirmAction,
  onDiscardAction,
  onCancelAction,
  onSubmitRetroClaim,
  onTacticalSelect,
  onTakeOverDevice,
}: ActionPanelProps) {
  const isIdle = !draft && !(receipt && isActionInFlight(receipt.status));

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">TACTICAL CHANNEL</span>
      <h2 className="bh-panel-title">玩家行动终端</h2>
      {connectionStatus !== 'open' && (
        <div className="bh-muted-box" role="status">
          {connectionStatus === 'unauthorized'
            ? '连接凭证失效，请重新进入房间。'
            : '正在恢复实时连接，服务器行动状态仍为准。'}
        </div>
      )}
      {deviceControl === false && (
        <div className="bh-muted-box" role="status">
          此设备正在只读观看，避免重复提交同一角色的行动。
          <button className="bh-button bh-button--yellow" type="button" onClick={onTakeOverDevice}>接管主控</button>
        </div>
      )}

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
                onSelect={onTacticalSelect}
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
            onSelect={onTacticalSelect}
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
          onSubmitAction(text);
        }}
      />

      <PlayerActionComposer
        inputText={inputText}
        phase={actionStatus}
        draft={draft}
        ephemeralPreview={ephemeralPreview}
        receipt={receipt}
        error={actionError}
        onInputChange={onInputTextChange}
        onAnalyze={() => onSubmitAction()}
        onConfirm={onConfirmAction}
        onDiscard={onDiscardAction}
        onCancelAction={onCancelAction}
      />

      <div className="bh-action-box">
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

interface MapFogRegion {
  regionId: string;
  polygon: Array<[number, number]>;
}

interface TextSceneData {
  name: string;
  description: string;
  visibleExits: string[];
  soloAdventure?: {
    nodeId: string;
    citation?: { source_ref?: string; page_number?: number };
    choices: Array<{ nodeId: string; label: string }>;
  };
}

function mapPolygonPoints(polygon: Array<[number, number]>): string {
  return polygon.map((coordinate) => {
    const x = coordinate[0] <= 1 ? coordinate[0] * 100 : coordinate[0];
    const y = coordinate[1] <= 1 ? coordinate[1] * 100 : coordinate[1];
    return `${x},${y}`;
  }).join(' ');
}

function PlayerMapPanel({
  roomId,
  mapRefresh,
  onMoveIntent,
}: {
  roomId: string;
  mapRefresh: number;
  onMoveIntent: (text: string, params: Record<string, unknown>) => void;
}) {
  const [tiles, setTiles] = useState<MapTileData[]>([]);
  const [currentTile, setCurrentTile] = useState<string | null>(null);
  const [hiddenCount, setHiddenCount] = useState(0);
  const [mapStatus, setMapStatus] = useState('no_map');
  const [mapType, setMapType] = useState<'graph' | 'image' | 'hybrid'>('graph');
  const [mapImageUrl, setMapImageUrl] = useState('');
  const [fogRegions, setFogRegions] = useState<MapFogRegion[]>([]);
  const [textScene, setTextScene] = useState<TextSceneData | null>(null);
  const [loading, setLoading] = useState(true);
  const [movePending, setMovePending] = useState(false);
  const [secretMove, setSecretMove] = useState(false);

  const fetchMap = () => {
    const token = getSlotValue('player_token') || '';
    fetch(`/api/maps/${encodeURIComponent(roomId)}`, {
      headers: { 'X-Room-Token': token },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Record<string, any> | null) => {
        if (data) {
          setTiles((data.nodes || []) as MapTileData[]);
          setCurrentTile((data.currentNodeId || null) as string | null);
          setHiddenCount(Number(data.hiddenCount || 0));
          setMapStatus(String(data.mapStatus || 'no_map'));
          setFogRegions((data.fogRegionAreas || []) as MapFogRegion[]);
          setTextScene((data.textScene || null) as TextSceneData | null);
          const nextMapType = data.mapType === 'image' || data.mapType === 'hybrid' ? data.mapType : 'graph';
          setMapType(nextMapType);
          const assetId = String(data.baseAsset?.assetId || '');
          if (!assetId) {
            setMapImageUrl('');
            return;
          }
          fetch(`/api/maps/${encodeURIComponent(roomId)}/assets/${encodeURIComponent(assetId)}`, {
            headers: { 'X-Room-Token': token },
          })
            .then((assetResponse) => assetResponse.ok ? assetResponse.blob() : null)
            .then((blob) => {
              if (!blob) return;
              setMapImageUrl((previous) => {
                if (previous) URL.revokeObjectURL(previous);
                return URL.createObjectURL(blob);
              });
            })
            .catch(() => setMapImageUrl(''));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchMap();
  }, [roomId, mapRefresh]);

  useEffect(() => () => {
    if (mapImageUrl) URL.revokeObjectURL(mapImageUrl);
  }, [mapImageUrl]);

  const handleMove = async (nodeId: string) => {
    setMovePending(true);
    const target = tiles.find((tile) => tile.nodeId === nodeId);
    const targetName = target?.name || '目标地点';
    onMoveIntent(secretMove ? `我偷偷前往${targetName}` : `移动到${targetName}`, {
      targetNodeId: nodeId,
      fromNodeId: currentTile || '',
      secretMove,
    });
    setMovePending(false);
  };

  const handleSoloMove = (nodeId: string) => {
    const sourceNodeId = textScene?.soloAdventure?.nodeId || '';
    if (!sourceNodeId) return;
    setMovePending(true);
    onMoveIntent(`转到条目 ${nodeId}`, {
      targetNodeId: nodeId,
      fromNodeId: sourceNodeId,
    });
    setMovePending(false);
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

  if (!loading && mapStatus === 'text_mode') {
    return (
      <section className="bh-panel">
        <span className="bh-eyebrow">TEXT SCENE</span>
        <h2 className="bh-panel-title">{textScene?.name || '当前场景'}</h2>
        <div className="bh-map-info" style={{ marginTop: 12 }}>
          <p style={{ fontWeight: 700 }}>{textScene?.description || '请根据当前叙事行动。'}</p>
          {textScene?.visibleExits?.length ? (
            <p className="bh-eyebrow" style={{ fontSize: 9 }}>
              可见出口：{textScene.visibleExits.join('、')}
            </p>
          ) : null}
          {textScene?.soloAdventure?.choices?.length ? (
            <div className="bh-action-box" style={{ marginTop: 12 }}>
              {textScene.soloAdventure.choices.map((choice) => (
                <button
                  className="bh-button bh-button--yellow"
                  disabled={movePending}
                  key={choice.nodeId}
                  onClick={() => handleSoloMove(choice.nodeId)}
                  type="button"
                >
                  {choice.label}
                </button>
              ))}
            </div>
          ) : null}
          {textScene?.soloAdventure?.citation?.source_ref ? (
            <p className="bh-eyebrow" style={{ fontSize: 9, marginTop: 10 }}>
              原文定位：{textScene.soloAdventure.citation.source_ref}
            </p>
          ) : null}
        </div>
        <p style={{ fontSize: 12, color: 'var(--bh-dim)', marginTop: 12 }}>
          本场景未使用可点击地图；你仍可在行动区描述探索、交谈或移动意图。
        </p>
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
      <label className="bh-muted-box" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <input type="checkbox" checked={secretMove} onChange={(event) => setSecretMove(event.target.checked)} />
        秘密移动：将隐藏你的 Token，并要求额外确认；越界或无法安全裁决时会进入 Host 异常队列。
      </label>

      <div
        className={`bh-map-grid bh-map-grid--${mapType}`}
        style={mapImageUrl ? { backgroundImage: `url(${mapImageUrl})` } : undefined}
      >
        {(mapType === 'image' || mapType === 'hybrid') && fogRegions.length > 0 && (
          <svg
            aria-label="地图迷雾"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 1 }}
          >
            {fogRegions.map((region) => (
              <polygon
                key={region.regionId}
                points={mapPolygonPoints(region.polygon)}
                fill="rgba(17, 17, 17, 0.86)"
              />
            ))}
          </svg>
        )}
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
              style={{ position: 'absolute', left: `${posX}%`, top: `${posY}%`, zIndex: 2 }}
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
