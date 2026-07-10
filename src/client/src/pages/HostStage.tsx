import { useCallback, useEffect, useRef, useState } from 'react';
import { BrutalProgress } from '../components/BauhausShell';
import HostSkeletonPanels from '../components/HostSkeletonPanels';
import { hostTabs, type HostTabKey } from '../navigation';
import { getSlotValue } from '../shared/identity';
import { buildRoomWsUrl } from '../shared/ws-url';
import { normalizeHud as normalizeHostStageHud } from './hostStageModel';

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

export default function HostStage({ roomId }: { roomId: string }) {
  const [activeTab, setActiveTab] = useState<HostTabKey>('narrative');
  const [hud, setHud] = useState<HUDData | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [rollEvent, setRollEvent] = useState<Record<string, unknown> | null>(null);
  const [atmosphere, setAtmosphere] = useState<Record<string, unknown> | null>(null);
  const [audioUnlocked, setAudioUnlocked] = useState(false);
  const [activeEncounter, setActiveEncounter] = useState<any>(null);
  const [encounterSuggestion, setEncounterSuggestion] = useState<any>(null);
  const [mapRefresh, setMapRefresh] = useState(0);
  const [hudError, setHudError] = useState('');

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
        const headers: Record<string, string> = { 'X-Owner-Token': ownerToken };
        if (accountToken) headers['Authorization'] = `Bearer ${accountToken}`;
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

  const handleDiceSettled = useCallback(() => {
    setRollEvent(null);
  }, []);

  const handleReset = async () => {
    await fetch(`/api/host/${roomId}/reset`, {
      method: 'POST',
      headers: { 'X-Owner-Token': getSlotValue('owner_token') || '' },
    });
    setMessages([]);
    setRollEvent(null);
  };

  const handlePause = async () => {
    await fetch(`/api/host/${roomId}/pause`, {
      method: 'POST',
      headers: { 'X-Owner-Token': getSlotValue('owner_token') || '' },
    });
  };

  const unlockAudio = () => {
    const ctx = new AudioContext();
    ctx.resume().then(() => setAudioUnlocked(true));
  };

  const visual = atmosphere?.visual as Record<string, unknown> | undefined;
  const filterStyle = visual?.filter ? `hue-rotate(${visual.filter === 'cold_blue' ? '180deg' : '0deg'}) saturate(1.5)` : undefined;
  const shakeClass = visual?.shake ? 'bh-host-shake' : '';
  const players = hud?.players ?? [];

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
          <button className="bh-button bh-button--red" onClick={handleReset} type="button">紧急重置</button>
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
