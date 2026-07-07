import { useEffect, useState } from 'react';
import { getSlotValue } from '../shared/identity';

interface TimelineEntry {
  sequence: number;
  event_type: string;
  audience: string;
  payload: Record<string, unknown>;
  issued_at: string;
}

interface CheckpointData {
  checkpoint_id: string;
  room_id: string;
  created_at: string;
}

export default function HostLogsPanel({ roomId }: { roomId: string }) {
  const [events, setEvents] = useState<TimelineEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [replayEvent, setReplayEvent] = useState<TimelineEntry | null>(null);
  const [checkpoints, setCheckpoints] = useState<CheckpointData[]>([]);
  const [cpNote, setCpNote] = useState('');
  const [restoringId, setRestoringId] = useState('');

  const token = getSlotValue('owner_token') || '';

  const fetchEvents = () => {
    const params = new URLSearchParams({ limit: '200' });
    if (filter) params.set('event_type', filter);
    if (keyword) params.set('keyword', keyword);
    fetch(`/api/rooms/${encodeURIComponent(roomId)}/timeline?${params}`, {
      headers: { 'X-Owner-Token': token },
    })
      .then((r) => r.json())
      .then((d) => setEvents(d.events || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  const fetchCheckpoints = () => {
    fetch(`/api/rooms/${encodeURIComponent(roomId)}/checkpoints`, {
      headers: { 'X-Owner-Token': token },
    })
      .then((r) => r.json())
      .then((d) => setCheckpoints(d.checkpoints || []))
      .catch(() => {});
  };

  useEffect(() => { fetchEvents(); fetchCheckpoints(); }, [roomId]);

  const handleCreateCheckpoint = async () => {
    const res = await fetch(`/api/rooms/${encodeURIComponent(roomId)}/checkpoint`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
      body: JSON.stringify({ auto: false, reason: cpNote }),
    });
    if (res.ok) { setCpNote(''); fetchCheckpoints(); }
  };

  const handleRestore = async (checkpointId: string) => {
    if (!confirm(`确认恢复到检查点 ${checkpointId}？此操作将覆盖当前房间状态。`)) return;
    setRestoringId(checkpointId);
    await fetch(`/api/rooms/${encodeURIComponent(roomId)}/restore/${checkpointId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
      body: JSON.stringify({ confirm: true }),
    });
    setRestoringId('');
    fetchEvents();
  };

  const handleExport = async (format: string, scope: string) => {
    const params = new URLSearchParams({ format, scope });
    const res = await fetch(`/api/rooms/${encodeURIComponent(roomId)}/export?${params}`, {
      headers: { 'X-Owner-Token': token },
    });
    const data = await res.json();
    const blob = new Blob(
      [format === 'json' ? JSON.stringify(data.data || data, null, 2) : (data.content || '')],
      { type: format === 'json' ? 'application/json' : 'text/markdown' },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `room_${roomId}_${scope}.${format === 'json' ? 'json' : 'md'}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getTypeLabel = (evType: string) => {
    if (evType.includes('reveal_transaction')) return '🎭 叙事';
    if (evType.includes('public_observation')) return '💬 公开';
    if (evType.includes('action_completed')) return '✅ 结算';
    if (evType.includes('state_patch')) return '🔄 状态';
    if (evType.includes('player_moved')) return '🚶 移动';
    if (evType.includes('map_')) return '🗺️ 地图';
    if (evType.includes('encounter_')) return '⚔️ 遭遇';
    if (evType.includes('checkpoint')) return '📸 检查点';
    return '📌 ' + evType.replace('s2c_', '').slice(0, 20);
  };

  const getPayloadSummary = (ev: TimelineEntry) => {
    const p = ev.payload;
    if (p.text && typeof p.text === 'string') return p.text.slice(0, 100);
    if (p.summaryText && typeof p.summaryText === 'string') return p.summaryText.slice(0, 100);
    if (p.skill_name || p.skillName) return `🎲 ${p.skill_name || p.skillName} ${p.roll}/${p.target}`;
    if (p.toNodeId) return `→ ${p.toNodeId}`;
    if (p.reason) return String(p.reason).slice(0, 100);
    return JSON.stringify(p).slice(0, 80);
  };

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">AUDIT LOG</span>
      <h2 className="bh-panel-title">事件时间线</h2>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        <select className="bh-input" value={filter} onChange={(e) => { setFilter(e.target.value); setLoading(true); setTimeout(fetchEvents, 0); }}>
          <option value="">全部类型</option>
          <option value="s2c_reveal_transaction">叙事</option>
          <option value="s2c_action_completed">结算</option>
          <option value="s2c_state_patch">状态变更</option>
          <option value="s2c_public_observation">公开观察</option>
          <option value="s2c_player_moved">移动</option>
          <option value="s2c_map_updated">地图</option>
          <option value="s2c_encounter_started">遭遇开始</option>
          <option value="s2c_encounter_resolved">遭遇结束</option>
          <option value="s2c_team_message">💬 队伍消息</option>
        </select>
        <input className="bh-input" placeholder="关键词搜索..." value={keyword}
               onChange={(e) => setKeyword(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') { setLoading(true); fetchEvents(); } }} />
        <button className="bh-button bh-button--black" onClick={() => { setLoading(true); fetchEvents(); }}>
          查询
        </button>
        <button className="bh-button" onClick={() => handleExport('markdown', 'public')}>📥 导出MD</button>
        <button className="bh-button" onClick={() => handleExport('json', 'full')}>📥 导出JSON</button>
      </div>

      {/* Events list */}
      {loading ? (
        <div className="bh-muted-box">加载时间线中...</div>
      ) : events.length === 0 ? (
        <div className="bh-muted-box">暂无事件记录</div>
      ) : (
        <div style={{ maxHeight: 400, overflowY: 'auto' }}>
          {events.map((ev) => (
            <div key={ev.sequence} className="bh-skeleton-row"
                 style={{ cursor: 'pointer' }}
                 onClick={() => setReplayEvent(ev)}>
              <span>
                <strong>{getTypeLabel(ev.event_type)}</strong>
                <span style={{ fontSize: 10, marginLeft: 6, opacity: 0.5 }}>#{ev.sequence}</span>
              </span>
              <span style={{ fontSize: 11, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {getPayloadSummary(ev)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Replay popup */}
      {replayEvent && (
        <div style={{ marginTop: 8, padding: 8, border: '2px solid var(--bh-yellow)', background: 'var(--bh-paper)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <strong>{getTypeLabel(replayEvent.event_type)} #{replayEvent.sequence}</strong>
            <button className="bh-button" style={{ padding: '2px 8px' }} onClick={() => setReplayEvent(null)}>✕</button>
          </div>
          <pre style={{ fontSize: 10, marginTop: 4, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
            {JSON.stringify(replayEvent.payload, null, 2)}
          </pre>
        </div>
      )}

      {/* Checkpoint panel */}
      <details style={{ marginTop: 12 }}>
        <summary className="bh-eyebrow" style={{ cursor: 'pointer' }}>
          📸 检查点 ({checkpoints.length})
        </summary>
        <div style={{ marginTop: 8 }}>
          <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
            <input className="bh-input" placeholder="检查点备注..." value={cpNote}
                   onChange={(e) => setCpNote(e.target.value)} />
            <button className="bh-button bh-button--yellow" onClick={handleCreateCheckpoint}>
              创建检查点
            </button>
          </div>
          {checkpoints.slice(0, 10).map((cp) => (
            <div key={cp.checkpoint_id} className="bh-skeleton-row">
              <span>{cp.checkpoint_id} <small style={{ opacity: 0.5 }}>{cp.created_at?.slice(0, 19)}</small></span>
              <button className="bh-button bh-button--red" style={{ padding: '2px 8px', fontSize: 10 }}
                      disabled={restoringId === cp.checkpoint_id}
                      onClick={() => handleRestore(cp.checkpoint_id)}>
                {restoringId === cp.checkpoint_id ? '恢复中...' : '恢复'}
              </button>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}
