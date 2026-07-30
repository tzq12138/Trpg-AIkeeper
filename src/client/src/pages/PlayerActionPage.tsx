import { useEffect, useRef, useState } from 'react';
import PlayerCharacter from './PlayerCharacter';
import PlayerInventory from './PlayerInventory';
import { getSlotValue } from '../shared/identity';
import TacticalButtons from '../components/TacticalButtons';
import PlayerTerminal from '../components/PlayerTerminal';
import VoiceInput from '../components/VoiceInput';
import PlayerActionComposer from '../components/PlayerActionComposer';
import AbsentPolicyControl, { type AbsentPolicy } from '../components/AbsentPolicyControl';
import CampaignHomePanel from '../components/CampaignHomePanel';
import CollaborationContractPanel from '../components/CollaborationContractPanel';
import { PlayerWS, type PlayerWSStatus } from '../ws';
import { apiFetch, authHeaders } from '../api';
import {
  analyzeActionDraft,
  cancelAction,
  cancelCollaborationContract,
  claimPlayerDevice,
  confirmActionDraft,
  createCollaborationContract,
  declareCombatRoundIdle as declareCombatRoundIdleApi,
  deleteActionDraft,
  getActionHints,
  getActionReceipt,
  getCampaignHome,
  resolveCompositeActionChoice,
  getCurrentActionDraft,
  getCollaborationContracts,
  getCollaborationParticipants,
  getPendingEncounterReaction,
  getPlayerCombatRound,
  getPlayerSettings,
  getRuleQuestions,
  getSafetyState,
  nextPlayerActionSequence,
  PlayerApiError,
  respondToCollaborationContract,
  type CollaborationContractDTO,
  type CollaborationParticipantDTO,
  type PlayerRuleQuestionDTO,
  type PlayerSafetyStateDTO,
  receiveActionSubmission,
  reconnectPlayer,
  resumeSafetyPause,
  reviseActionDraft,
  resolveEncounterReaction,
  updatePlayerSettings,
} from '../shared/player-api';
import {
  canSendWhileStatefulActionBusy,
  isStatefulPlayerInputMode,
  recordedInputSummary,
  type PlayerInputMode,
} from '../shared/player-input-modes';
import {
  getPlayerPendingTaskCount,
  getPlayerCurrentPriority,
  type PlayerCurrentPriority,
  type PlayerCurrentPriorityInput,
} from '../shared/player-current-priority';
import {
  countUnreadPlayerNotifications,
  readNotificationReadSequence,
  writeNotificationReadSequence,
  type PlayerNotificationEvent,
} from '../shared/player-notifications';
import { combatRoundSummaryText } from '../shared/combat-round-summary';
import { lockCombatRoundReceipt } from '../shared/combat-round-lock';
import {
  getCombatTargetTags,
  isCombatTargetOnlyDraft,
  toggleCombatTargetTag,
} from '../shared/combat-target-tags';
import { formatTeamMessageText } from '../shared/team-message';
import type { InventoryTransferDTO } from '../shared/inventory-transfer-api';
import {
  canStartNewAction,
  createConfirmIdempotencyKey,
  isActionInFlight,
  mergeAuthoritativeReceipt,
  AUTO_CONFIRM_GRACE_MS,
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
  PlayerCombatRoundDTO,
  SemanticMapProjectionDTO,
  SkillCheckResult,
  SoloCombatReactionDTO,
  TacticalAction,
} from '../types';
import type { PlayerTabKey } from '../navigation';
export { default as RedactedCitationDisclosure } from '../components/RedactedCitationDisclosure';

export function getActionPanelCurrentPriority(input: PlayerCurrentPriorityInput) {
  return getPlayerCurrentPriority(input);
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

export function shouldApplyEphemeralAnalysis(requestEpoch: number, currentEpoch: number): boolean {
  return requestEpoch === currentEpoch;
}

export function narrationFollowUpItems(
  payload: {
    environmentChanges?: unknown;
    interactableObjects?: unknown;
    openQuestion?: unknown;
  },
  eventId: string,
): NarrativeFeedItem[] {
  const environmentChanges = Array.isArray(payload.environmentChanges)
    ? payload.environmentChanges.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).slice(0, 3)
    : [];
  const interactableObjects = Array.isArray(payload.interactableObjects)
    ? payload.interactableObjects.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).slice(0, 5)
    : [];
  const openQuestion = typeof payload.openQuestion === 'string' ? payload.openQuestion.trim() : '';
  const items: NarrativeFeedItem[] = environmentChanges.map((text, index) => ({
    id: `${eventId}-environment-${index}`,
    kind: 'environment_change',
    text,
  }));
  if (interactableObjects.length > 0) {
    items.push({
      id: `${eventId}-interactable-0`,
      kind: 'interactable_object',
      text: `可交互：${interactableObjects.join('、')}`,
    });
  }
  if (openQuestion) {
    items.push({ id: `${eventId}-question`, kind: 'open_question', text: openQuestion });
  }
  return items;
}

export function mergeNarrationDetails(
  previous: NarrativeFeedItem[],
  incoming: NarrativeFeedItem[],
): NarrativeFeedItem[] {
  const incomingKinds = new Set(incoming.map((item) => item.kind));
  return [
    ...previous.filter((item) => !incomingKinds.has(item.kind)),
    ...incoming,
  ].slice(-30);
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

export function SemanticMapPanel({
  projection,
  imageUrl = '',
}: {
  projection: SemanticMapProjectionDTO;
  imageUrl?: string;
}) {
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
        {imageUrl ? <img className="bh-map-base-asset" src={imageUrl} alt="当前地图底图" /> : null}
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
  initialTab = 'action',
}: {
  roomId: string;
  initialTab?: PlayerTabKey;
}) {
  const [tab, setTab] = useState<PlayerTabKey>(initialTab);
  const [character, setCharacter] = useState<CharacterSheet | null>(null);
  const [inputText, setInputText] = useState('');
  const [inputMode, setInputMode] = useState<PlayerInputMode>('action');
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
  const analysisEpoch = useRef(0);
  const [messages, setMessages] = useState<PlayerChatMessage[]>([]);
  const [ruleQuestions, setRuleQuestions] = useState<PlayerRuleQuestionDTO[]>([]);
  const [safetyState, setSafetyState] = useState<PlayerSafetyStateDTO>({
    status: 'active',
    activePauseCount: 0,
    canResume: false,
    ownRequestIds: [],
  });
  const [narrationDetails, setNarrationDetails] = useState<NarrativeFeedItem[]>([]);
  const [pendingActions, setPendingActions] = useState<TacticalAction[]>([]);
  const [pendingCombatReaction, setPendingCombatReaction] = useState<SoloCombatReactionDTO | null>(null);
  const [combatRound, setCombatRound] = useState<PlayerCombatRoundDTO | null>(null);
  const [absentPolicy, setAbsentPolicy] = useState<AbsentPolicy>('idle');
  const [speechRouting, setSpeechRouting] = useState<'party_message' | 'npc_dialogue'>('party_message');
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
  const [hasPendingInventoryTransfer, setHasPendingInventoryTransfer] = useState(false);
  const [hasUnresolvedPartyQuestion, setHasUnresolvedPartyQuestion] = useState(false);
  const [unreadNotifications, setUnreadNotifications] = useState({ privateResults: 0, publicClues: 0 });
  const [collaborationContracts, setCollaborationContracts] = useState<CollaborationContractDTO[]>([]);
  const [collaborationParticipants, setCollaborationParticipants] = useState<CollaborationParticipantDTO[]>([]);
  const [reconnectedRoomId, setReconnectedRoomId] = useState<string | null>(null);
  const [autoConfirmPending, setAutoConfirmPending] = useState(false);
  const localDraftKey = `aikeeper_action_draft:${roomId}`;
  const autoConfirmTimer = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const notificationReadSequence = useRef<number | null>(null);
  const latestVisibleEventSequence = useRef(0);

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

  useEffect(() => () => {
    if (autoConfirmTimer.current !== null) window.clearTimeout(autoConfirmTimer.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
    getRuleQuestions()
      .then(({ questions }) => {
        if (!cancelled) setRuleQuestions(questions);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getSafetyState()
      .then((state) => {
        if (!cancelled) setSafetyState(state);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [roomId]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [contracts, participants] = await Promise.all([
          getCollaborationContracts(),
          getCollaborationParticipants(),
        ]);
        if (!cancelled) {
          setCollaborationContracts(contracts.items);
          setCollaborationParticipants(participants.items);
        }
      } catch {
        if (!cancelled) {
          setCollaborationContracts([]);
          setCollaborationParticipants([]);
        }
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [roomId]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const home = await getCampaignHome();
        if (!cancelled) setHasUnresolvedPartyQuestion((home.unresolved_questions || []).length > 0);
      } catch {
        if (!cancelled) setHasUnresolvedPartyQuestion(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

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
        latestVisibleEventSequence.current = restoredSequence.current;
        try {
          const storedReadSequence = readNotificationReadSequence(localStorage, roomId);
          if (storedReadSequence === null) {
            notificationReadSequence.current = restoredSequence.current;
            writeNotificationReadSequence(localStorage, roomId, restoredSequence.current);
            setUnreadNotifications({ privateResults: 0, publicClues: 0 });
          } else {
            notificationReadSequence.current = storedReadSequence;
            setUnreadNotifications(countUnreadPlayerNotifications(
              (data.recent_events || []) as PlayerNotificationEvent[],
              storedReadSequence,
            ));
          }
        } catch {
          notificationReadSequence.current = restoredSequence.current;
          setUnreadNotifications({ privateResults: 0, publicClues: 0 });
        }
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
        } else {
          const currentDraft = await getCurrentActionDraft();
          if (!cancelled && currentDraft) {
            setDraft(currentDraft);
            setEphemeralPreview(null);
            setInputText(currentDraft.declared_intent);
            setActionStatus(currentDraft.status);
          } else if (!cancelled && data.pending_submissions?.[0]) {
            const submission = data.pending_submissions[0];
            setInputText(submission.raw_text);
            setInputMode(submission.input_mode);
            setActionStatus('typing');
            setRecoveryText('已恢复上次未完成的行动输入；请重新生成预览后确认。');
          }
        }
        const pendingReaction = await getPendingEncounterReaction();
        if (!cancelled) setPendingCombatReaction(pendingReaction.reaction);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setReconnectedRoomId(roomId);
      });
    return () => { cancelled = true; };
  }, [localDraftKey, roomId]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const round = await getPlayerCombatRound();
        if (!cancelled) setCombatRound(round);
      } catch {
        if (!cancelled) setCombatRound(null);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [roomId]);

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
    let cancelled = false;
    getPlayerSettings()
      .then((settings) => {
        if (!cancelled) {
          setAbsentPolicy(settings.absent_policy);
          setSpeechRouting(settings.speech_routing);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const transfers = await apiFetch<{ incoming: InventoryTransferDTO[] }>('/api/player/inventory-transfers', {
          headers: authHeaders(),
        });
        if (!cancelled) setHasPendingInventoryTransfer(
          (transfers.incoming || []).some((transfer) => transfer.status === 'pending'),
        );
      } catch {
        if (!cancelled) setHasPendingInventoryTransfer(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const text = inputText.trim();
    if (!text || !isStatefulPlayerInputMode(inputMode, speechRouting === 'npc_dialogue') || draft || (receipt && isActionInFlight(receipt.status))) return;
    if (!['idle', 'typing'].includes(actionStatus) || lastEphemeralText.current === text) return;
    const timer = window.setTimeout(async () => {
      const requestEpoch = ++analysisEpoch.current;
      lastEphemeralText.current = text;
      setActionStatus('analyzing');
      try {
        const preview = await analyzeActionDraft({
          declared_intent: text,
          base_state_version: stateVersion,
          ephemeral: true,
        });
        if (shouldApplyEphemeralAnalysis(requestEpoch, analysisEpoch.current)) {
          setEphemeralPreview(preview);
        }
      } catch (error) {
        if (
          shouldApplyEphemeralAnalysis(requestEpoch, analysisEpoch.current)
          && !(error instanceof PlayerApiError && error.status === 403)
        ) {
          setActionError(formatPlayerApiError(error));
        }
      } finally {
        if (shouldApplyEphemeralAnalysis(requestEpoch, analysisEpoch.current)) {
          setActionStatus('typing');
        }
      }
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [actionStatus, draft, inputMode, inputText, receipt, speechRouting, stateVersion]);

  useEffect(() => {
    if (reconnectedRoomId !== roomId) return;
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
      if (Number.isSafeInteger(event.roomSequence) && event.roomSequence > 0) {
        latestVisibleEventSequence.current = Math.max(latestVisibleEventSequence.current, event.roomSequence);
        const readSequence = notificationReadSequence.current;
        if (readSequence !== null) {
          const incoming = countUnreadPlayerNotifications([event], readSequence);
          if (incoming.privateResults || incoming.publicClues) {
            setUnreadNotifications((previous) => ({
              privateResults: previous.privateResults + incoming.privateResults,
              publicClues: previous.publicClues + incoming.publicClues,
            }));
          }
        }
      }
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
      } else if (event.type === 's2c_combat_round_locked') {
        setReceipt((current) => lockCombatRoundReceipt(current));
        getPlayerCombatRound().then(setCombatRound).catch(() => {});
      } else if (
        event.type === 's2c_action_queued'
        || event.type === 's2c_action_batched'
        || event.type === 's2c_action_deferred'
      ) {
        const payload = event.payload as { actionId?: string; status?: ActionStatus };
        setActionStatus(payload.status || (
          event.type === 's2c_action_queued'
            ? 'queued'
            : event.type === 's2c_action_batched'
              ? 'batched'
              : 'awaiting_host_exception'
        ));
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
        apiFetch<CharacterSheet>('/api/player/character', { headers: authHeaders() })
          .then(setCharacter)
          .catch(() => {});
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
      } else if (event.type === 's2c_turn_resolved') {
        const text = combatRoundSummaryText(event.payload);
        if (text) {
          setMessages((prev) => [...prev.slice(-49), {
            id: `combat-summary:${event.roomSequence}`,
            sender: 'system',
            text,
            timestamp: Date.now(),
          }]);
          getPlayerCombatRound().then(setCombatRound).catch(() => {});
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
      } else if (event.type === 's2c_private_notice') {
        const payload = event.payload as { text?: unknown };
        const text = typeof payload.text === 'string' && payload.text.trim()
          ? payload.text
          : '收到一条新的私密结果。';
        setMessages((prev) => [...prev.slice(-49), {
          id: `private-notice:${event.roomSequence}`,
          sender: 'system',
          text,
          timestamp: Date.now(),
        }]);
      } else if (event.type === 's2c_clue_discovered') {
        const payload = event.payload as { name?: unknown };
        const name = typeof payload.name === 'string' && payload.name.trim() ? payload.name : '一条个人线索';
        setMessages((prev) => [...prev.slice(-49), {
          id: `private-clue:${event.roomSequence}`,
          sender: 'system',
          text: `发现个人线索：${name}`,
          timestamp: Date.now(),
        }]);
      } else if (event.type === 's2c_clue_shared') {
        const payload = event.payload as { publicVersion?: unknown };
        const text = typeof payload.publicVersion === 'string' && payload.publicVersion.trim()
          ? `队伍新增公开线索：${payload.publicVersion}`
          : '队伍新增了一条公开线索。';
        setMessages((prev) => [...prev.slice(-49), {
          id: `party-clue:${event.roomSequence}`,
          sender: 'team',
          text,
          timestamp: Date.now(),
        }]);
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
        const payload = event.payload as {
          environmentChanges?: unknown;
          interactableObjects?: unknown;
          openQuestion?: unknown;
        };
        const details = narrationFollowUpItems(payload, event.eventId || crypto.randomUUID());
        if (details.length > 0) {
          setNarrationDetails((previous) => mergeNarrationDetails(previous, details));
        }
        setAiProgress({ stage: 'completed', status: 'completed', label: '叙事完成' });
      } else if (event.type === 's2c_encounter_started') {
        getPlayerCombatRound().then(setCombatRound).catch(() => {});
      } else if (event.type === 's2c_encounter_updated') {
        getPlayerCombatRound().then(setCombatRound).catch(() => {});
      } else if (event.type === 's2c_encounter_resolved') {
        setPendingActions([]);
        setPendingCombatReaction(null);
      } else if (event.type === 's2c_solo_combat_reaction_requested') {
        const payload = event.payload as { reaction?: SoloCombatReactionDTO };
        if (payload.reaction) {
          setPendingCombatReaction(payload.reaction);
          setPendingActions([]);
        }
      } else if (event.type === 's2c_team_message') {
        const p = event.payload as Record<string, unknown>;
        if (p.text && typeof p.text === 'string') {
          setMessages((prev) => [...prev.slice(-49), {
            id: crypto.randomUUID(),
            sender: 'team',
            text: formatTeamMessageText(p),
            timestamp: Date.now(),
          }]);
        }
      } else if (event.type === 's2c_safety_state_changed') {
        getSafetyState().then(setSafetyState).catch(() => {});
      }
    });
    ws.connect(token);
    return () => {
      wsRef.current = null;
      ws.disconnect();
    };
  }, [reconnectedRoomId, roomId]);

  const confirmDraft = async (
    nextDraft: ActionDraftDTO,
    selectedSkill?: string,
    compositeStepOrder?: string[],
  ) => {
    if (autoConfirmTimer.current !== null) {
      window.clearTimeout(autoConfirmTimer.current);
      autoConfirmTimer.current = null;
    }
    setAutoConfirmPending(false);
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
        selectedSkill,
        compositeStepOrder,
      );
      setDraft(null);
      setEphemeralPreview(null);
      setReceipt(nextReceipt);
      setActionStatus(nextReceipt.status);
      apiFetch<CharacterSheet>('/api/player/character', { headers: authHeaders() })
        .then(setCharacter)
        .catch(() => {});
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

  const updateCollaborationDependencies = async (characterIds: string[]) => {
    if (!draft?.draft_id) return;
    setActionError('');
    try {
      const updated = await reviseActionDraft(draft.draft_id, {
        declared_intent: draft.declared_intent,
        intent_type: draft.intent_type,
        base_state_version: draft.base_state_version,
        params: {
          ...draft.params,
          dependsOnCharacterIds: characterIds,
        },
      });
      setDraft(updated);
      setActionStatus(updated.status);
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const resolveCompositeChoice = async (proceed: boolean) => {
    if (!receipt?.action_id) return;
    setActionError('');
    try {
      const nextReceipt = await resolveCompositeActionChoice(receipt.action_id, proceed);
      setReceipt(nextReceipt);
      setActionStatus(nextReceipt.status);
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const submitAction = async (
    overrideText?: string,
    intentType?: string,
    params: Record<string, unknown> = {},
    mode: PlayerInputMode = inputMode,
  ) => {
    const declaredIntent = (overrideText ?? inputText).trim();
    if (isCombatTargetOnlyDraft(declaredIntent)) {
      setActionError('已选择目标，请继续描述你想怎么做。');
      return;
    }
    const statefulSubmission = !canSendWhileStatefulActionBusy(
      mode,
      speechRouting === 'npc_dialogue',
    );
    if (!declaredIntent || (statefulSubmission && (draft || (receipt && isActionInFlight(receipt.status)))) ) return;
    if (pendingCombatReaction && statefulSubmission) {
      setActionError('黑熊正在发动攻击；请先选择闪避或反击。');
      return;
    }
    if (deviceControl === false) {
      setActionError('此设备为只读。请先接管主控设备，再提交行动。');
      return;
    }
    setActionError('');
    analysisEpoch.current += 1;
    try {
      const submission = await receiveActionSubmission({
        actionId: crypto.randomUUID(),
        rawText: declaredIntent,
        inputMode: mode,
        clientSequence: nextPlayerActionSequence(),
        baseStateVersion: stateVersion,
      });
      if (!submission.requiresAnalysis) {
        setEphemeralPreview(null);
        setInputText('');
        if (!statefulSubmission && (draft || (receipt && isActionInFlight(receipt.status)))) {
          setActionStatus(receipt?.status || actionStatus);
        } else {
          setActionStatus('idle');
          localStorage.removeItem(localDraftKey);
        }
        if (mode === 'rule_question') {
          setRuleQuestions((previous) => [{
            actionId: submission.actionId,
            text: declaredIntent,
            createdAt: submission.receivedAt,
          }, ...previous.filter((question) => question.actionId !== submission.actionId)].slice(0, 50));
        }
        setMessages((previous) => [...previous.slice(-49), {
          id: submission.actionId,
          sender: 'system',
          text: recordedInputSummary(mode, declaredIntent),
          timestamp: Date.now(),
        }]);
        if (mode === 'safety') {
          setSafetyState((previous) => ({
            status: 'safety_paused',
            activePauseCount: Math.max(1, previous.activePauseCount + 1),
            canResume: true,
            ownRequestIds: previous.ownRequestIds.includes(submission.actionId)
              ? previous.ownRequestIds
              : [...previous.ownRequestIds, submission.actionId],
          }));
        }
        return;
      }
      setActionStatus('analyzing');
      const analyzed = await analyzeActionDraft({
        declared_intent: declaredIntent,
        intent_type: intentType,
        params,
        base_state_version: stateVersion,
        ephemeral: false,
        submission_action_id: submission.actionId,
      });
      setEphemeralPreview(null);
      if (shouldAutoConfirmDraft(analyzed)) {
        setDraft(analyzed);
        setActionStatus(analyzed.status);
        setAutoConfirmPending(true);
        autoConfirmTimer.current = window.setTimeout(() => {
          autoConfirmTimer.current = null;
          setAutoConfirmPending(false);
          void confirmDraft(analyzed);
        }, AUTO_CONFIRM_GRACE_MS);
      } else {
        setDraft(analyzed);
        setActionStatus(analyzed.status);
      }
    } catch (error) {
      setActionError(formatPlayerApiError(error));
      setActionStatus('typing');
    }
  };

  const resumeOwnSafetyPause = async () => {
    const requestId = safetyState.ownRequestIds[0];
    if (!requestId) return;
    setActionError('');
    try {
      const nextState = await resumeSafetyPause(requestId);
      setSafetyState(nextState);
      setMessages((previous) => [...previous.slice(-49), {
        id: `safety-resumed:${requestId}`,
        sender: 'system',
        text: nextState.status === 'active'
          ? '安全暂停已由你恢复，引擎可以继续结算。'
          : '你的暂停已恢复；仍有其他匿名安全暂停生效。',
        timestamp: Date.now(),
      }]);
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const updateInputText = (value: string, mode: PlayerInputMode = inputMode) => {
    if (autoConfirmTimer.current !== null) {
      window.clearTimeout(autoConfirmTimer.current);
      autoConfirmTimer.current = null;
    }
    setAutoConfirmPending(false);
    analysisEpoch.current += 1;
    setInputText(value);
    setDraft(null);
    setEphemeralPreview(null);
    lastEphemeralText.current = '';
    if (isStatefulPlayerInputMode(mode, speechRouting === 'npc_dialogue')) {
      setActionStatus(value.trim() ? 'typing' : 'idle');
      if (value.trim()) {
        localStorage.setItem(localDraftKey, JSON.stringify({ text: value, updatedAt: Date.now() }));
      } else {
        localStorage.removeItem(localDraftKey);
      }
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

  const toggleCombatTarget = (targetLabel: string) => {
    const next = toggleCombatTargetTag(inputText, targetLabel);
    if (!next.changed) {
      setActionError('本轮最多选择两个目标；请先取消一个标签。');
      return;
    }
    setActionError('');
    setInputMode('action');
    updateInputText(next.inputText, 'action');
  };

  const discardDraft = async () => {
    if (autoConfirmTimer.current !== null) {
      window.clearTimeout(autoConfirmTimer.current);
      autoConfirmTimer.current = null;
    }
    setAutoConfirmPending(false);
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
    void submitAction(action.label, action.intent_type, action.params, 'combat_action');
  };

  const resolveCombatReaction = async (choice: 'dodge' | 'counterattack') => {
    if (!pendingCombatReaction || deviceControl === false) return;
    setActionError('');
    try {
      const outcome = await resolveEncounterReaction(pendingCombatReaction.reactionId, choice);
      setPendingCombatReaction(outcome.nextReaction);
      const receivedDamage = Number(outcome.result.damageToPlayer || 0);
      const dealtDamage = Number(outcome.result.damageToAttacker ?? outcome.result.damageToBear ?? 0);
      const attackerName = pendingCombatReaction.attackerName || '敌人';
      setMessages((previous) => [...previous.slice(-49), {
        id: outcome.reaction.reactionId,
        sender: 'system',
        text: outcome.result.playerWins
          ? `你${choice === 'dodge' ? '闪开了' : '反击成功'}${attackerName}的${pendingCombatReaction.attackName}${dealtDamage ? `，造成 ${dealtDamage} 点伤害` : ''}。`
          : `${attackerName}的${pendingCombatReaction.attackName}命中，受到 ${receivedDamage} 点伤害。`,
        timestamp: Date.now(),
      }]);
      if (outcome.soloTransition) {
        setMapRefresh((value) => value + 1);
      }
      const updatedCharacter = await apiFetch<CharacterSheet>('/api/player/character', { headers: authHeaders() });
      setCharacter(updatedCharacter);
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
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
    }, 'item_action');
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

  const changeAbsentPolicy = async (policy: AbsentPolicy) => {
    try {
      const settings = await updatePlayerSettings({ absent_policy: policy });
      setAbsentPolicy(settings.absent_policy);
      setActionError('');
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const declareCombatRoundIdle = async () => {
    if (deviceControl === false) return;
    setActionError('');
    try {
      await declareCombatRoundIdleApi();
      setCombatRound(await getPlayerCombatRound());
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const markNotificationsRead = () => {
    const nextSequence = latestVisibleEventSequence.current;
    if (notificationReadSequence.current === null || nextSequence <= notificationReadSequence.current) return;
    notificationReadSequence.current = nextSequence;
    try {
      writeNotificationReadSequence(localStorage, roomId, nextSequence);
    } catch {}
    setUnreadNotifications({ privateResults: 0, publicClues: 0 });
  };

  const refreshCollaboration = async () => {
    const [contracts, participants] = await Promise.all([
      getCollaborationContracts(),
      getCollaborationParticipants(),
    ]);
    setCollaborationContracts(contracts.items);
    setCollaborationParticipants(participants.items);
  };

  const createCollaboration = async (sharedIntent: string, inviteeCharacterIds: string[]) => {
    setActionError('');
    try {
      await createCollaborationContract(sharedIntent, inviteeCharacterIds);
      await refreshCollaboration();
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const respondToCollaboration = async (contractId: string, decision: 'accept' | 'decline') => {
    setActionError('');
    try {
      const contract = await respondToCollaborationContract(contractId, decision);
      await refreshCollaboration();
      if (contract.status === 'accepted') {
        const linkedDraft = await getCurrentActionDraft();
        if (linkedDraft) {
          setDraft(linkedDraft);
          setEphemeralPreview(null);
          setInputText(linkedDraft.declared_intent);
          setActionStatus(linkedDraft.status);
        }
      }
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const cancelCollaboration = async (contractId: string) => {
    setActionError('');
    try {
      await cancelCollaborationContract(contractId);
      await refreshCollaboration();
    } catch (error) {
      setActionError(formatPlayerApiError(error));
    }
  };

  const navigatePlayerTab = (nextTab: PlayerTabKey) => {
    if (nextTab === 'logs') markNotificationsRead();
    setTab(nextTab);
  };

  const terminalPriorityInput = {
    hasPendingCombatReaction: Boolean(pendingCombatReaction),
    hasConfirmationDraft: Boolean(draft),
    hasPendingInventoryTransfer,
    hasUnresolvedPartyQuestion,
    unreadPrivateResultCount: unreadNotifications.privateResults,
    unreadPublicClueCount: unreadNotifications.publicClues,
    hasCollaborationInvite: Boolean(character?.character_id) && collaborationContracts.some((contract) => (
      contract.status === 'pending'
      && contract.initiatorCharacterId !== character?.character_id
      && contract.pendingCharacterIds.includes(character?.character_id || '')
    )),
    actionStatus,
    hasInputText: Boolean(inputText.trim()),
  };
  const terminalPriority = getPlayerCurrentPriority(terminalPriorityInput);
  const terminalPendingTaskCount = getPlayerPendingTaskCount(terminalPriorityInput);

  return (
    <PlayerTerminal activeTab={tab} character={character} onTabChange={navigatePlayerTab} isReady={isReady} charStatus={charStatus} onToggleReady={toggleReady} currentPriority={terminalPriority} pendingTaskCount={terminalPendingTaskCount}>
      {tab === 'home' && (
        <CampaignHomePanel roomId={roomId} onContinueScene={() => setTab('action')} />
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
          inputMode={inputMode}
          draft={draft}
          ephemeralPreview={ephemeralPreview}
          receipt={receipt}
          messages={messages}
          ruleQuestions={ruleQuestions}
          narrationDetails={narrationDetails}
          recoveryText={recoveryText}
          pendingActions={pendingActions}
          pendingCombatReaction={pendingCombatReaction}
          hasPendingInventoryTransfer={hasPendingInventoryTransfer}
          hasUnresolvedPartyQuestion={hasUnresolvedPartyQuestion}
          unreadPrivateResultCount={unreadNotifications.privateResults}
          unreadPublicClueCount={unreadNotifications.publicClues}
          collaborationContracts={collaborationContracts}
          collaborationParticipants={collaborationParticipants}
          autoConfirmPending={autoConfirmPending}
          safetyState={safetyState}
          combatRound={combatRound}
          absentPolicy={absentPolicy}
          speechRoutesToDialogue={speechRouting === 'npc_dialogue'}
          deviceControl={deviceControl}
          character={character}
          onClaimJustificationChange={setClaimJustification}
          onClaimOpenChange={setClaimOpen}
          onClaimStatusChange={setClaimStatus}
          onClaimedItemNameChange={setClaimedItemName}
          onInputTextChange={updateInputText}
          onToggleCombatTarget={toggleCombatTarget}
          onInputModeChange={setInputMode}
          onSubmitAction={submitAction}
          onConfirmAction={(selectedSkill, compositeStepOrder) => draft && void confirmDraft(
            draft,
            selectedSkill,
            compositeStepOrder,
          )}
          onUpdateCollaborationDependencies={(characterIds) => void updateCollaborationDependencies(characterIds)}
          onDiscardAction={() => void discardDraft()}
          onCancelAction={() => void cancelSubmittedAction()}
          onResolveCompositeChoice={(proceed) => void resolveCompositeChoice(proceed)}
          onSubmitRetroClaim={submitRetroClaim}
          onTacticalSelect={submitTacticalAction}
          onResolveCombatReaction={(choice) => void resolveCombatReaction(choice)}
          onDeclareCombatRoundIdle={() => void declareCombatRoundIdle()}
          onTakeOverDevice={() => void takeOverDevice()}
          onChangeAbsentPolicy={(policy) => void changeAbsentPolicy(policy)}
          onRequestActionHints={() => void requestActionHints()}
          onApplyHint={applyHint}
          onNotificationsReviewed={markNotificationsRead}
          onOpenTab={navigatePlayerTab}
          onCreateCollaboration={createCollaboration}
          onRespondToCollaboration={respondToCollaboration}
          onCancelCollaboration={cancelCollaboration}
          onResumeSafetyPause={() => void resumeOwnSafetyPause()}
        />
      )}
      {tab === 'character' && <PlayerCharacter externalResult={lastSkillCheckResult} onResultConsumed={() => setLastSkillCheckResult(null)} />}
      {tab === 'inventory' && (
        <PlayerInventory
          onDescribeInNarration={(text) => {
            updateInputText(text);
            setTab('action');
          }}
          onOpenCampaignHome={() => setTab('home')}
        />
      )}
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
  inputMode: PlayerInputMode;
  draft: ActionDraftDTO | null;
  ephemeralPreview: ActionDraftDTO | null;
  receipt: ActionReceiptDTO | null;
  messages: PlayerChatMessage[];
  ruleQuestions: PlayerRuleQuestionDTO[];
  narrationDetails: NarrativeFeedItem[];
  recoveryText: string;
  pendingActions: TacticalAction[];
  pendingCombatReaction: SoloCombatReactionDTO | null;
  hasPendingInventoryTransfer: boolean;
  hasUnresolvedPartyQuestion: boolean;
  unreadPrivateResultCount: number;
  unreadPublicClueCount: number;
  collaborationContracts: CollaborationContractDTO[];
  collaborationParticipants: CollaborationParticipantDTO[];
  autoConfirmPending: boolean;
  safetyState: PlayerSafetyStateDTO;
  combatRound: PlayerCombatRoundDTO | null;
  absentPolicy: AbsentPolicy;
  speechRoutesToDialogue: boolean;
  deviceControl: boolean | null;
  character: CharacterSheet | null;
  onClaimJustificationChange: (value: string) => void;
  onClaimOpenChange: (value: boolean) => void;
  onClaimStatusChange: (value: string) => void;
  onClaimedItemNameChange: (value: string) => void;
  onInputTextChange: (value: string) => void;
  onToggleCombatTarget: (targetLabel: string) => void;
  onInputModeChange: (mode: PlayerInputMode) => void;
  onSubmitAction: (text?: string) => void;
  onConfirmAction: (selectedSkill?: string, compositeStepOrder?: string[]) => void;
  onUpdateCollaborationDependencies: (characterIds: string[]) => void;
  onDiscardAction: () => void;
  onCancelAction: () => void;
  onResolveCompositeChoice: (proceed: boolean) => void;
  onSubmitRetroClaim: () => void;
  onTacticalSelect: (action: TacticalAction) => void;
  onResolveCombatReaction: (choice: 'dodge' | 'counterattack') => void;
  onDeclareCombatRoundIdle: () => void;
  onTakeOverDevice: () => void;
  onChangeAbsentPolicy: (policy: AbsentPolicy) => void;
  onRequestActionHints: () => void;
  onApplyHint: (hint: string) => void;
  onNotificationsReviewed: () => void;
  onOpenTab: (tab: PlayerTabKey) => void;
  onCreateCollaboration: (sharedIntent: string, inviteeCharacterIds: string[]) => void;
  onRespondToCollaboration: (contractId: string, decision: 'accept' | 'decline') => void;
  onCancelCollaboration: (contractId: string) => void;
  onResumeSafetyPause: () => void;
}

function formatPlayerApiError(error: unknown): string {
  if (!(error instanceof PlayerApiError)) return '行动提交失败，请稍后重试。';
  if (error.detail && typeof error.detail === 'object' && 'code' in error.detail) {
    const code = String(error.detail.code);
    const messages: Record<string, string> = {
      action_already_submitted: '本回合已有一条有效行动，请先撤回或等待结算。',
      confirmation_required: '仍有风险项未确认。',
      skill_selection_required: '请先选择采用的技能。',
      skill_selection_invalid: '只能选择系统给出的技能候选。',
      draft_analysis_disabled: '本房间已关闭停顿分析，你仍可手动生成行动预览。',
      sync_required: '世界状态已变化，请同步后重新确认行动。',
      v2_action_draft_required: '此房间必须通过行动预览提交。',
      safety_paused: '匿名安全暂停正在生效，新的剧情行动暂不结算。',
    };
    return messages[code] || `行动处理失败：${code}`;
  }
  return `行动处理失败（${error.status}）`;
}

function combatHealthBar(segments: number | undefined): string {
  if (typeof segments !== 'number' || !Number.isInteger(segments) || segments < 0 || segments > 8) {
    return '';
  }
  return ` ${'█'.repeat(segments)}${'░'.repeat(8 - segments)}`;
}

const combatDistanceText: Record<'engaged' | 'near' | 'short' | 'medium' | 'long', string> = {
  engaged: '贴身',
  near: '近距离',
  short: '短距离',
  medium: '中距离',
  long: '远距离',
};

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
  inputMode,
  draft,
  ephemeralPreview,
  receipt,
  messages,
  ruleQuestions,
  narrationDetails,
  recoveryText,
  pendingActions,
  pendingCombatReaction,
  hasPendingInventoryTransfer,
  hasUnresolvedPartyQuestion,
  unreadPrivateResultCount,
  unreadPublicClueCount,
  collaborationContracts,
  collaborationParticipants,
  autoConfirmPending,
  safetyState,
  combatRound,
  absentPolicy,
  speechRoutesToDialogue,
  deviceControl,
  character,
  onClaimJustificationChange,
  onClaimOpenChange,
  onClaimStatusChange,
  onClaimedItemNameChange,
  onInputTextChange,
  onToggleCombatTarget,
  onInputModeChange,
  onSubmitAction,
  onConfirmAction,
  onUpdateCollaborationDependencies,
  onDiscardAction,
  onCancelAction,
  onResolveCompositeChoice,
  onSubmitRetroClaim,
  onTacticalSelect,
  onResolveCombatReaction,
  onDeclareCombatRoundIdle,
  onTakeOverDevice,
  onChangeAbsentPolicy,
  onRequestActionHints,
  onApplyHint,
  onNotificationsReviewed,
  onOpenTab,
  onCreateCollaboration,
  onRespondToCollaboration,
  onCancelCollaboration,
  onResumeSafetyPause,
}: ActionPanelProps) {
  const isIdle = canStartNewAction(draft, receipt);
  const combatTargetTags = getCombatTargetTags(inputText);
  const canEditCombatTargets = Boolean(
    combatRound?.phase === 'declaration'
    && !combatRound.declaration?.submitted
    && isIdle
    && deviceControl !== false,
  );
  const priorityInput = {
    hasPendingCombatReaction: Boolean(pendingCombatReaction),
    hasConfirmationDraft: Boolean(draft),
    hasPendingInventoryTransfer,
    hasUnresolvedPartyQuestion,
    unreadPrivateResultCount,
    unreadPublicClueCount,
    hasCollaborationInvite: Boolean(character?.character_id) && collaborationContracts.some((contract) => (
      contract.status === 'pending'
      && contract.initiatorCharacterId !== character?.character_id
      && contract.pendingCharacterIds.includes(character?.character_id || '')
    )),
    actionStatus,
    hasInputText: Boolean(inputText.trim()),
  };
  const currentPriority = getActionPanelCurrentPriority(priorityInput);
  const pendingTaskCount = getPlayerPendingTaskCount(priorityInput);
  const priorityTargetTab = currentPriority.targetTab;
  const narrativeItems: NarrativeFeedItem[] = [
    ...messages.map((message) => ({
      id: message.id,
      kind: message.sender === 'player' ? 'player' : message.sender === 'system' ? 'recovery' : 'kp_narration',
      text: message.text,
    } as NarrativeFeedItem)),
    ...narrationDetails,
  ];

  return (
    <div className="bh-player-play-grid">
      <section
        className="bh-panel bh-player-narrative-layout bh-player-narrative-layout--mobile-safe"
        data-safe-widths="360 390 430"
      >
      <section
        className={`bh-muted-box bh-player-current bh-player-current--${currentPriority.kind}`}
        aria-label="当前最重要的事"
      >
        <span className="bh-eyebrow">CURRENT PRIORITY</span>
        <h3>{currentPriority.title}</h3>
        <p>{currentPriority.detail}</p>
        {pendingTaskCount > 1 && <p className="bh-hint">另有 {pendingTaskCount - 1} 项待处理。</p>}
        {priorityTargetTab && (
          <button className="bh-button" type="button" onClick={() => {
            if (currentPriority.notificationKind) onNotificationsReviewed();
            onOpenTab(priorityTargetTab);
          }}>
            {priorityTargetTab === 'inventory'
              ? '查看待接收物品'
              : priorityTargetTab === 'logs'
                ? currentPriority.notificationKind === 'private_result' ? '查看私密结果' : '查看公共线索'
                : currentPriority.title === '回应协同行动邀请' ? '回应邀请' : '查看队伍待调查问题'}
          </button>
        )}
        {autoConfirmPending && (
          <div className="bh-muted-box" style={{ marginTop: 8 }}>
            <p>低风险行动将在 2 秒后进入结算。</p>
            <button className="bh-button" type="button" onClick={onDiscardAction}>撤回预览</button>
          </div>
        )}
      </section>
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

      {pendingActions.length > 0 && isIdle && (
        <div className="bh-panel" style={{ marginTop: 16 }}>
          <span className="bh-eyebrow">RULE DECISION</span>
          <p className="bh-hint">仅在规则明确要求你选择时显示；普通战斗请直接描述行动。</p>
          <TacticalButtons
            actions={pendingActions}
            disabled={false}
            onSelect={onTacticalSelect}
          />
        </div>
      )}

      {pendingCombatReaction && (
        <div className="bh-panel" style={{ marginTop: 16 }} role="alert">
          <span className="bh-eyebrow">INCOMING ATTACK</span>
          <h3 className="bh-panel-title">{pendingCombatReaction.attackerName || '敌人'}第 {pendingCombatReaction.roundNumber} 轮·{pendingCombatReaction.attackName}</h3>
          <p>先决定你的应对方式；结算前不会扣除生命。</p>
          <div className="bh-hint-list">
            <button className="bh-button" type="button" disabled={deviceControl === false} onClick={() => onResolveCombatReaction('dodge')}>闪避</button>
            <button className="bh-button bh-button--yellow" type="button" disabled={deviceControl === false} onClick={() => onResolveCombatReaction('counterattack')}>反击</button>
          </div>
        </div>
      )}

      {character && (
        <CollaborationContractPanel
          currentCharacterId={character.character_id}
          participants={collaborationParticipants}
          contracts={collaborationContracts}
          disabled={deviceControl === false}
          onCreate={onCreateCollaboration}
          onRespond={onRespondToCollaboration}
          onCancel={onCancelCollaboration}
        />
      )}

      {combatRound?.hasCombat && combatRound.declaration && (
        <section className="bh-muted-box" aria-label="战斗声明进度">
          <span className="bh-eyebrow">COMBAT ROUND</span>
          <h3>第 {combatRound.roundNumber} 轮 · {
            combatRound.phase === 'declaration' ? '声明行动' :
              combatRound.phase === 'resolution' ? '统一结算中' :
                combatRound.phase === 'summary' ? '轮末总结' : '等待处理'
          }</h3>
          <p>{combatRound.declaration.submitted
            ? '你的声明已提交；锁定前可撤回当前行动。'
            : '请用自然语言描述你本轮想做的事。'}</p>
          <p>{combatRound.declaration.submittedCount} / {combatRound.declaration.totalPlayers} 名调查员已完成声明。</p>
          {combatRound.phase === 'declaration' && !combatRound.declaration.submitted && (
            <div className="bh-action-row bh-action-row--responsive">
              <button
                className="bh-button"
                type="button"
                disabled={deviceControl === false}
                onClick={onDeclareCombatRoundIdle}
              >
                本轮暂不主动行动
              </button>
              <span className="bh-hint">正式声明：不攻击、不移动、不选目标、不消耗资源；仍可能受到外部影响。</span>
            </div>
          )}
          {combatRound.publicClusters?.map((cluster) => (
            <div key={cluster.publicTitle} className="bh-muted-box">
              <strong>{cluster.publicTitle}</strong>
              {cluster.completedPublicFacts.map((fact) => <p key={fact}>{fact}</p>)}
            </div>
          ))}
          {combatRound.observablePreparations && combatRound.observablePreparations.length > 0 && (
            <div className="bh-muted-box">
              <strong>可观察到的准备</strong>
              {combatRound.observablePreparations.map((preparation) => <p key={preparation}>{preparation}</p>)}
            </div>
          )}
          {combatRound.publicUnits && combatRound.publicUnits.length > 0 && (
            <div className="bh-muted-box" aria-label="当前可见单位">
              <strong>当前可见</strong>
              <p className="bh-hint">
                {canEditCombatTargets
                  ? '点击对象只加入本轮目标标签，不会替你选择动作或提交行动。'
                  : '本轮目标已锁定；当前仅显示可观察对象。'}
              </p>
              {combatRound.publicUnits.map((unit) => (
                <button
                  key={`${unit.kind}-${unit.label}`}
                  className="bh-button"
                  type="button"
                  aria-pressed={combatTargetTags.includes(unit.label)}
                  disabled={
                    !canEditCombatTargets
                    || (!combatTargetTags.includes(unit.label) && combatTargetTags.length >= 2)
                  }
                  onClick={() => onToggleCombatTarget(unit.label)}
                >
                  {unit.label} · {unit.condition}{combatHealthBar(unit.healthSegments)}
                  {unit.distanceBand ? ` · ${combatDistanceText[unit.distanceBand]}` : ''}
                  {unit.lastObservedAt ? ` · 最后发现：${unit.lastObservedAt}` : ''}
                </button>
              ))}
              {combatTargetTags.length > 0 && <p>本轮目标：{combatTargetTags.join('、')}</p>}
            </div>
          )}
        </section>
      )}

      {combatRound?.hasCombat && (
        <AbsentPolicyControl
          policy={absentPolicy}
          disabled={deviceControl === false}
          onChange={onChangeAbsentPolicy}
        />
      )}

      {safetyState.status === 'safety_paused' && (
        <section className="bh-muted-box" aria-live="assertive" aria-label="匿名安全暂停">
          <span className="bh-eyebrow">SAFETY PAUSE</span>
          <h3>引擎已匿名暂停</h3>
          <p>新的剧情行动不会结算。队伍可以继续发送场外信息或安全请求。</p>
          {safetyState.canResume ? (
            <button className="bh-button bh-button--yellow" type="button" onClick={onResumeSafetyPause}>
              恢复我触发的安全暂停
            </button>
          ) : (
            <p className="bh-hint">只有触发本次暂停的玩家可以恢复。</p>
          )}
        </section>
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
        inputMode={inputMode}
        phase={actionStatus}
        draft={draft}
        ephemeralPreview={ephemeralPreview}
        receipt={receipt}
        error={actionError}
        safetyPaused={safetyState.status === 'safety_paused'}
        speechRoutesToDialogue={speechRoutesToDialogue}
        collaborationParticipants={collaborationParticipants}
        currentCharacterId={character?.character_id}
        onInputChange={onInputTextChange}
        onInputModeChange={onInputModeChange}
        onAnalyze={() => onSubmitAction()}
        onConfirm={onConfirmAction}
        onUpdateCollaborationDependencies={onUpdateCollaborationDependencies}
        onDiscard={onDiscardAction}
        onCancelAction={onCancelAction}
        onResolveCompositeChoice={onResolveCompositeChoice}
      />

      {ruleQuestions.length > 0 && (
        <section className="bh-muted-box" aria-label="我的规则问题">
          <span className="bh-eyebrow">RULE QUESTIONS · 仅自己可见</span>
          <p>这些问题不会改变世界状态，也不会进入队伍或 KP 叙事。</p>
          <ul className="bh-hint-list">
            {ruleQuestions.slice(0, 5).map((question) => <li key={question.actionId}>{question.text}</li>)}
          </ul>
        </section>
      )}

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
    <PlayerContextRail
      character={character}
      currentPriority={currentPriority}
      recentItems={narrativeItems}
      onOpenTab={onOpenTab}
    />
  </div>
  );
}

function PlayerLogsPanel({ messages }: { messages: PlayerChatMessage[] }) {
  const [archive, setArchive] = useState<any[]>([]);
  const [archiveType, setArchiveType] = useState('all');
  type LogRow = PlayerChatMessage & { citations?: Array<{ label?: string; page?: number }> };

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

  const archiveRows: LogRow[] = archive.map((e: any) => ({
    id: String(e.sequence || Math.random()),
    sender: (e.is_public ? 'kp' : 'system') as 'kp' | 'system',
    text: e.data?.text || JSON.stringify(e.data || {}).slice(0, 80),
    timestamp: Date.now(),
    citations: Array.isArray(e.data?.citations) ? e.data.citations : [],
  }));

  const localRows: LogRow[] = archiveRows.length > 0 ? archiveRows : messages.length > 0 ? messages.slice(-8).reverse() : [
    { id: 'empty', sender: 'system' as const, text: '暂无历史记录。跑团开始后此处将显示事件日志。', timestamp: Date.now() },
  ];

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">INVESTIGATION LOGS</span>
      <h2 className="bh-panel-title">调查日志</h2>
      <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
        {['all', 'narrative', 'actions', 'clues', 'skill_checks', 'citations'].map((t) => (
          <button key={t} className={`bh-button${archiveType === t ? ' bh-button--yellow' : ''}`}
                  style={{ padding: '2px 8px', fontSize: 10 }}
                  onClick={() => setArchiveType(t)}>
            {t === 'all' ? '全部' : t === 'narrative' ? '剧情' : t === 'actions' ? '行动' : t === 'clues' ? '线索' : t === 'skill_checks' ? '检定' : '依据'}
          </button>
        ))}
      </div>
      <div className="bh-log-list">
        {localRows.slice(0, 12).map((msg) => (
          <div key={msg.id} className="bh-log-entry">
            <strong>{msg.sender.toUpperCase()}</strong>
            <p>{msg.text}</p>
            {(msg.citations || []).length > 0 && (
              <small>
                依据：{(msg.citations || []).map((citation, index) => (
                  <span key={`${citation.label || 'citation'}-${index}`}>
                    {index ? '；' : ''}{citation.label || '已校验依据'}{citation.page ? ` · 第 ${citation.page} 页` : ''}
                  </span>
                ))}
              </small>
            )}
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
    return <SemanticMapPanel projection={projection} imageUrl={mapImageUrl} />;
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

export function PlayerContextRail({
  character,
  currentPriority = null,
  recentItems = [],
  onOpenTab,
}: {
  character: CharacterSheet | null;
  currentPriority?: PlayerCurrentPriority | null;
  recentItems?: NarrativeFeedItem[];
  onOpenTab: (tab: PlayerTabKey) => void;
}) {
  const [drawerView, setDrawerView] = useState<'pending' | 'recent'>('pending');
  const recentVisibleItems = recentItems.slice(-5).reverse();
  const priorityActionLabel = currentPriority?.targetTab === 'inventory'
    ? '查看待接收物品'
    : currentPriority?.targetTab === 'home'
      ? '查看队伍待调查问题'
      : '回到当前';
  const sessionContext = (
    <>
      <span className="bh-eyebrow">SESSION CONTEXT</span>
      <h3>本局资料</h3>
      <div className="bh-context-vitals">
        <div><span>生命</span><strong>{character ? `${character.hp}/${character.max_hp}` : '--/--'}</strong></div>
        <div><span>理智</span><strong>{character ? `${character.san}/${character.max_san}` : '--/--'}</strong></div>
      </div>
      <p>地图只展示已知地点；移动、使用物品与检定仍通过自然语言行动确认。</p>
    </>
  );
  const pendingContent = (
    <section className="bh-context-drawer-section" aria-label="待处理">
      <span className="bh-eyebrow">待处理</span>
      {currentPriority ? (
        <>
          <strong>{currentPriority.title}</strong>
          <p>{currentPriority.detail}</p>
          {currentPriority.targetTab && (
            <button className="bh-button" type="button" onClick={() => onOpenTab(currentPriority.targetTab || 'action')}>
              {priorityActionLabel}
            </button>
          )}
        </>
      ) : <p>暂无待处理事项。</p>}
    </section>
  );
  const recentContent = (
    <section className="bh-context-drawer-section" aria-label="最近发生">
      <span className="bh-eyebrow">最近发生</span>
      {recentVisibleItems.length ? (
        <ol className="bh-context-recent-list">
          {recentVisibleItems.map((item) => <li key={item.id}>{item.text}</li>)}
        </ol>
      ) : <p>暂无新的可见事件。</p>}
    </section>
  );
  const contextActions = (
    <div className="bh-context-actions">
      <button className="bh-button" type="button" onClick={() => onOpenTab('map')}>打开地图</button>
      <button className="bh-button" type="button" onClick={() => onOpenTab('character')}>角色与技能</button>
      <button className="bh-button" type="button" onClick={() => onOpenTab('inventory')}>物品与线索</button>
      <button className="bh-button" type="button" onClick={() => onOpenTab('logs')}>调查日志</button>
    </div>
  );
  const desktopContent = (
    <>
      {sessionContext}
      {pendingContent}
      {recentContent}
      {contextActions}
    </>
  );
  const mobileContent = (
    <>
      <div className="bh-context-drawer-tabs" role="tablist" aria-label="本局资料摘要">
        <button
          className="bh-button"
          type="button"
          role="tab"
          aria-selected={drawerView === 'pending'}
          onClick={() => setDrawerView('pending')}
        >
          待处理
        </button>
        <button
          className="bh-button"
          type="button"
          role="tab"
          aria-selected={drawerView === 'recent'}
          onClick={() => setDrawerView('recent')}
        >
          最近发生
        </button>
      </div>
      <div role="tabpanel" hidden={drawerView !== 'pending'}>{pendingContent}</div>
      <div role="tabpanel" hidden={drawerView !== 'recent'}>{recentContent}</div>
      {sessionContext}
      {contextActions}
    </>
  );

  return (
    <aside className="bh-player-context-rail" aria-label="本局资料">
      <div className="bh-player-context-rail__desktop">{desktopContent}</div>
      <details className="bh-player-context-rail__mobile">
        <summary>本局资料</summary>
        <div className="bh-player-context-rail__drawer">{mobileContent}</div>
      </details>
    </aside>
  );
}
