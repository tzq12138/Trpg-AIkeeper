import { useState, useEffect, useRef, useCallback } from 'react';
import type { EngineEvent } from '../types';

interface PlayerStatus {
  character_id: string;
  player_name: string;
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
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${protocol}//${window.location.hostname}:3001/ws?room=${roomId}&role=host&lastSequence=${lastSeqRef.current}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          onEvent(data);
        } catch { /* ignore parse errors */ }
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
  const hpPercent = player.hp_max > 0 ? (player.hp / player.hp_max) * 100 : 0;
  const sanPercent = player.san_max > 0 ? (player.san / player.san_max) * 100 : 0;

  return (
    <div style={{
      background: 'rgba(0,0,0,0.6)',
      borderRadius: 8,
      padding: '12px 16px',
      minWidth: 160,
      backdropFilter: 'blur(4px)',
      border: '1px solid rgba(255,255,255,0.1)',
    }}>
      <div style={{ fontWeight: 'bold', fontSize: 14, marginBottom: 8 }}>{player.player_name}</div>
      <div style={{ marginBottom: 4 }}>
        <div style={{ fontSize: 11, color: '#aaa' }}>HP {player.hp}/{player.hp_max}</div>
        <div style={{ background: 'rgba(255,255,255,0.1)', borderRadius: 4, height: 6, marginTop: 2 }}>
          <div style={{
            background: hpPercent > 50 ? '#4caf50' : hpPercent > 25 ? '#ff9800' : '#f44336',
            width: `${hpPercent}%`,
            height: '100%',
            borderRadius: 4,
            transition: 'width 0.5s ease',
          }} />
        </div>
      </div>
      <div>
        <div style={{ fontSize: 11, color: '#aaa' }}>SAN {player.san}/{player.san_max}</div>
        <div style={{ background: 'rgba(255,255,255,0.1)', borderRadius: 4, height: 6, marginTop: 2 }}>
          <div style={{
            background: '#9c27b0',
            width: `${sanPercent}%`,
            height: '100%',
            borderRadius: 4,
            transition: 'width 0.5s ease',
          }} />
        </div>
      </div>
      {player.status_tags.length > 0 && (
        <div style={{ marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {player.status_tags.map((tag, i) => (
            <span key={i} style={{
              fontSize: 10,
              background: 'rgba(255,200,0,0.3)',
              borderRadius: 4,
              padding: '2px 6px',
            }}>{tag}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function GlobalHUD({ players, engineState }: { players: PlayerStatus[]; engineState: string }) {
  return (
    <div style={{
      position: 'absolute',
      top: 16,
      left: 16,
      right: 16,
      display: 'flex',
      gap: 12,
      zIndex: 10,
      flexWrap: 'wrap',
    }}>
      {players.map((p) => <PlayerCard key={p.character_id} player={p} />)}
      <div style={{
        marginLeft: 'auto',
        background: 'rgba(0,0,0,0.5)',
        borderRadius: 8,
        padding: '8px 16px',
        alignSelf: 'flex-start',
        fontSize: 12,
        color: engineState === 'thinking' ? '#ffd54f' : '#aaa',
      }}>
        {engineState === 'thinking' ? 'KP 思考中...' : engineState === 'busy' ? 'KP 忙碌...' : ''}
      </div>
    </div>
  );
}

function SceneBackground({ imageUrl }: { imageUrl: string | null }) {
  const [images, setImages] = useState<{ url: string; key: string }[]>([]);

  useEffect(() => {
    if (!imageUrl) return;
    setImages((prev) => {
      const next = [...prev, { url: imageUrl, key: imageUrl }];
      return next.slice(-2);
    });
  }, [imageUrl]);

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 0 }}>
      {images.map((img, i) => (
        <div
          key={img.key}
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: `url(${img.url})`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            opacity: i === images.length - 1 ? 1 : 0,
            transition: 'opacity 1.5s ease',
          }}
        />
      ))}
      {images.length === 0 && (
        <div style={{
          position: 'absolute',
          inset: 0,
          background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)',
        }} />
      )}
    </div>
  );
}

function TypewriterSubtitle({ messages }: { messages: ChatMessage[] }) {
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

  if (!displayed) return null;

  return (
    <div style={{
      position: 'absolute',
      bottom: 40,
      left: 40,
      right: 40,
      zIndex: 20,
      textAlign: 'center',
    }}>
      <div style={{
        display: 'inline-block',
        background: 'rgba(0,0,0,0.75)',
        borderRadius: 12,
        padding: '16px 32px',
        maxWidth: '80%',
        fontSize: 22,
        lineHeight: 1.6,
        color: '#eee',
        backdropFilter: 'blur(8px)',
        border: '1px solid rgba(255,255,255,0.1)',
      }}>
        {displayed}
        <span style={{ opacity: 0.5, animation: 'blink 1s infinite' }}>|</span>
      </div>
    </div>
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
    <div style={{
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      zIndex: 30,
      background: 'rgba(0,0,0,0.8)',
      borderRadius: 16,
      padding: '32px 48px',
      textAlign: 'center',
      border: '2px solid rgba(255,215,0,0.5)',
    }}>
      <div style={{ fontSize: 14, color: '#aaa', marginBottom: 8 }}>骰子检定</div>
      <div style={{ fontSize: 36, fontWeight: 'bold', color: '#ffd54f' }}>
        {String(rollEvent.dice || '1d20')}
      </div>
      {rollEvent.skill ? (
        <div style={{ fontSize: 16, color: '#ccc', marginTop: 8 }}>{String(rollEvent.skill)}</div>
      ) : null}
    </div>
  );
}

export default function HostStage({ roomId }: { roomId: string }) {
  const [hud, setHud] = useState<HUDData | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [rollEvent, setRollEvent] = useState<Record<string, unknown> | null>(null);
  const [atmosphere, setAtmosphere] = useState<Record<string, unknown> | null>(null);
  const [audioUnlocked, setAudioUnlocked] = useState(false);

  const handleEvent = useCallback((data: Record<string, unknown>) => {
    if (data.type === 'host_state_update' && data.hud) {
      setHud(data.hud as HUDData);
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
    }
  }, []);

  useHostWS(roomId, handleEvent);

  const handleDiceSettled = useCallback(() => {
    setRollEvent(null);
  }, []);

  const handleReset = async () => {
    await fetch(`/api/host/${roomId}/reset`, { method: 'POST' });
    setMessages([]);
    setRollEvent(null);
  };

  const handlePause = async () => {
    await fetch(`/api/host/${roomId}/pause`, { method: 'POST' });
  };

  const unlockAudio = () => {
    const ctx = new AudioContext();
    ctx.resume().then(() => setAudioUnlocked(true));
  };

  const visual = atmosphere?.visual as Record<string, unknown> | undefined;
  const filterStyle = visual?.filter ? `hue-rotate(${visual.filter === 'cold_blue' ? '180deg' : '0deg'}) saturate(1.5)` : undefined;
  const shakeClass = visual?.shake ? 'host-shake' : '';

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      overflow: 'hidden',
      color: 'white',
      fontFamily: 'sans-serif',
    }}>
      <style>{`
        @keyframes blink { 0%,50% { opacity: 1; } 51%,100% { opacity: 0; } }
        @keyframes shake {
          0%,100% { transform: translateX(0); }
          25% { transform: translateX(-4px); }
          75% { transform: translateX(4px); }
        }
        .host-shake { animation: shake 0.15s infinite; }
      `}</style>

      <div className={shakeClass} style={{ position: 'absolute', inset: 0, filter: filterStyle }}>
        <SceneBackground imageUrl={hud?.scene_image_url ?? null} />
        <GlobalHUD players={hud?.players ?? []} engineState={hud?.engine_state ?? 'idle'} />
        <TypewriterSubtitle messages={messages} />
        <DiceRollDisplay rollEvent={rollEvent} onSettled={handleDiceSettled} />
      </div>

      <div style={{
        position: 'absolute',
        bottom: 8,
        right: 16,
        zIndex: 50,
        display: 'flex',
        gap: 8,
      }}>
        {!audioUnlocked && (
          <button onClick={unlockAudio} style={{
            background: 'rgba(0,0,0,0.5)',
            border: '1px solid rgba(255,255,255,0.2)',
            borderRadius: 6,
            color: '#fff',
            padding: '6px 12px',
            cursor: 'pointer',
            fontSize: 12,
          }}>解锁音频</button>
        )}
        <button onClick={handlePause} style={{
          background: 'rgba(0,0,0,0.5)',
          border: '1px solid rgba(255,255,255,0.2)',
          borderRadius: 6,
          color: '#fff',
          padding: '6px 12px',
          cursor: 'pointer',
          fontSize: 12,
        }}>暂停/恢复</button>
        <button onClick={handleReset} style={{
          background: 'rgba(180,0,0,0.6)',
          border: '1px solid rgba(255,100,100,0.3)',
          borderRadius: 6,
          color: '#fff',
          padding: '6px 12px',
          cursor: 'pointer',
          fontSize: 12,
        }}>紧急重置</button>
      </div>
    </div>
  );
}
