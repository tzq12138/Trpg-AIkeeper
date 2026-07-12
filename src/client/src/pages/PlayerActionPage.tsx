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
  getActionHints,
  getActionReceipt,
  PlayerApiError,
  reconnectPlayer,
} from '../shared/player-api';
import {
  canStartNewAction,
  createConfirmIdempotencyKey,
  isActionInFlight,
  mergeAuthoritativeReceipt,
  shouldAutoConfirmDraft,
} from '../shared/player-action-controller';
import type {
  ActionDraftDTO,
  ActionReceiptDTO,
  ActionStatus,
  AiStageName,
  AiStageProgress,
  CharacterSheet,
  EngineEvent,
  PlayerChatMessage,
  SemanticMapProjectionDTO,
  SkillCheckResult,
  TacticalAction,
} from '../types';
import type { PlayerTabKey } from '../navigation';
export { default as RedactedCitationDisclosure } from '../components/RedactedCitationDisclosure';

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

export type NarrativeFeedItem = {
  id: string;
  kind: 'kp_narration' | 'environment_change' | 'interactable_object' | 'open_question' | 'judgement' | 'clarification' | 'recovery' | 'player';
  text: string;
};

const AI_STAGE_ORDER: AiStageName[] = [
  'retrieving',
  'directing',
  'validating_rules',
  'narrating',
  'recovering',
  'completed',
];

export function applyActionInspiration(text: string): { inputText: string; shouldSubmit: false } {
  return { inputText: text, shouldSubmit: false };
}

export function NarrativeFeed({
  items,
  recoveryText,
}: {
  items: NarrativeFeedItem[];
  recoveryText?: string;
}) {
  return (
    <section className="bh-panel bh-narrative-feed" aria-label="叙事对话流">
      <span className="bh-eyebrow">叙事对话流</span>
      <h2 className="bh-panel-title">你眼前发生的事</h2>
      {recoveryText ? <div className="bh-muted-box">{recoveryText}</div> : null}
      <div className="bh-message-list" aria-live="polite">
        {items.length === 0 ? (
          <article className="bh-message">等待 KP 叙事，或用自然语言描述你的下一步。</article>
        ) : items.map((item) => (
          <article key={item.id} className={`bh-message bh-message--${item.kind}`}>
            <span className="bh-eyebrow">{item.kind}</span>
            <p>{item.text}</p>
          </article>
        ))}
      </div>
      <PlayerAuxiliarySidebar activeTab="action" />
    </section>
  );
}

export function AiStageIndicator({ progress }: { progress: AiStageProgress }) {
  const currentIndex = AI_STAGE_ORDER.indexOf(progress.stage);
  return (
    <section className="bh-ai-stage" aria-label="AI 阶段">
      <div className="bh-action-row bh-action-row--responsive">
        {AI_STAGE_ORDER.map((stage, index) => (
          <span
            key={stage}
            className={`bh-eyebrow ${index <= currentIndex ? 'bh-ai-stage--done' : ''} ${stage === progress.stage ? 'bh-ai-stage--active' : ''}`}
          >
            {stage}
          </span>
        ))}
      </div>
      <p className="bh-muted-box">{progress.detail || progress.label || progress.stage}</p>
    </section>
  );
}

export function PlayerAuxiliarySidebar({ activeTab }: { activeTab: PlayerTabKey }) {
  const panels = [
    ['角色', '角色卡、状态和技能保留在侧栏中。'],
    ['物品', '物品与主张能力保留为辅助入口。'],
    ['线索', '线索、问题和证据板保留为辅助入口。'],
    ['地图', activeTab === 'map' ? '当前地图已打开。' : '地图移入可折叠侧栏。'],
    ['历史', '历史记录保留为回看入口。'],
  ];
  return (
    <aside className="bh-player-auxiliary" aria-label="辅助面板">
      <span className="bh-eyebrow">辅助面板</span>
      {panels.map(([label, text]) => (
        <details key={label}>
          <summary>{label}</summary>
          <p>{text}</p>
        </details>
      ))}
    </aside>
  );
}

export function SemanticMapPanel({ projection }: { projection: SemanticMapProjectionDTO }) {
  return (
    <section className="bh-panel bh-semantic-map" aria-label="语义地图">
      <span className="bh-eyebrow">语义地图 · 只读</span>
      <h2 className="bh-panel-title">{projection.partyPosition?.label || '已知区域'}</h2>
      {projection.baseAsset?.assetId ? <p className="bh-muted-box">图片底图已加载</p> : null}
      {projection.textScene ? (
        <div className="bh-map-info">
          <strong>{projection.textScene.name}</strong>
          <p>{projection.textScene.description}</p>
        </div>
      ) : null}
      <div className={`bh-map-grid bh-map-grid--${projection.mapType || 'graph'}`}>
        {projection.knownConnections.map((connection, index) => (
          <span key={`${connection.fromNodeId}-${connection.toNodeId}-${index}`} className="bh-map-edge-label">
            {connection.label || `${connection.fromNodeId} → ${connection.toNodeId}`}
          </span>
        ))}
        {projection.knownLocations.map((location) => (
          <div
            key={location.nodeId}
            className={`bh-map-node ${location.isCurrent ? 'bh-map-node--current' : 'bh-map-node--explored'}`}
            style={{
              position: 'absolute',
              left: `${location.position?.x ?? 50}%`,
              top: `${location.position?.y ?? 50}%`,
              zIndex: 2,
            }}
            title={location.description || location.label}
          >
            <span className="bh-map-node-name">{location.label}</span>
          </div>
        ))}
      </div>
      {projection.fogOfWar.length > 0 ? (
        <p className="bh-muted-box">迷雾区域：{projection.fogOfWar.length}</p>
      ) : null}
      <p className="bh-muted-box">移动请在自然语言输入中描述，系统会生成行动预览。</p>
    </section>
  );
}

export default function PlayerActionPage({
  roomId,
  initialTab = 'home',
}: {
  roomId: string;
  initialTab?: PlayerTabKey;
}) {
  const [tab, setTab] = useState<PlayerTabKey>(initialTab);
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
  const [aiProgress, setAiProgress] = useState<AiStageProgress>({ stage: 'completed', status: 'idle', label: '待命' });
  const [recoveryText, setRecoveryText] = useState('');
  const [actionHints, setActionHints] = useState<string[]>([]);
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
          const latestStage = [...(authoritative.timeline || [])].reverse()
            .map((event) => event.metadata?.ai_stage || event.metadata?.stage)
            .find((stage): stage is AiStageName => typeof stage === 'string' && AI_STAGE_ORDER.includes(stage as AiStageName));
          if (latestStage) {
            setAiProgress({ stage: latestStage, status: latestStage === 'completed' ? 'completed' : 'active', detail: '已从行动时间线恢复。' });
            setRecoveryText('已从行动时间线恢复。');
          }
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
      } else if (event.type === 's2c_ai_stage_changed') {
        const payload = event.payload as { stage?: AiStageName; label?: string; detail?: string };
        if (payload.stage && AI_STAGE_ORDER.includes(payload.stage)) {
          setAiProgress({ stage: payload.stage, status: 'active', label: payload.label, detail: payload.detail });
        }
      } else if (event.type === 's2c_ai_recovery_required') {
        const payload = event.payload as { actionId?: string };
        setAiProgress({ stage: 'recovering', status: 'active', label: '恢复中', detail: 'AI 正在恢复本次行动。' });
        setRecoveryText('AI 正在恢复本次行动。');
        if (payload.actionId) {
          getActionReceipt(payload.actionId)
            .then((incoming) => {
              setReceipt((current) => mergeAuthoritativeReceipt(current, incoming));
              setActionStatus(incoming.status);
            })
            .catch(() => {});
        }
      } else if (event.type === 's2c_director_plan_validated') {
        setAiProgress({ stage: 'validating_rules', status: 'completed', label: '导演计划已验证' });
      } else if (event.type === 's2c_narration_completed') {
        setAiProgress({ stage: 'completed', status: 'completed', label: '叙事完成' });
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

  const requestActionHints = async () => {
    try {
      const response = await getActionHints();
      setActionHints((response.hints || []).slice(0, 5));
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const applyHint = (hint: string) => {
    const result = applyActionInspiration(hint);
    updateInputText(result.inputText);
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
    if (!claimedItemName.trim() || !canStartNewAction(draft, receipt)) return;
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
      {tab === 'home' && (
        <CampaignHomePanel roomId={roomId} onContinueScene={() => setTab('map')} />
      )}
      {tab === 'action' && (
        <ActionPanel
          actionStatus={actionStatus}
          connectionStatus={connectionStatus}
          actionError={actionError}
          aiProgress={aiProgress}
          actionHints={actionHints}
          claimJustification={claimJustification}
          claimOpen={claimOpen}
          claimStatus={claimStatus}
          claimedItemName={claimedItemName}
          inputText={inputText}
          draft={draft}
          ephemeralPreview={ephemeralPreview}
          receipt={receipt}
          messages={messages}
          recoveryText={recoveryText}
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
          onRequestActionHints={() => void requestActionHints()}
          onApplyHint={applyHint}
        />
      )}
      {tab === 'character' && <PlayerCharacter externalResult={lastSkillCheckResult} onResultConsumed={() => setLastSkillCheckResult(null)} />}
      {tab === 'inventory' && <PlayerInventory />}
      {tab === 'logs' && <PlayerLogsPanel messages={messages} />}
      {tab === 'map' && (
        <PlayerMapPanel
          roomId={roomId}
          mapRefresh={mapRefresh}
        />
      )}
    </PlayerTerminal>
  );
}

interface ActionPanelProps {
  actionStatus: ActionStatus;
  connectionStatus: PlayerWSStatus;
  actionError: string;
  aiProgress: AiStageProgress;
  actionHints: string[];
  claimJustification: string;
  claimOpen: boolean;
  claimStatus: string;
  claimedItemName: string;
  inputText: string;
  draft: ActionDraftDTO | null;
  ephemeralPreview: ActionDraftDTO | null;
  receipt: ActionReceiptDTO | null;
  messages: PlayerChatMessage[];
  recoveryText: string;
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
  onRequestActionHints: () => void;
  onApplyHint: (hint: string) => void;
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
  aiProgress,
  actionHints,
  claimJustification,
  claimOpen,
  claimStatus,
  claimedItemName,
  inputText,
  draft,
  ephemeralPreview,
  receipt,
  messages,
  recoveryText,
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
  onRequestActionHints,
  onApplyHint,
}: ActionPanelProps) {
  const isIdle = canStartNewAction(draft, receipt);
  const narrativeItems: NarrativeFeedItem[] = messages.map((message) => ({
    id: message.id,
    kind: message.sender === 'player' ? 'player' : message.sender === 'system' ? 'recovery' : 'kp_narration',
    text: message.text,
  }));

  return (
    <section
      className="bh-panel bh-player-narrative-layout bh-player-narrative-layout--mobile-safe"
      data-safe-widths="360 390 430"
    >
      <span className="bh-eyebrow">TACTICAL CHANNEL</span>
      <h2 className="bh-panel-title">自然语言行动</h2>
      <NarrativeFeed items={narrativeItems} recoveryText={recoveryText} />
      <AiStageIndicator progress={aiProgress} />
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

      <div className="bh-action-box">
        <button className="bh-button" type="button" onClick={onRequestActionHints}>
          给我一些行动灵感
        </button>
        {actionHints.length > 0 && (
          <div className="bh-hint-list">
            {actionHints.slice(0, 5).map((hint) => (
              <button className="bh-button" key={hint} type="button" onClick={() => onApplyHint(hint)}>
                {hint}
              </button>
            ))}
          </div>
        )}
      </div>

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

function PlayerMapPanel({
  roomId,
  mapRefresh,
}: {
  roomId: string;
  mapRefresh: number;
}) {
  const [mapStatus, setMapStatus] = useState('no_map');
  const [mapImageUrl, setMapImageUrl] = useState('');
  const [projection, setProjection] = useState<SemanticMapProjectionDTO | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchMap = () => {
    const token = getSlotValue('player_token') || '';
    fetch(`/api/maps/${encodeURIComponent(roomId)}`, {
      headers: { 'X-Room-Token': token },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Record<string, any> | null) => {
        if (data) {
          const knownLocations = Array.isArray(data.knownLocations)
            ? data.knownLocations
            : (data.nodes || []).map((node: Record<string, any>) => ({
              nodeId: node.nodeId,
              label: node.name,
              description: node.description,
              isCurrent: node.isCurrent || node.nodeId === data.currentNodeId,
              position: node.position,
            }));
          const knownConnections = Array.isArray(data.knownConnections) ? data.knownConnections : [];
          setProjection({
            roomId: String(data.roomId || roomId),
            mapStatus: String(data.mapStatus || 'active'),
            mapType: data.mapType === 'image' || data.mapType === 'hybrid' ? data.mapType : 'graph',
            baseAsset: data.baseAsset || {},
            knownLocations,
            knownConnections,
            partyPosition: data.partyPosition || knownLocations.find((location: any) => location.isCurrent) || null,
            fogOfWar: Array.isArray(data.fogOfWar) ? data.fogOfWar : (data.fogRegionAreas || []),
            textScene: data.textScene || null,
          });
          setMapStatus(String(data.mapStatus || 'no_map'));
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

  if (!loading && projection) {
    return <SemanticMapPanel projection={projection} />;
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

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">INVESTIGATION MAP</span>
      <h2 className="bh-panel-title">调查区域地图</h2>
      <div
        className="bh-map-grid bh-map-grid--readonly"
        style={mapImageUrl ? { backgroundImage: `url(${mapImageUrl})` } : undefined}
      />
      <p className="bh-muted-box">地图仅显示已知信息。移动请在行动区用自然语言描述。</p>
    </section>
  );
}
