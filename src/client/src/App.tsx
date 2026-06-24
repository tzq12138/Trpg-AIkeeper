import { useState, useEffect } from 'react';
import HostStage from './pages/HostStage';
import HostLobby from './pages/HostLobby';
import AdminDashboard from './pages/AdminDashboard';
import PlayerCharacter from './pages/PlayerCharacter';
import PlayerInventory from './pages/PlayerInventory';
import TacticalButtons from './components/TacticalButtons';
import { PlayerWS } from './ws';
import { apiFetch, authHeaders } from './api';
import type { EngineEvent, PlayerChatMessage, TacticalAction } from './types';

function getRoute(): { page: string; param: string } {
  const path = window.location.pathname;
  if (path === '/') return { page: 'home', param: '' };
  if (path === '/admin') return { page: 'admin', param: '' };
  if (path === '/host/create') return { page: 'host-create', param: '' };
  if (path.match(/^\/host\/[^/]+\/stage$/)) return { page: 'host-stage', param: path.split('/')[2] };
  if (path.startsWith('/host/')) return { page: 'host-lobby', param: path.split('/')[2] };
  if (path === '/player/join') return { page: 'player-join', param: '' };
  if (path.startsWith('/player/')) return { page: 'player-action', param: path.split('/')[2] };
  return { page: 'home', param: '' };
}

export default function App() {
  const [route, setRoute] = useState(getRoute());

  useEffect(() => {
    const handler = () => setRoute(getRoute());
    window.addEventListener('popstate', handler);
    return () => window.removeEventListener('popstate', handler);
  }, []);

  if (route.page === 'host-stage') {
    return <HostStage roomId={route.param} />;
  }
  if (route.page === 'admin') {
    return <AdminDashboard />;
  }

  return (
    <div style={{ maxWidth: 480, margin: '0 auto', padding: 16, fontFamily: 'sans-serif' }}>
      <h1>AI-Keeper</h1>
      {route.page === 'home' && <Home />}
      {route.page === 'host-create' && <HostCreate />}
      {route.page === 'host-lobby' && <HostLobby roomId={route.param} />}
      {route.page === 'player-join' && <PlayerJoin />}
      {route.page === 'player-action' && <PlayerAction roomId={route.param} />}
    </div>
  );
}

function Home() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <a href="/admin" style={{ padding: 16, border: '2px solid #3f51b5', borderRadius: 8, textAlign: 'center', color: '#8c9eff', fontWeight: 'bold' }}>
        管理后台
      </a>
      <a href="/host/create" style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8, textAlign: 'center' }}>
        创建房间 (Host)
      </a>
      <a href="/player/join" style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8, textAlign: 'center' }}>
        加入房间 (Player)
      </a>
    </div>
  );
}

function HostCreate() {
  const [roomId, setRoomId] = useState('');
  const [ownerToken, setOwnerToken] = useState('');

  const create = async () => {
    const res = await fetch('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    setRoomId(data.room_id);
    setOwnerToken(data.owner_token);
    localStorage.setItem('owner_token', data.owner_token);
  };

  if (roomId) {
    return (
      <div>
        <h2>房间已创建</h2>
        <p>房间号: <strong>{roomId}</strong></p>
        <a href={`/host/${roomId}`}>进入大厅</a>
      </div>
    );
  }

  return <button onClick={create} style={{ padding: 16, fontSize: 18 }}>创建房间</button>;
}

function PlayerJoin() {
  const [roomCode, setRoomCode] = useState('');
  const [error, setError] = useState('');

  const join = async () => {
    setError('');
    const res = await fetch(`/api/player/rooms/${roomCode}/join`, { method: 'POST' });
    if (!res.ok) {
      setError('房间不存在');
      return;
    }
    const data = await res.json();
    localStorage.setItem('player_token', data.player_token);
    window.location.href = `/player/${roomCode}`;
  };

  return (
    <div>
      <input
        placeholder="房间码"
        value={roomCode}
        onChange={(e) => setRoomCode(e.target.value)}
        style={{ padding: 12, fontSize: 16, width: '100%', marginBottom: 8 }}
      />
      <button onClick={join} style={{ padding: 12, fontSize: 16, width: '100%' }}>加入</button>
      {error && <p style={{ color: 'red' }}>{error}</p>}
    </div>
  );
}

type PlayerTab = 'action' | 'character' | 'inventory';

function PlayerAction({ roomId }: { roomId: string }) {
  const [tab, setTab] = useState<PlayerTab>('action');
  const [inputText, setInputText] = useState('');
  const [actionStatus, setActionStatus] = useState<string>('idle');
  const [messages, setMessages] = useState<PlayerChatMessage[]>([]);
  const [pendingActions, setPendingActions] = useState<TacticalAction[]>([]);
  const [claimOpen, setClaimOpen] = useState(false);
  const [claimedItemName, setClaimedItemName] = useState('');
  const [claimJustification, setClaimJustification] = useState('');
  const [claimStatus, setClaimStatus] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('player_token') || '';
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
      } else if (event.type === 's2c_public_observation') {
        const payload = event.payload as { text?: string };
        const text = payload.text;
        if (text) {
          setMessages((prev) => [...prev.slice(-49), {
            id: crypto.randomUUID(),
            sender: 'kp',
            text,
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
      }
    });
    ws.connect(token);
    return () => ws.disconnect();
  }, [roomId]);

  const submitAction = async () => {
    if (!inputText.trim() || actionStatus !== 'idle') return;
    setActionStatus('submitting');
    const actionId = crypto.randomUUID();
    try {
      const res = await fetch('/api/player/intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Room-Token': localStorage.getItem('player_token') || '' },
        body: JSON.stringify({
          action_id: actionId,
          intent_type: 'dialogue',
          declared_intent: inputText,
        }),
      });
      if (res.ok) {
        setActionStatus('resolving');
        setMessages((prev) => [...prev.slice(-49), {
          id: actionId, sender: 'player', text: inputText, timestamp: Date.now(),
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
    const justification = claimJustification.trim() || `我主张角色背景中应有${claimedItemName.trim()}`;
    try {
      const res = await fetch('/api/player/intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Room-Token': localStorage.getItem('player_token') || '' },
        body: JSON.stringify({
          action_id: actionId,
          intent_type: 'retroactive_item_claim',
          declared_intent: justification,
          params: {
            claimedItemName: claimedItemName.trim(),
            justificationText: justification,
          },
        }),
      });
      if (res.ok) {
        setClaimStatus('主张已提交');
        setMessages((prev) => [...prev.slice(-49), {
          id: actionId,
          sender: 'player',
          text: `主张物品：${claimedItemName.trim()}`,
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

  const tabs: { key: PlayerTab; label: string }[] = [
    { key: 'action', label: '行动' },
    { key: 'character', label: '角色卡' },
    { key: 'inventory', label: '背包' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '2px solid #333' }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              flex: 1, padding: '10px 0', border: 'none', background: 'transparent',
              color: tab === t.key ? '#8c9eff' : '#666', fontSize: 14, fontWeight: 'bold',
              borderBottom: tab === t.key ? '2px solid #3f51b5' : '2px solid transparent',
              cursor: 'pointer',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'action' && (
        <div>
          <div style={{
            maxHeight: 300, overflowY: 'auto', marginBottom: 12,
            background: 'rgba(255,255,255,0.03)', borderRadius: 8, padding: 10,
          }}>
            {messages.length === 0 && (
              <p style={{ color: '#555', fontSize: 13, textAlign: 'center' }}>等待KP指令...</p>
            )}
            {messages.map((msg) => (
              <div key={msg.id} style={{
                marginBottom: 10,
                textAlign: msg.sender === 'player' ? 'right' : 'left',
              }}>
                <div style={{
                  display: 'inline-block',
                  maxWidth: '85%',
                  padding: '8px 12px',
                  borderRadius: 10,
                  background: msg.sender === 'player' ? '#3f51b5' : 'rgba(255,255,255,0.08)',
                  color: '#ddd',
                  fontSize: 14,
                  textAlign: 'left',
                }}>
                  {msg.text}
                  {msg.actions && msg.actions.length > 0 && (
                    <TacticalButtons
                      actions={msg.actions}
                      disabled={actionStatus !== 'idle'}
                      onSubmitted={() => setActionStatus('resolving')}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>

          {pendingActions.length > 0 && actionStatus === 'idle' && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>快捷行动</div>
              <TacticalButtons
                actions={pendingActions}
                disabled={false}
                onSubmitted={() => setActionStatus('resolving')}
              />
            </div>
          )}

          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="描述你的行动..."
            disabled={actionStatus !== 'idle'}
            style={{ width: '100%', height: 60, padding: 8, fontSize: 14, borderRadius: 8, border: '1px solid #333', background: '#111', color: '#ddd', boxSizing: 'border-box' }}
          />
          <button
            onClick={submitAction}
            disabled={actionStatus !== 'idle'}
            style={{
              padding: 12, fontSize: 16, width: '100%', marginTop: 8,
              borderRadius: 8, border: 'none',
              background: actionStatus === 'idle' ? '#3f51b5' : '#333',
              color: actionStatus === 'idle' ? '#fff' : '#666',
              cursor: actionStatus === 'idle' ? 'pointer' : 'not-allowed',
            }}
          >
            {actionStatus === 'idle' ? '提交行动' : '等待结算...'}
          </button>
          <button
            onClick={() => {
              setClaimOpen((v) => !v);
              setClaimStatus('');
            }}
            disabled={actionStatus !== 'idle'}
            style={{
              padding: 10, fontSize: 14, width: '100%', marginTop: 8,
              borderRadius: 8, border: '1px solid #333',
              background: 'transparent',
              color: actionStatus === 'idle' ? '#8c9eff' : '#666',
              cursor: actionStatus === 'idle' ? 'pointer' : 'not-allowed',
            }}
          >
            主张物品
          </button>
          {claimOpen && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <input
                value={claimedItemName}
                onChange={(e) => setClaimedItemName(e.target.value)}
                placeholder="物品名，例如：医用塑胶手套"
                style={{ padding: 8, fontSize: 14, borderRadius: 8, border: '1px solid #333', background: '#111', color: '#ddd', boxSizing: 'border-box' }}
              />
              <input
                value={claimJustification}
                onChange={(e) => setClaimJustification(e.target.value)}
                placeholder="理由，例如：我是医生，随身带着"
                style={{ padding: 8, fontSize: 14, borderRadius: 8, border: '1px solid #333', background: '#111', color: '#ddd', boxSizing: 'border-box' }}
              />
              <button
                onClick={submitRetroClaim}
                disabled={!claimedItemName.trim() || actionStatus !== 'idle'}
                style={{
                  padding: 10, fontSize: 14, borderRadius: 8, border: 'none',
                  background: claimedItemName.trim() && actionStatus === 'idle' ? '#4caf50' : '#333',
                  color: claimedItemName.trim() && actionStatus === 'idle' ? '#fff' : '#666',
                  cursor: claimedItemName.trim() && actionStatus === 'idle' ? 'pointer' : 'not-allowed',
                }}
              >
                提交主张
              </button>
              {claimStatus && <div style={{ color: '#888', fontSize: 12 }}>{claimStatus}</div>}
            </div>
          )}
        </div>
      )}

      {tab === 'character' && <PlayerCharacter />}
      {tab === 'inventory' && <PlayerInventory />}
    </div>
  );
}
