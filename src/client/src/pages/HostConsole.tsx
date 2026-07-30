import { useCallback, useEffect, useRef, useState } from 'react';
import { BrutalProgress } from '../components/BauhausShell';
import HostSkeletonPanels from '../components/HostSkeletonPanels';
import { hostTabs, type HostTabKey } from '../navigation';
import { buildHostHeaders } from '../shared/host-auth';
import { getSlotValue } from '../shared/identity';
import { buildRoomWsUrl } from '../shared/ws-url';
import { normalizeHud as normalizeHostStageHud } from './hostStageModel';
import type { HostDirectorSnapshotDTO } from '../shared/types';
import RedactedCitationDisclosure from '../components/RedactedCitationDisclosure';

interface PlayerStatus {
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

interface HUDData {
  room_id: string;
  players: PlayerStatus[];
  scene_image_url: string | null;
  engine_state: string;
  queue_status: { normal: number; urgent: number };
}

interface ChatMessage {
  text?: string;
  speaker?: string;
  content?: string;
}

interface ActionException {
  action_id: string;
  character_id: string;
  intent_type: string;
  declared_intent: string;
  status: 'awaiting_host_exception';
  created_at: string;
}

interface ProjectionRecovery {
  action_id: string;
  character_id: string;
}

interface SafetyRequest {
  actionId: string;
  createdAt: string;
}

interface HostReviewPacket {
  review_request_id: string;
  action_id: string;
  character_id: string;
  original_intent: string;
  original_action_text: string;
  objection: string;
  intent_contract: {
    intentType: string;
    understandingSummary: string;
    risk: string;
    visibility: string;
    confirmationRequirements: string[];
    target: string | null;
    method: string | null;
    object: string | null;
    constraints: string[];
    resources: string[];
    conditions: string[];
    ambiguities: string[];
  };
  rule_plan: {
    ruleSetVersion: string;
    authoritativeInputs: Record<string, unknown>;
    modifiers: Record<string, unknown>;
    formula: string;
  };
  state_diff: {
    before: Record<string, unknown>;
    after: Record<string, unknown>;
  };
  citations: Array<{
    source?: string;
    page?: number;
    pageNumber?: number;
    location?: string;
  }>;
}

export interface HostPresentationState {
  transactionId: string | null;
  currentStepIndex: number;
  totalSteps: number;
  paused: boolean;
  completed: boolean;
  queuedTransactions: number;
  canSkipVisual: boolean;
}

export type HostPresentationCommand = 'play' | 'pause' | 'next' | 'skip-visual' | 'replay';

type ActionExceptionDecision = 'request_player_choice' | 'rejected';

function useHostWS(roomId: string, onEvent: (event: Record<string, unknown>) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const lastSeqRef = useRef(0);

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let delay = 1000;

    function connect() {
      const ownerToken = getSlotValue('owner_token') || '';
      const url = buildRoomWsUrl(window.location, {
        roomId,
        role: 'host',
        ownerToken,
        lastSequence: lastSeqRef.current,
      });
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          onEvent(data);
        } catch {
          // Ignore malformed events from transient reconnects.
        }
      };

      ws.onclose = () => {
        reconnectTimer = setTimeout(() => {
          delay = Math.min(delay * 1.5 + Math.random() * 500, 30000);
          connect();
        }, delay);
      };

      ws.onopen = () => {
        delay = 1000;
      };
    }

    connect();
    return () => {
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [roomId, onEvent]);
}

function PlayerCard({ player }: { player: PlayerStatus }) {
  const danger = player.hp <= Math.ceil(player.hp_max * 0.25) || player.san <= Math.ceil(player.san_max * 0.4);

  return (
    <article className={`bh-player-card ${danger ? 'bh-player-card--danger' : ''}`}>
      <h3>{player.player_name}</h3>
      <div className="bh-subtitle">{player.investigator_name || player.character_id}</div>
      <BrutalProgress label="HP" value={player.hp} max={player.hp_max} tone={danger ? 'red' : 'yellow'} />
      <BrutalProgress label="SAN" value={player.san} max={player.san_max} tone={player.san < player.san_max / 2 ? 'red' : 'yellow'} />
      {player.status_tags.length > 0 && (
        <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {player.status_tags.map((tag) => (
            <span className="bh-eyebrow" key={tag}>{tag}</span>
          ))}
        </div>
      )}
    </article>
  );
}

function TypewriterText({ messages }: { messages: ChatMessage[] }) {
  const [displayed, setDisplayed] = useState('');
  const targetRef = useRef('');
  const indexRef = useRef(0);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const last = messages[messages.length - 1];
    const text = last?.text || last?.content || '';
    if (!text || text === targetRef.current) return;
    targetRef.current = text;
    indexRef.current = 0;
    setDisplayed('');

    function tick() {
      if (indexRef.current < targetRef.current.length) {
        indexRef.current += 1;
        setDisplayed(targetRef.current.slice(0, indexRef.current));
        rafRef.current = requestAnimationFrame(tick);
      }
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [messages]);

  return (
    <p>
      {displayed || '投影待命。等待玩家行动、公共观察或裁决叙事进入舞台。'}
      <span className="bh-cursor">|</span>
    </p>
  );
}

function DiceRollDisplay({ rollEvent, onSettled }: { rollEvent: Record<string, unknown> | null; onSettled: () => void }) {
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!rollEvent) return;
    timerRef.current = setTimeout(onSettled, 15000);
    return () => clearTimeout(timerRef.current);
  }, [rollEvent, onSettled]);

  if (!rollEvent) return null;

  return (
    <div className="bh-dice-toast">
      <strong>骰子检定</strong>
      <span>{String(rollEvent.skill || rollEvent.dice || 'D100')}</span>
      {rollEvent.result ? <span>结果：{String(rollEvent.result)}</span> : null}
    </div>
  );
}

function NarrativeProjection({ imageUrl, messages, rollEvent, onDiceSettled }: {
  imageUrl: string | null;
  messages: ChatMessage[];
  rollEvent: Record<string, unknown> | null;
  onDiceSettled: () => void;
}) {
  return (
    <div className="bh-projection">
      {imageUrl && <div className="bh-projection-image" style={{ backgroundImage: `url(${imageUrl})` }} />}
      <DiceRollDisplay rollEvent={rollEvent} onSettled={onDiceSettled} />
      <div className="bh-projection-copy">
        <h2>场景投影</h2>
        <TypewriterText messages={messages} />
      </div>
    </div>
  );
}

export function HostDirectorConsole({
  snapshot,
  onPause,
  onTakeOverException,
}: {
  snapshot: HostDirectorSnapshotDTO;
  onPause: () => void;
  onTakeOverException: () => void;
}) {
  return (
    <section className="bh-panel bh-host-director-console" aria-label="只读导演台">
      <span className="bh-eyebrow">只读导演台</span>
      <h2 className="bh-panel-title">{snapshot.currentScene || '当前场景'}</h2>
      <div className="bh-action-row bh-action-row--responsive">
        <button className="bh-button" type="button" onClick={onPause}>暂停</button>
        <button className="bh-button bh-button--yellow" type="button" onClick={onTakeOverException}>异常接管</button>
      </div>
      <dl className="bh-action-preview__facts">
        <div><dt>阶段</dt><dd>{snapshot.stage}</dd></div>
        <div><dt>风险</dt><dd>{snapshot.risks.join('；') || '无'}</dd></div>
      </dl>
      <ReadOnlyList title="确认事实" items={snapshot.confirmedFacts} />
      <ReadOnlyList title="待触发条件" items={snapshot.pendingTriggers} />
      <ReadOnlyList title="异常队列" items={snapshot.exceptionQueue} />
      <RedactedCitationDisclosure citations={snapshot.aiEvidence} />
    </section>
  );
}

function ReadOnlyList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="bh-muted-box">
      <strong>{title}</strong>
      {items.length ? (
        <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
      ) : <p>暂无</p>}
    </div>
  );
}

export function HostExceptionQueue({
  items,
  resolvingActionId,
  onResolve,
}: {
  items: ActionException[];
  resolvingActionId: string | null;
  onResolve: (actionId: string, decision: ActionExceptionDecision, reason: string) => void;
}) {
  const [reasons, setReasons] = useState<Record<string, string>>({});

  if (items.length === 0) return null;

  return (
    <section className="bh-panel" aria-label="异常行动队列">
      <span className="bh-eyebrow">EXCEPTION ONLY</span>
      <h2 className="bh-panel-title">异常行动队列</h2>
      <p className="bh-subtitle">仅处理无法安全裁决的行动；普通行动仍由 AI 与规则引擎完成。</p>
      {items.map((item) => {
        const reason = reasons[item.action_id] || '';
        const isResolving = resolvingActionId === item.action_id;
        return (
          <article className="bh-muted-box" key={item.action_id}>
            <strong>{item.intent_type}</strong>
            <p>{item.declared_intent}</p>
            <textarea
              aria-label={`处理原因 ${item.action_id}`}
              placeholder="处理原因"
              value={reason}
              onChange={(event) => setReasons((previous) => ({
                ...previous,
                [item.action_id]: event.target.value,
              }))}
            />
            <div className="bh-action-row bh-action-row--responsive">
              <button
                className="bh-button bh-button--yellow"
                disabled={isResolving}
                onClick={() => onResolve(
                  item.action_id,
                  'request_player_choice',
                  reason.trim() || '请补充具体行动方式。',
                )}
                type="button"
              >
                请求玩家澄清
              </button>
              <button
                className="bh-button"
                disabled={isResolving}
                onClick={() => onResolve(
                  item.action_id,
                  'rejected',
                  reason.trim() || '当前行动无法安全裁决。',
                )}
                type="button"
              >
                拒绝行动
              </button>
            </div>
          </article>
        );
      })}
    </section>
  );
}

export function HostProjectionRecoveryQueue({
  items,
  replayingActionId,
  onReplay,
}: {
  items: ProjectionRecovery[];
  replayingActionId: string | null;
  onReplay: (actionId: string) => void;
}) {
  if (items.length === 0) return null;

  return (
    <section className="bh-panel" aria-label="投影恢复队列">
      <span className="bh-eyebrow">PROJECTION RECOVERY</span>
      <h2 className="bh-panel-title">投影恢复队列</h2>
      <p className="bh-subtitle">投影发送失败；重放只读取已保存的结果包，不会重新裁决或改写世界状态。</p>
      {items.map((item) => {
        const isReplaying = replayingActionId === item.action_id;
        return (
          <article className="bh-muted-box" key={item.action_id}>
            <strong>{item.action_id}</strong>
            <p>角色：{item.character_id}</p>
            <button
              className="bh-button bh-button--yellow"
              disabled={isReplaying}
              onClick={() => onReplay(item.action_id)}
              type="button"
            >
              {isReplaying ? '正在重放…' : '重放已保存投影'}
            </button>
          </article>
        );
      })}
    </section>
  );
}

function stateDiffLines(before: Record<string, unknown>, after: Record<string, unknown>) {
  const labels: Record<string, string> = { hp: 'HP', san: 'SAN', mp: 'MP', luck: '幸运' };
  return Object.entries(after)
    .filter(([key, value]) => before[key] !== value)
    .map(([key, value]) => `${labels[key] || key}: ${String(before[key] ?? '—')} → ${String(value)}`);
}

export function HostReviewPacketQueue({ items }: { items: HostReviewPacket[] }) {
  if (items.length === 0) return null;

  return (
    <section className="bh-panel" aria-label="行动复核">
      <span className="bh-eyebrow">REVIEW PACKET · HOST ONLY</span>
      <h2 className="bh-panel-title">行动复核</h2>
      <p className="bh-subtitle">对照原话、确认后的理解、规则依据、状态差异与来源；处理仍通过受控复核接口完成。</p>
      {items.map((item) => {
        const stateChanges = stateDiffLines(item.state_diff.before, item.state_diff.after);
        const inputs = item.rule_plan.authoritativeInputs;
        return (
          <article className="bh-muted-box" key={item.review_request_id}>
            <strong>行动 {item.action_id}</strong>
            <p><b>玩家原话：</b>{item.original_action_text || item.original_intent || '未记录'}</p>
            <p><b>异议：</b>{item.objection}</p>
            <dl className="bh-action-preview__facts">
              <div><dt>系统理解</dt><dd>{item.intent_contract.understandingSummary || '未记录'}</dd></div>
              <div><dt>风险 / 可见性</dt><dd>{item.intent_contract.risk || '未记录'} / {item.intent_contract.visibility || '未记录'}</dd></div>
              <div><dt>目标 / 方法</dt><dd>{item.intent_contract.target || '未记录'} / {item.intent_contract.method || '未记录'}</dd></div>
              {(item.intent_contract.conditions || []).length > 0 && <div><dt>条件</dt><dd>{item.intent_contract.conditions.join('；')}</dd></div>}
              {(item.intent_contract.ambiguities || []).length > 0 && <div><dt>歧义</dt><dd>{item.intent_contract.ambiguities.join('；')}</dd></div>}
              <div><dt>规则集</dt><dd>{item.rule_plan.ruleSetVersion}</dd></div>
              <div><dt>公式</dt><dd>{item.rule_plan.formula || '未记录'}</dd></div>
              <div><dt>权威输入</dt><dd>{String(inputs.skillName || '—')} {inputs.skillValue === undefined ? '' : String(inputs.skillValue)}</dd></div>
            </dl>
            <ReadOnlyList title="状态差异" items={stateChanges} />
            <ReadOnlyList
              title="来源"
              items={item.citations.map((citation) => [
                citation.source,
                (citation.page ?? citation.pageNumber) ? `p.${citation.page ?? citation.pageNumber}` : '',
                citation.location,
              ].filter(Boolean).join(' · '))}
            />
          </article>
        );
      })}
    </section>
  );
}

export function HostPresentationControls({
  state,
  pendingCommand,
  onCommand,
}: {
  state: HostPresentationState;
  pendingCommand: HostPresentationCommand | null;
  onCommand: (command: HostPresentationCommand) => void;
}) {
  if (!state.transactionId && state.queuedTransactions === 0) return null;

  return (
    <section className="bh-panel" aria-label="演出控制">
      <span className="bh-eyebrow">PRESENTATION</span>
      <h2 className="bh-panel-title">演出控制</h2>
      <p className="bh-subtitle">
        {state.transactionId
          ? `步骤 ${state.currentStepIndex} / ${state.totalSteps}`
          : `待播放事务 ${state.queuedTransactions} 个`}
        ；仅推进已保存的演出，不会重新裁决或改写世界状态。
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        <button
          className="bh-button"
          disabled={pendingCommand !== null || (Boolean(state.transactionId) && !state.paused)}
          onClick={() => onCommand('play')}
          type="button"
        >
          {pendingCommand === 'play' ? '启动中...' : state.transactionId ? '继续演出' : '开始演出'}
        </button>
        <button
          className="bh-button"
          disabled={pendingCommand !== null || state.paused || state.completed}
          onClick={() => onCommand('pause')}
          type="button"
        >
          {pendingCommand === 'pause' ? '暂停中...' : '暂停演出'}
        </button>
          <button
            className="bh-button bh-button--yellow"
            disabled={pendingCommand !== null || state.paused || state.completed}
            onClick={() => onCommand('next')}
            type="button"
          >
            {pendingCommand === 'next' ? '推进中...' : '下一步'}
          </button>
          <button
            className="bh-button"
            disabled={pendingCommand !== null || !state.canSkipVisual}
            onClick={() => onCommand('skip-visual')}
            type="button"
          >
            {pendingCommand === 'skip-visual' ? '跳过中...' : '跳过视觉步骤'}
          </button>
          <button
            className="bh-button"
            disabled={pendingCommand !== null || !state.transactionId || state.currentStepIndex === 0}
            onClick={() => onCommand('replay')}
            type="button"
          >
            {pendingCommand === 'replay' ? '重放中...' : '重放公开步骤'}
          </button>
      </div>
    </section>
  );
}

export function HostSafetyRequests({
  items,
  onRefresh,
  onExtend,
  onEndSession,
}: {
  items: SafetyRequest[];
  onRefresh: () => void;
  onExtend: () => void;
  onEndSession: () => void;
}) {
  const [confirmingEnd, setConfirmingEnd] = useState(false);
  if (items.length === 0) return null;

  return (
    <section className="bh-panel" aria-label="安全请求">
      <span className="bh-eyebrow">SAFETY · HOST ONLY</span>
      <h2 className="bh-panel-title">匿名安全暂停</h2>
      <p className="bh-subtitle">触发者和原文均不显示；只有触发者可以恢复，引擎会保持暂停。</p>
      {items.map((item) => (
        <article className="bh-muted-box" key={item.actionId}>
          <strong>安全暂停进行中</strong>
          <time>{item.createdAt}</time>
        </article>
      ))}
      <div className="bh-action-row">
        <button className="bh-button" type="button" onClick={onExtend}>延长暂停</button>
        {!confirmingEnd ? (
          <button className="bh-button" type="button" onClick={() => setConfirmingEnd(true)}>
            安全结束本次冒险
          </button>
        ) : (
          <>
            <button className="bh-button bh-button--danger" type="button" onClick={onEndSession}>
              确认安全结束
            </button>
            <button className="bh-button" type="button" onClick={() => setConfirmingEnd(false)}>
              取消
            </button>
          </>
        )}
        <button className="bh-button" type="button" onClick={onRefresh}>刷新</button>
      </div>
    </section>
  );
}

export default function HostConsole({
  roomId,
  initialTab = 'narrative',
}: {
  roomId: string;
  initialTab?: HostTabKey;
}) {
  const [activeTab, setActiveTab] = useState<HostTabKey>(initialTab);
  const [hud, setHud] = useState<HUDData | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [rollEvent, setRollEvent] = useState<Record<string, unknown> | null>(null);
  const [atmosphere, setAtmosphere] = useState<Record<string, unknown> | null>(null);
  const [audioUnlocked, setAudioUnlocked] = useState(false);
  const [activeEncounter, setActiveEncounter] = useState<any>(null);
  const [encounterSuggestion, setEncounterSuggestion] = useState<any>(null);
  const [mapRefresh, setMapRefresh] = useState(0);
  const [hudError, setHudError] = useState('');
  const [actionExceptions, setActionExceptions] = useState<ActionException[]>([]);
  const [actionReviews, setActionReviews] = useState<HostReviewPacket[]>([]);
  const [resolvingActionId, setResolvingActionId] = useState<string | null>(null);
  const [projectionRecoveries, setProjectionRecoveries] = useState<ProjectionRecovery[]>([]);
  const [replayingProjectionActionId, setReplayingProjectionActionId] = useState<string | null>(null);
  const [safetyRequests, setSafetyRequests] = useState<SafetyRequest[]>([]);
  const [safetyRefresh, setSafetyRefresh] = useState(0);
  const [presentation, setPresentation] = useState<HostPresentationState | null>(null);
  const [presentationCommand, setPresentationCommand] = useState<HostPresentationCommand | null>(null);

  const handleEvent = useCallback((data: Record<string, unknown>) => {
    if (data.type === 'host_state_update' && data.hud) {
      setHud(normalizeHostStageHud(data.hud as Record<string, unknown>));
    } else if (data.type === 'scene_update') {
      setHud((prev) => prev ? { ...prev, scene_image_url: data.image_url as string | null } : prev);
    } else if (data.type === 'chat_message') {
      setMessages((prev) => [...prev, data.message as ChatMessage]);
    } else if (data.type === 'atmosphere_update') {
      setAtmosphere(data.atmosphere as Record<string, unknown>);
    } else if (data.type === 's2c_reveal_transaction') {
      const payload = data.payload as { steps?: Array<{ kind?: string; payload?: Record<string, unknown> }>; summaryText?: string };
      const steps = payload.steps || [];
      const rollStep = steps.find((step) => step.kind === 'roll')?.payload;
      if (rollStep) {
        setRollEvent(rollStep);
      }
      const narrative = steps.find((step) => step.kind === 'narrative_text')?.payload?.text || payload.summaryText;
      if (narrative) {
        setMessages((prev) => [...prev, { text: String(narrative), speaker: 'KP' }]);
      }
    } else if (data.type === 's2c_public_observation') {
      const payload = data.payload as { text?: string };
      if (payload.text) {
        setMessages((prev) => [...prev, { text: payload.text, speaker: 'KP' }]);
      }
    } else if (data.type === 'encounter_suggested') {
      setEncounterSuggestion(data.payload);
    } else if (data.type === 'encounter_started') {
      setActiveEncounter(data.payload);
      setEncounterSuggestion(null);
      setActiveTab('combat');
    } else if (data.type === 'encounter_updated') {
      setActiveEncounter(data.payload);
    } else if (data.type === 'encounter_resolved') {
      setActiveEncounter(null);
    } else if (data.type === 'team_message') {
      const p = data.payload as Record<string, unknown>;
      if (p.text && typeof p.text === 'string') {
        setMessages((prev) => [...prev, {
          text: `💬 ${p.playerName || p.investigatorName || '玩家'}: ${p.text}`,
          speaker: 'TEAM',
        }]);
      }
    } else if (data.type === 'safety_request') {
      setSafetyRefresh((previous) => previous + 1);
    } else if (data.type === 's2c_action_review_requested' || data.type === 'action_review_requested') {
      void loadActionReviews();
    } else if (data.type === 'map_updated' || data.type === 'player_moved' || data.type === 'map_revealed') {
      setMapRefresh((prev) => prev + 1);
    }
  }, []);

  useHostWS(roomId, handleEvent);

  // Fetch HUD on mount — don't wait for WS to push first data
  useEffect(() => {
    const fetchHud = async () => {
      try {
        const ownerToken = getSlotValue('owner_token') || '';
        const accountToken = getSlotValue('account_token') || '';
        const headers = buildHostHeaders(ownerToken, accountToken);
        const res = await fetch(`/api/host/${roomId}/hud`, { headers });
        if (res.ok) {
          const data = await res.json();
          if (data.players) { setHud(normalizeHostStageHud(data)); setHudError(''); }
        } else {
          setHudError('无法加载玩家状态——请检查房主身份或刷新页面');
        }
      } catch { setHudError('网络错误——请确认后端已启动'); }
    };
    fetchHud();
  }, [roomId]);

  const loadActionExceptions = useCallback(async () => {
    try {
      const response = await fetch(`/api/host/${roomId}/action-exceptions`, {
        headers: buildHostHeaders(
          getSlotValue('owner_token') || '',
          getSlotValue('account_token') || '',
        ),
      });
      if (!response.ok) return;
      const payload = await response.json() as { items?: ActionException[] };
      setActionExceptions(payload.items || []);
    } catch {
      return;
    }
  }, [roomId]);

  useEffect(() => {
    void loadActionExceptions();
  }, [loadActionExceptions]);

  const loadActionReviews = useCallback(async () => {
    try {
      const response = await fetch(`/api/host/${roomId}/action-reviews`, {
        headers: buildHostHeaders(
          getSlotValue('owner_token') || '',
          getSlotValue('account_token') || '',
        ),
      });
      if (!response.ok) return;
      const payload = await response.json() as { items?: HostReviewPacket[] };
      setActionReviews(payload.items || []);
    } catch {
      return;
    }
  }, [roomId]);

  useEffect(() => {
    void loadActionReviews();
    const timer = window.setInterval(() => void loadActionReviews(), 5000);
    return () => window.clearInterval(timer);
  }, [loadActionReviews]);

  const loadProjectionRecoveries = useCallback(async () => {
    try {
      const response = await fetch(`/api/host/${roomId}/projection-replays`, {
        headers: buildHostHeaders(
          getSlotValue('owner_token') || '',
          getSlotValue('account_token') || '',
        ),
      });
      if (!response.ok) return;
      const payload = await response.json() as { items?: ProjectionRecovery[] };
      setProjectionRecoveries(payload.items || []);
    } catch {
      return;
    }
  }, [roomId]);

  useEffect(() => {
    void loadProjectionRecoveries();
    const timer = window.setInterval(() => void loadProjectionRecoveries(), 5000);
    return () => window.clearInterval(timer);
  }, [loadProjectionRecoveries]);

  const loadPresentation = useCallback(async () => {
    try {
      const response = await fetch(`/api/host/${roomId}/presentation`, {
        headers: buildHostHeaders(
          getSlotValue('owner_token') || '',
          getSlotValue('account_token') || '',
        ),
      });
      if (!response.ok) return;
      setPresentation(await response.json() as HostPresentationState);
    } catch {
      return;
    }
  }, [roomId]);

  useEffect(() => {
    void loadPresentation();
    const timer = window.setInterval(() => void loadPresentation(), 2000);
    return () => window.clearInterval(timer);
  }, [loadPresentation]);

  useEffect(() => {
    const loadSafetyRequests = async () => {
      try {
        const response = await fetch(`/api/host/${roomId}/safety-requests`, {
          headers: buildHostHeaders(
            getSlotValue('owner_token') || '',
            getSlotValue('account_token') || '',
          ),
        });
        if (!response.ok) return;
        const payload = await response.json() as { items?: SafetyRequest[] };
        setSafetyRequests(payload.items || []);
      } catch {
        return;
      }
    };
    void loadSafetyRequests();
  }, [roomId, safetyRefresh]);

  const handleDiceSettled = useCallback(() => {
    setRollEvent(null);
  }, []);

  const handlePause = async () => {
    await fetch(`/api/host/${roomId}/pause`, {
      method: 'POST',
      headers: { 'X-Owner-Token': getSlotValue('owner_token') || '' },
    });
  };

  const handleSafetyCommand = async (command: 'extend' | 'end-session') => {
    const response = await fetch(`/api/host/${roomId}/safety/${command}`, {
      method: 'POST',
      headers: buildHostHeaders(
        getSlotValue('owner_token') || '',
        getSlotValue('account_token') || '',
      ),
    });
    if (!response.ok) return;
    if (command === 'end-session') setSafetyRequests([]);
    setSafetyRefresh((previous) => previous + 1);
  };

  const handleResolveException = useCallback(async (
    actionId: string,
    decision: ActionExceptionDecision,
    reason: string,
  ) => {
    setResolvingActionId(actionId);
    try {
      const response = await fetch(`/api/host/${roomId}/action-exceptions/${actionId}/resolve`, {
        method: 'POST',
        headers: buildHostHeaders(
          getSlotValue('owner_token') || '',
          getSlotValue('account_token') || '',
          true,
        ),
        body: JSON.stringify({ decision, reason }),
      });
      if (!response.ok) {
        setHudError('异常行动处理失败——请刷新后重试。');
        return;
      }
      setActionExceptions((previous) => previous.filter((item) => item.action_id !== actionId));
    } catch {
      setHudError('网络错误——无法处理异常行动。');
    } finally {
      setResolvingActionId(null);
    }
  }, [roomId]);

  const handleReplayProjection = useCallback(async (actionId: string) => {
    setReplayingProjectionActionId(actionId);
    try {
      const response = await fetch(`/api/host/${roomId}/actions/${actionId}/replay-projection`, {
        method: 'POST',
        headers: buildHostHeaders(
          getSlotValue('owner_token') || '',
          getSlotValue('account_token') || '',
        ),
      });
      if (!response.ok) {
        setHudError('投影重放失败——请刷新后重试。');
        return;
      }
      await loadProjectionRecoveries();
    } catch {
      setHudError('网络错误——无法重放已保存投影。');
    } finally {
      setReplayingProjectionActionId(null);
    }
  }, [loadProjectionRecoveries, roomId]);

  const handlePresentationCommand = useCallback(async (command: HostPresentationCommand) => {
    setPresentationCommand(command);
    try {
      const response = await fetch(`/api/host/${roomId}/presentation/${command}`, {
        method: 'POST',
        headers: buildHostHeaders(
          getSlotValue('owner_token') || '',
          getSlotValue('account_token') || '',
        ),
      });
        if (!response.ok) {
          setHudError('演出控制未执行——请刷新后重试。');
          return;
        }
        if (command === 'replay') {
          await loadPresentation();
          return;
        }
        setPresentation(await response.json() as HostPresentationState);
    } catch {
      setHudError('网络错误——无法控制演出。');
    } finally {
      setPresentationCommand(null);
    }
    }, [loadPresentation, roomId]);

  const unlockAudio = () => {
    const ctx = new AudioContext();
    ctx.resume().then(() => setAudioUnlocked(true));
  };

  const visual = atmosphere?.visual as Record<string, unknown> | undefined;
  const filterStyle = visual?.filter ? `hue-rotate(${visual.filter === 'cold_blue' ? '180deg' : '0deg'}) saturate(1.5)` : undefined;
  const shakeClass = visual?.shake ? 'bh-host-shake' : '';
  const players = hud?.players ?? [];
  const directorSnapshot: HostDirectorSnapshotDTO = {
    currentScene: messages[messages.length - 1]?.text || messages[messages.length - 1]?.content || '当前场景',
    confirmedFacts: messages.slice(-3).map((message) => message.text || message.content || '').filter(Boolean),
    pendingTriggers: [`普通 ${hud?.queue_status?.normal ?? 0}`, `紧急 ${hud?.queue_status?.urgent ?? 0}`],
    aiEvidence: [],
    stage: hud?.engine_state === 'thinking' ? 'directing' : hud?.engine_state === 'busy' ? 'narrating' : 'completed',
    risks: encounterSuggestion ? ['遭遇建议待确认'] : [],
    exceptionQueue: actionExceptions.map((item) => item.declared_intent),
  };

  return (
    <div className="bh-host">
      {hudError && (
        <div style={{
          margin: 0, padding: '12px 20px',
          border: '3px solid var(--bh-yellow)', background: 'var(--bh-paper)',
          fontWeight: 700, fontSize: 14,
        }}>
          {hudError}
          <button style={{ marginLeft: 12, fontWeight: 900, cursor: 'pointer' }} onClick={() => setHudError('')}>✕</button>
        </div>
      )}
      <header className="bh-host-topbar">
        <div className="bh-host-brand">
          <strong className="bh-panel-title" style={{ margin: 0 }}>阿卡姆系统</strong>
          <span className="bh-room-code">房间代码：{roomId}</span>
        </div>
        <nav className="bh-host-tabs" aria-label="守密人页面">
          {hostTabs.map((tab) => (
            <button
              className="bh-tab"
              key={tab.key}
              type="button"
              aria-selected={activeTab === tab.key}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="bh-host-actions">
          {!audioUnlocked && (
            <button className="bh-button bh-button--yellow" onClick={unlockAudio} type="button">解锁音频</button>
          )}
          <button className="bh-button" onClick={handlePause} type="button">系统锁定</button>
        </div>
      </header>

      <div className={`bh-host-layout ${shakeClass}`} style={{ filter: filterStyle }}>
        <aside className="bh-host-rail">
          <div className="bh-keeper-card">
            <div className="bh-keeper-mark">KP</div>
            <h2 className="bh-panel-title">KEEPER_PRIME</h2>
            <p className="bh-subtitle">v.0.4.2_stable</p>
          </div>
          <div className="bh-tool-list">
            {hostTabs.map((tab) => (
              <button
                className="bh-tool"
                key={tab.key}
                type="button"
                aria-pressed={activeTab === tab.key}
                onClick={() => setActiveTab(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="bh-rail-footer">
            <span className="bh-eyebrow">QUEUE</span>
            <strong>普通 {hud?.queue_status?.normal ?? 0} / 紧急 {hud?.queue_status?.urgent ?? 0}</strong>
            <span>{hud?.engine_state === 'thinking' ? 'KP 思考中' : hud?.engine_state === 'busy' ? 'KP 忙碌中' : '系统待命'}</span>
          </div>
        </aside>

        <section className="bh-stage-panel">
          <div className="bh-stage-label">{hostTabs.find((tab) => tab.key === activeTab)?.eyebrow} // 第一阶段投影</div>
          {activeTab === 'narrative' ? (
            <NarrativeProjection
              imageUrl={hud?.scene_image_url ?? null}
              messages={messages}
              rollEvent={rollEvent}
              onDiceSettled={handleDiceSettled}
            />
          ) : (
            <div className="bh-projection" style={{ background: 'var(--bh-paper)' }}>
              <HostSkeletonPanels
                activeTab={activeTab}
                queueStatus={hud?.queue_status}
                messages={messages}
                roomId={roomId}
                activeEncounter={activeEncounter}
                encounterSuggestion={encounterSuggestion}
                onEncounterConfirmed={() => {}}
                mapRefresh={mapRefresh}
              />
            </div>
          )}
        </section>

        <aside className="bh-monitor">
          <div className="bh-monitor-label">调查员监控</div>
          <HostDirectorConsole
            snapshot={directorSnapshot}
            onPause={() => void handlePause()}
            onTakeOverException={() => setActiveTab('logs')}
          />
          <HostExceptionQueue
            items={actionExceptions}
            resolvingActionId={resolvingActionId}
            onResolve={(actionId, decision, reason) => void handleResolveException(actionId, decision, reason)}
          />
          <HostReviewPacketQueue items={actionReviews} />
          <HostProjectionRecoveryQueue
            items={projectionRecoveries}
            replayingActionId={replayingProjectionActionId}
            onReplay={(actionId) => void handleReplayProjection(actionId)}
          />
          {presentation && (
            <HostPresentationControls
              state={presentation}
              pendingCommand={presentationCommand}
              onCommand={(command) => void handlePresentationCommand(command)}
            />
          )}
          <HostSafetyRequests
            items={safetyRequests}
            onRefresh={() => setSafetyRefresh((previous) => previous + 1)}
            onExtend={() => void handleSafetyCommand('extend')}
            onEndSession={() => void handleSafetyCommand('end-session')}
          />
          <div className="bh-player-monitor-list">
            {players.length === 0 && (
              <article className="bh-player-card">
                <h3>等待调查员</h3>
                <p>玩家加入后，HP / SAN 会在这里实时显示。</p>
              </article>
            )}
            {players.map((player) => <PlayerCard key={player.character_id} player={player} />)}
          </div>
        </aside>
      </div>
    </div>
  );
}
