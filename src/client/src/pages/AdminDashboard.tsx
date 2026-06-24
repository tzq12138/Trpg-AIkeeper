import { useState, useEffect, useCallback } from 'react';

const owner = () => localStorage.getItem('owner_token') || '';
const player = () => localStorage.getItem('player_token') || '';

async function api(path: string, opts?: RequestInit) {
  const res = await fetch(path, { ...opts, headers: { 'Content-Type': 'application/json', ...opts?.headers } });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// ─── 主入口 ───

type AdminTab =
  | 'rooms' | 'scenarios' | 'players' | 'ai' | 'events' | 'campaign' | 'rag';

const TABS: { key: AdminTab; label: string }[] = [
  { key: 'rooms', label: '房间管理' },
  { key: 'scenarios', label: '剧本导入' },
  { key: 'players', label: '玩家管理' },
  { key: 'ai', label: 'AI KP' },
  { key: 'events', label: '事件日志' },
  { key: 'campaign', label: '战役档案' },
  { key: 'rag', label: 'RAG 知识库' },
];

export default function AdminDashboard({ roomId: initialRoom }: { roomId?: string }) {
  const [tab, setTab] = useState<AdminTab>('rooms');
  const [roomId, setRoomId] = useState(initialRoom || localStorage.getItem('admin_room_id') || '');

  const selectRoom = (id: string) => {
    setRoomId(id);
    localStorage.setItem('admin_room_id', id);
  };

  return (
    <div style={{ fontFamily: 'sans-serif', color: '#ddd', background: '#0a0a0a', minHeight: '100vh' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '12px 20px', background: '#111', borderBottom: '1px solid #222' }}>
        <h1 style={{ fontSize: 18, margin: 0, color: '#8c9eff' }}>AI-Keeper 管理后台</h1>
        {roomId && <span style={{ marginLeft: 16, fontSize: 13, color: '#666' }}>房间: {roomId}</span>}
        <a href="/" style={{ marginLeft: 'auto', color: '#666', fontSize: 13 }}>返回首页</a>
      </div>

      <div style={{ display: 'flex', borderBottom: '1px solid #222', padding: '0 16px' }}>
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            padding: '10px 16px', border: 'none', background: 'transparent',
            color: tab === t.key ? '#8c9eff' : '#666', fontSize: 13, fontWeight: 'bold',
            borderBottom: tab === t.key ? '2px solid #3f51b5' : '2px solid transparent',
            cursor: 'pointer',
          }}>{t.label}</button>
        ))}
      </div>

      <div style={{ padding: 20, maxWidth: 900 }}>
        {tab === 'rooms' && <RoomsPanel roomId={roomId} selectRoom={selectRoom} />}
        {tab === 'scenarios' && <ScenariosPanel selectRoom={selectRoom} />}
        {tab === 'players' && <PlayersPanel roomId={roomId} />}
        {tab === 'ai' && <AIPanel roomId={roomId} />}
        {tab === 'events' && <EventsPanel roomId={roomId} />}
        {tab === 'campaign' && <CampaignPanel roomId={roomId} />}
        {tab === 'rag' && <RAGPanel />}
      </div>
    </div>
  );
}

// ─── 房间管理 ───

function RoomsPanel({ roomId, selectRoom }: { roomId: string; selectRoom: (id: string) => void }) {
  const [room, setRoom] = useState<any>(null);
  const [hud, setHud] = useState<any>(null);
  const [log, setLog] = useState<string[]>([]);

  const addLog = (msg: string) => setLog(p => [...p.slice(-29), `${new Date().toLocaleTimeString()} ${msg}`]);

  const loadRoom = useCallback(async () => {
    if (!roomId) return;
    try {
      const r = await api(`/api/rooms/${roomId}`);
      setRoom(r);
    } catch { setRoom(null); }
  }, [roomId]);

  const loadHud = useCallback(async () => {
    if (!roomId) return;
    try {
      const h = await api(`/api/host/${roomId}/hud`);
      setHud(h);
    } catch { setHud(null); }
  }, [roomId]);

  useEffect(() => { loadRoom(); loadHud(); }, [loadRoom, loadHud]);

  const createRoom = async () => {
    const r = await api('/api/rooms', { method: 'POST', body: '{}' });
    localStorage.setItem('owner_token', r.owner_token);
    selectRoom(r.room_id);
    addLog(`创建房间 ${r.room_id}`);
  };

  const startGame = async () => {
    await api(`/api/rooms/${roomId}/start`, { method: 'POST', headers: { 'X-Owner-Token': owner() } });
    addLog('游戏已开始');
    loadRoom();
  };

  const pause = async () => {
    await api(`/api/host/${roomId}/pause`, { method: 'POST', headers: { 'X-Owner-Token': owner() } });
    addLog('已暂停');
  };

  const retryTurn = async () => {
    await api(`/api/host/${roomId}/retry-turn`, { method: 'POST', headers: { 'X-Owner-Token': owner() } });
    addLog('已重试回合');
  };

  const reset = async () => {
    if (!confirm('确定紧急重置？')) return;
    await api(`/api/host/${roomId}/reset`, { method: 'POST', headers: { 'X-Owner-Token': owner() } });
    addLog('已紧急重置');
    loadHud();
  };

  return (
    <div>
      <h2 style={{ color: '#8c9eff', fontSize: 16 }}>房间管理</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <button onClick={createRoom} style={btnStyle}>创建新房间</button>
        <input placeholder="输入房间码" value={roomId} onChange={e => selectRoom(e.target.value)}
          style={{ ...inputStyle, width: 160 }} />
        <button onClick={() => { loadRoom(); loadHud(); }} style={btnStyle}>刷新</button>
      </div>

      {room && (
        <div style={cardStyle}>
          <div><b>房间 ID:</b> {room.room_id}</div>
          <div><b>状态:</b> <span style={{ color: room.status === 'active' ? '#4caf50' : '#ff9800' }}>{room.status}</span></div>
          <div><b>Owner Token:</b> <code style={{ fontSize: 11 }}>{room.owner_token?.slice(0, 12)}...</code></div>
          <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {room.status === 'lobby' && <button onClick={startGame} style={btnGreen}>开始游戏</button>}
            <button onClick={pause} style={btnYellow}>暂停 AI</button>
            <button onClick={retryTurn} style={btnYellow}>重试回合</button>
            <button onClick={reset} style={btnRed}>紧急重置</button>
          </div>
        </div>
      )}

      {hud && (
        <div style={cardStyle}>
          <h3 style={{ fontSize: 14, color: '#8c9eff' }}>HUD 状态</h3>
          <pre style={{ fontSize: 12, color: '#aaa', whiteSpace: 'pre-wrap' }}>{JSON.stringify(hud, null, 2)}</pre>
        </div>
      )}

      <div style={cardStyle}>
        <h3 style={{ fontSize: 14, color: '#8c9eff' }}>操作日志</h3>
        {log.map((l, i) => <div key={i} style={{ fontSize: 12, color: '#888' }}>{l}</div>)}
      </div>
    </div>
  );
}

// ─── 剧本导入 ───

function ScenariosPanel({ selectRoom }: { selectRoom: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [importResult, setImportResult] = useState<any>(null);
  const [qualityReport, setQualityReport] = useState<any>(null);
  const [scenarioId, setScenarioId] = useState('');
  const [uploading, setUploading] = useState(false);

  const uploadPdf = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('/api/scenarios/import-pdf', { method: 'POST', body: fd });
      const data = await res.json();
      setImportResult(data);
      setScenarioId(data.scenario_id);
    } catch (e: any) { setImportResult({ error: e.message }); }
    setUploading(false);
  };

  const loadQuality = async () => {
    if (!scenarioId) return;
    try {
      const r = await api(`/api/scenarios/${scenarioId}/quality-report`);
      setQualityReport(r);
    } catch { setQualityReport(null); }
  };

  const createRoomFromScenario = async () => {
    if (!scenarioId) return;
    const r = await api(`/api/scenarios/${scenarioId}/create-room`, { method: 'POST' });
    localStorage.setItem('owner_token', r.owner_token);
    selectRoom(r.room_id);
  };

  return (
    <div>
      <h2 style={{ color: '#8c9eff', fontSize: 16 }}>剧本导入</h2>

      <div style={cardStyle}>
        <h3 style={{ fontSize: 14 }}>上传 PDF</h3>
        <input type="file" accept=".pdf" onChange={e => setFile(e.target.files?.[0] || null)} style={{ color: '#aaa', marginBottom: 8 }} />
        <button onClick={uploadPdf} disabled={!file || uploading} style={btnStyle}>
          {uploading ? '导入中...' : '开始导入'}
        </button>
        {importResult && (
          <pre style={{ fontSize: 12, color: '#aaa', marginTop: 8 }}>{JSON.stringify(importResult, null, 2)}</pre>
        )}
      </div>

      {scenarioId && (
        <div style={cardStyle}>
          <h3 style={{ fontSize: 14 }}>质量报告</h3>
          <p style={{ fontSize: 12, color: '#888' }}>剧本 ID: {scenarioId}</p>
          <button onClick={loadQuality} style={btnStyle}>查看质量报告</button>
          {qualityReport && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 'bold', color: levelColor(qualityReport.level) }}>
                等级: {qualityReport.level} ({Math.round(qualityReport.completeness * 100)}% 完整)
              </div>
              {qualityReport.issues?.map((i: any, idx: number) => (
                <div key={idx} style={{ fontSize: 12, color: '#aaa', marginTop: 4 }}>
                  [{i.severity}] {i.category}: {i.message}
                </div>
              ))}
            </div>
          )}
          <button onClick={createRoomFromScenario} style={{ ...btnGreen, marginTop: 12 }}>一键开局</button>
        </div>
      )}
    </div>
  );
}

function levelColor(level: string) {
  if (level === 'ready') return '#4caf50';
  if (level === 'warning') return '#ff9800';
  if (level === 'highRisk') return '#f44336';
  return '#666';
}

// ─── 玩家管理 ───

function PlayersPanel({ roomId }: { roomId: string }) {
  const [players, setPlayers] = useState<any[]>([]);
  const [clues, setClues] = useState<any[]>([]);
  const [objectives, setObjectives] = useState<any[]>([]);
  const [archive, setArchive] = useState<any[]>([]);
  const [skillCheck, setSkillCheck] = useState({ skill: 'library_use', difficulty: 'regular' });
  const [skillResult, setSkillResult] = useState<any>(null);

  const loadPlayers = useCallback(async () => {
    if (!roomId) return;
    try {
      const h = await api(`/api/host/${roomId}/hud`);
      setPlayers(h.players || []);
    } catch {}
  }, [roomId]);

  useEffect(() => { loadPlayers(); }, [loadPlayers]);

  const loadClues = async () => {
    try { setClues(await api('/api/player/clues', { headers: { 'X-Room-Token': player() } })); } catch {}
  };

  const loadObjectives = async () => {
    try { setObjectives(await api('/api/player/objectives', { headers: { 'X-Room-Token': player() } })); } catch {}
  };

  const loadArchive = async () => {
    try { setArchive(await api('/api/player/archive', { headers: { 'X-Room-Token': player() } })); } catch {}
  };

  const doSkillCheck = async () => {
    try {
      const r = await api('/api/player/skill-check', {
        method: 'POST',
        headers: { 'X-Room-Token': player() },
        body: JSON.stringify({ skill_name: skillCheck.skill, difficulty: skillCheck.difficulty }),
      });
      setSkillResult(r);
    } catch {}
  };

  return (
    <div>
      <h2 style={{ color: '#8c9eff', fontSize: 16 }}>玩家管理</h2>

      <div style={cardStyle}>
        <h3 style={{ fontSize: 14 }}>当前玩家 ({players.length})</h3>
        {players.length === 0 && <p style={muted}>暂无玩家</p>}
        {players.map((p: any, i: number) => (
          <div key={i} style={{ padding: 8, borderBottom: '1px solid #222', display: 'flex', gap: 16, fontSize: 13 }}>
            <span style={{ color: '#ddd' }}>{p.name || p.playerName || `玩家${i + 1}`}</span>
            <span style={{ color: '#888' }}>HP:{p.hp ?? '?'} SAN:{p.san ?? '?'}</span>
            <span style={{ color: p.isReady ? '#4caf50' : '#ff9800' }}>{p.isReady ? '✓ Ready' : '未准备'}</span>
          </div>
        ))}
      </div>

      <div style={cardStyle}>
        <h3 style={{ fontSize: 14 }}>技能检定</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <select value={skillCheck.skill} onChange={e => setSkillCheck(s => ({ ...s, skill: e.target.value }))} style={inputStyle}>
            {['library_use', 'listen', 'spot_hidden', 'persuade', 'fast_talk', 'locksmith',
              'first_aid', 'medicine', 'psychology', 'stealth', 'dodge', 'fight_brawl'].map(s =>
              <option key={s} value={s}>{s}</option>
            )}
          </select>
          <select value={skillCheck.difficulty} onChange={e => setSkillCheck(s => ({ ...s, difficulty: e.target.value }))} style={inputStyle}>
            <option value="regular">普通</option>
            <option value="hard">困难</option>
            <option value="extreme">极限</option>
          </select>
          <button onClick={doSkillCheck} style={btnStyle}>掷骰</button>
        </div>
        {skillResult && (
          <pre style={{ fontSize: 12, color: '#aaa' }}>{JSON.stringify(skillResult, null, 2)}</pre>
        )}
      </div>

      <div style={cardStyle}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <button onClick={loadClues} style={btnStyle}>加载线索</button>
          <button onClick={loadObjectives} style={btnStyle}>加载目标</button>
          <button onClick={loadArchive} style={btnStyle}>加载档案</button>
        </div>
        {clues.length > 0 && (
          <div>
            <h3 style={{ fontSize: 14 }}>线索 ({clues.length})</h3>
            {clues.map((c: any, i: number) => (
              <div key={i} style={{ fontSize: 12, color: '#aaa', padding: 4, borderBottom: '1px solid #1a1a1a' }}>
                {c.is_private ? '🔒' : '🌐'} {c.text} <span style={{ color: '#555' }}>({c.source})</span>
              </div>
            ))}
          </div>
        )}
        {objectives.length > 0 && (
          <div>
            <h3 style={{ fontSize: 14 }}>目标 ({objectives.length})</h3>
            {objectives.map((o: any, i: number) => (
              <div key={i} style={{ fontSize: 12, color: '#aaa', padding: 4 }}>
                [{o.type}] {o.text} — <span style={{ color: o.status === 'active' ? '#4caf50' : '#666' }}>{o.status}</span>
              </div>
            ))}
          </div>
        )}
        {archive.length > 0 && (
          <div>
            <h3 style={{ fontSize: 14 }}>档案 ({archive.length})</h3>
            {archive.slice(0, 20).map((e: any, i: number) => (
              <div key={i} style={{ fontSize: 11, color: '#666', padding: 2 }}>
                #{e.sequence} [{e.event_type}] {JSON.stringify(e.payload).slice(0, 80)}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── AI KP ───

function AIPanel({ roomId }: { roomId: string }) {
  const [status, setStatus] = useState<any>(null);
  const [triggerResult, setTriggerResult] = useState<any>(null);

  const loadStatus = async () => {
    if (!roomId) return;
    try { setStatus(await api(`/api/rooms/${roomId}/ai-status`)); } catch {}
  };

  const triggerTurn = async () => {
    try {
      const r = await api(`/api/rooms/${roomId}/ai-turn`, { method: 'POST' });
      setTriggerResult(r);
    } catch {}
  };

  useEffect(() => { loadStatus(); }, [loadStatus]);

  return (
    <div>
      <h2 style={{ color: '#8c9eff', fontSize: 16 }}>AI KP 控制</h2>
      <div style={cardStyle}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <button onClick={loadStatus} style={btnStyle}>刷新状态</button>
          <button onClick={triggerTurn} style={btnGreen}>手动触发 AI 回合</button>
        </div>
        {status && <pre style={{ fontSize: 12, color: '#aaa' }}>{JSON.stringify(status, null, 2)}</pre>}
        {triggerResult && (
          <div style={{ marginTop: 12 }}>
            <h3 style={{ fontSize: 14, color: '#8c9eff' }}>触发结果</h3>
            <pre style={{ fontSize: 12, color: '#aaa' }}>{JSON.stringify(triggerResult, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 事件日志 ───

function EventsPanel({ roomId }: { roomId: string }) {
  const [events, setEvents] = useState<any[]>([]);
  const [replay, setReplay] = useState<any[]>([]);
  const [checkpoints, setCheckpoints] = useState<any[]>([]);

  const loadEvents = async () => {
    if (!roomId) return;
    try { setEvents(await api(`/api/rooms/${roomId}/events?limit=50`)); } catch {}
  };

  const loadReplay = async () => {
    if (!roomId) return;
    try { setReplay(await api(`/api/rooms/${roomId}/events/public?limit=50`)); } catch {}
  };

  const loadCheckpoints = async () => {
    if (!roomId) return;
    try { setCheckpoints(await api(`/api/rooms/${roomId}/checkpoints`)); } catch {}
  };

  const createCheckpoint = async () => {
    await api(`/api/rooms/${roomId}/checkpoint`, { method: 'POST' });
    loadCheckpoints();
  };

  useEffect(() => { loadEvents(); loadCheckpoints(); }, [loadEvents, loadCheckpoints]);

  return (
    <div>
      <h2 style={{ color: '#8c9eff', fontSize: 16 }}>事件日志</h2>
      <div style={cardStyle}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <button onClick={loadEvents} style={btnStyle}>全部事件</button>
          <button onClick={loadReplay} style={btnStyle}>公共回放</button>
          <button onClick={loadCheckpoints} style={btnStyle}>检查点列表</button>
          <button onClick={createCheckpoint} style={btnGreen}>创建检查点</button>
        </div>

        {events.length > 0 && (
          <div>
            <h3 style={{ fontSize: 14 }}>事件 ({events.length})</h3>
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              {events.map((e: any, i: number) => (
                <div key={i} style={{ fontSize: 11, color: '#888', padding: 3, borderBottom: '1px solid #1a1a1a', fontFamily: 'monospace' }}>
                  <span style={{ color: '#555' }}>#{e.sequence}</span>{' '}
                  <span style={{ color: '#8c9eff' }}>{e.event_type}</span>{' '}
                  <span style={{ color: '#666' }}>[{e.audience}]</span>{' '}
                  {JSON.stringify(e.payload).slice(0, 100)}
                </div>
              ))}
            </div>
          </div>
        )}

        {checkpoints.length > 0 && (
          <div>
            <h3 style={{ fontSize: 14 }}>检查点 ({checkpoints.length})</h3>
            {checkpoints.map((c: any, i: number) => (
              <div key={i} style={{ fontSize: 12, color: '#aaa', padding: 4 }}>
                {c.checkpoint_id} — {c.created_at}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 战役档案 ───

function CampaignPanel({ roomId }: { roomId: string }) {
  const [campaign, setCampaign] = useState<any>(null);

  const loadCampaign = async () => {
    if (!roomId) return;
    try { setCampaign(await api(`/api/rooms/${roomId}/campaign`)); } catch {}
  };

  const endCampaign = async () => {
    if (!confirm('确定结束战役？')) return;
    try {
      const r = await api(`/api/rooms/${roomId}/end`, { method: 'POST' });
      setCampaign(r);
    } catch {}
  };

  return (
    <div>
      <h2 style={{ color: '#8c9eff', fontSize: 16 }}>战役档案</h2>
      <div style={cardStyle}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <button onClick={loadCampaign} style={btnStyle}>查看战役摘要</button>
          <button onClick={endCampaign} style={btnRed}>结束战役</button>
        </div>
        {campaign && <pre style={{ fontSize: 12, color: '#aaa', whiteSpace: 'pre-wrap' }}>{JSON.stringify(campaign, null, 2)}</pre>}
      </div>
    </div>
  );
}

// ─── RAG 知识库 ───

function RAGPanel() {
  const [stats, setStats] = useState<any>(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);

  const loadStats = async () => {
    try { setStats(await api('/api/rag/stats')); } catch {}
  };

  const doSearch = async () => {
    if (!query.trim()) return;
    try {
      const r = await api('/api/rag/search', {
        method: 'POST',
        body: JSON.stringify({ query, top_k: 5 }),
      });
      setResults(r);
    } catch {}
  };

  return (
    <div>
      <h2 style={{ color: '#8c9eff', fontSize: 16 }}>RAG 知识库</h2>
      <div style={cardStyle}>
        <button onClick={loadStats} style={btnStyle}>加载统计</button>
        {stats && <pre style={{ fontSize: 12, color: '#aaa', marginTop: 8 }}>{JSON.stringify(stats, null, 2)}</pre>}
      </div>
      <div style={cardStyle}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="语义搜索..." style={{ ...inputStyle, flex: 1 }}
            onKeyDown={e => e.key === 'Enter' && doSearch()} />
          <button onClick={doSearch} style={btnStyle}>搜索</button>
        </div>
        {results.map((r: any, i: number) => (
          <div key={i} style={{ fontSize: 12, padding: 8, borderBottom: '1px solid #222' }}>
            <div style={{ color: '#8c9eff' }}>[{r.source_type}] sim: {r.similarity?.toFixed(3)}</div>
            <div style={{ color: '#aaa' }}>{r.content?.slice(0, 200)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 样式 ───

const btnStyle: React.CSSProperties = {
  padding: '8px 16px', border: 'none', borderRadius: 6, background: '#333',
  color: '#ddd', fontSize: 13, cursor: 'pointer',
};
const btnGreen: React.CSSProperties = { ...btnStyle, background: '#2e7d32', color: '#fff' };
const btnYellow: React.CSSProperties = { ...btnStyle, background: '#f57f17', color: '#fff' };
const btnRed: React.CSSProperties = { ...btnStyle, background: '#c62828', color: '#fff' };
const inputStyle: React.CSSProperties = {
  padding: '8px 12px', borderRadius: 6, border: '1px solid #333',
  background: '#111', color: '#ddd', fontSize: 13,
};
const cardStyle: React.CSSProperties = {
  background: '#111', borderRadius: 8, padding: 16, marginBottom: 16,
  border: '1px solid #222',
};
const muted: React.CSSProperties = { color: '#555', fontSize: 13 };
