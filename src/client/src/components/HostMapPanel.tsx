import { useState, useEffect, useCallback } from 'react';

interface HostMapNode {
  nodeId: string; name: string; description: string;
  position: { x: number; y: number };
  explored: boolean; hidden: boolean;
  hasClues: boolean; hasNpcs: boolean;
  npcsPresent: string[]; cluesAvailable: string[];
}

interface HostMapData {
  mapId: string; mapName: string;
  nodes: HostMapNode[];
  edges: Array<{ from: string; to: string }>;
  playerPositions: Record<string, string>;
  exploredNodes: string[]; hiddenNodes: string[];
  mapStatus: string;
}

interface HostMapPanelProps {
  roomId: string;
  mapRefresh: number;
}

function getHostToken(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get('token') || '';
}

export default function HostMapPanel({ roomId, mapRefresh }: HostMapPanelProps) {
  const [mapData, setMapData] = useState<HostMapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [mapStatus, setMapStatus] = useState('no_map');
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [operationPending, setOperationPending] = useState(false);

  const fetchMap = useCallback(() => {
    const token = getHostToken();
    fetch(`/api/host/${encodeURIComponent(roomId)}/map/full`, {
      headers: { 'X-Owner-Token': token },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: HostMapData | null) => {
        if (data && data.nodes && data.nodes.length > 0) {
          setMapData(data);
          setMapStatus(data.mapStatus || 'active');
        } else {
          setMapData(null);
          setMapStatus('no_map');
        }
      })
      .catch(() => { setMapStatus('no_map'); })
      .finally(() => setLoading(false));
  }, [roomId]);

  useEffect(() => {
    fetchMap();
  }, [fetchMap, mapRefresh]);

  const handleReveal = async (nodeId: string) => {
    setOperationPending(true);
    const token = getHostToken();
    try {
      await fetch(`/api/host/${encodeURIComponent(roomId)}/map/reveal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
        body: JSON.stringify({ node_id: nodeId, visible: true }),
      });
    } catch { /* ignore */ }
    fetchMap();
    setOperationPending(false);
  };

  const handleHide = async (nodeId: string) => {
    setOperationPending(true);
    const token = getHostToken();
    try {
      await fetch(`/api/host/${encodeURIComponent(roomId)}/map/reveal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
        body: JSON.stringify({ node_id: nodeId, visible: false }),
      });
    } catch { /* ignore */ }
    fetchMap();
    setOperationPending(false);
  };

  const handleForceMove = async (nodeId: string) => {
    if (!mapData) return;
    // Find a character to move — use first player with a known position
    const players = Object.entries(mapData.playerPositions || {});
    if (players.length === 0) return;
    const [characterId] = players[0];
    setOperationPending(true);
    const token = getHostToken();
    try {
      // Use the host move-character endpoint
      await fetch(`/api/host/${encodeURIComponent(roomId)}/map/move-character`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
        body: JSON.stringify({ character_id: characterId, node_id: nodeId }),
      });
    } catch { /* ignore */ }
    fetchMap();
    setOperationPending(false);
  };

  if (loading) {
    return (
      <section className="bh-panel">
        <span className="bh-eyebrow">MAP</span>
        <h2 className="bh-panel-title">地图监督</h2>
        <div className="bh-muted-box">加载地图中...</div>
      </section>
    );
  }

  if (mapStatus === 'no_map' || !mapData) {
    return (
      <section className="bh-panel">
        <span className="bh-eyebrow">MAP</span>
        <h2 className="bh-panel-title">地图监督</h2>
        <div className="bh-muted-box" style={{ padding: 32, textAlign: 'center' }}>
          <p style={{ fontWeight: 700, marginBottom: 8 }}>当前房间未初始化地图</p>
          <p style={{ fontSize: 12, color: 'var(--bh-dim)' }}>
            请先在管理后台导入或生成场景地图，然后启动房间。
          </p>
        </div>
      </section>
    );
  }

  const selected = mapData.nodes.find((n) => n.nodeId === selectedNode);
  const playerPositions = mapData.playerPositions || {};
  const playersOnNodes: Record<string, string[]> = {};
  Object.entries(playerPositions).forEach(([charId, nodeId]) => {
    if (!playersOnNodes[nodeId]) playersOnNodes[nodeId] = [];
    playersOnNodes[nodeId].push(charId);
  });

  return (
    <section className="bh-panel">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <span className="bh-eyebrow">HOST MAP CONTROL</span>
          <h2 className="bh-panel-title">
            {mapData.mapName || '场景地图'}
          </h2>
        </div>
        <div style={{ display: 'flex', gap: 8, fontSize: 11, color: 'var(--bh-dim)' }}>
          <span>节点 {mapData.nodes.length}</span>
          <span>|</span>
          <span>已探索 {mapData.exploredNodes?.length || 0}</span>
          <span>|</span>
          <span>隐藏 {mapData.hiddenNodes?.length || 0}</span>
        </div>
      </div>

      {operationPending && (
        <div className="bh-muted-box" style={{ marginBottom: 8 }}>操作已提交...</div>
      )}

      <div className="bh-map-grid" style={{ position: 'relative', minHeight: 300, border: '2px solid var(--bh-black)' }}>
        {mapData.nodes.map((node) => {
          const isHidden = mapData.hiddenNodes?.includes(node.nodeId);
          const isExplored = !isHidden || mapData.exploredNodes?.includes(node.nodeId);
          const hasPlayers = (playersOnNodes[node.nodeId]?.length || 0) > 0;
          const isSelected = node.nodeId === selectedNode;

          const posX = node.position?.x ?? 50;
          const posY = node.position?.y ?? 50;

          let className = 'bh-map-node';
          if (hasPlayers) className += ' bh-map-node--current';
          if (isExplored) className += ' bh-map-node--explored';
          if (isHidden) className += ' bh-map-node--hidden';
          if (isSelected) className += ' bh-map-node--selected';

          return (
            <button
              key={node.nodeId}
              className={className}
              style={{
                position: 'absolute',
                left: `${posX}%`,
                top: `${posY}%`,
                transform: 'translate(-50%, -50%)',
                cursor: 'pointer',
                opacity: isHidden ? 0.4 : 1,
              }}
              onClick={() => setSelectedNode(node.nodeId)}
              title={node.description}
            >
              <span className="bh-map-node-name">
                {isHidden ? '???' : node.name}
              </span>
              {hasPlayers && <span className="bh-map-node-badge">P</span>}
              {!isHidden && node.hasClues && <span className="bh-map-node-badge" style={{ fontSize: 8 }}>🔍</span>}
              {!isHidden && node.hasNpcs && <span className="bh-map-node-badge" style={{ fontSize: 8 }}>👤</span>}
            </button>
          );
        })}

        {/* Edge lines */}
        <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 0 }}>
          {(mapData.edges || []).map((edge, i) => {
            const from = mapData.nodes.find((n) => n.nodeId === edge.from);
            const to = mapData.nodes.find((n) => n.nodeId === edge.to);
            if (!from || !to) return null;
            const fromHidden = mapData.hiddenNodes?.includes(from.nodeId);
            const toHidden = mapData.hiddenNodes?.includes(to.nodeId);
            const opacity = (fromHidden || toHidden) ? 0.15 : 0.5;
            return (
              <line
                key={`edge-${i}`}
                x1={`${from.position?.x ?? 50}%`}
                y1={`${from.position?.y ?? 50}%`}
                x2={`${to.position?.x ?? 50}%`}
                y2={`${to.position?.y ?? 50}%`}
                stroke="var(--bh-black)"
                strokeWidth={1.5}
                opacity={opacity}
              />
            );
          })}
        </svg>
      </div>

      {/* Selected node detail */}
      {selected && (
        <div className="bh-map-info" style={{ marginTop: 12, padding: 12, border: '2px solid var(--bh-black)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <strong style={{ display: 'block', marginBottom: 4 }}>{selected.name}</strong>
              <p style={{ fontSize: 13, color: 'var(--bh-dim)', marginBottom: 8 }}>{selected.description}</p>
              {selected.hasClues && (
                <span className="bh-eyebrow" style={{ fontSize: 9 }}>线索: {selected.cluesAvailable?.join(', ') || '有线索'}</span>
              )}
              {selected.hasNpcs && (
                <span className="bh-eyebrow" style={{ fontSize: 9, marginLeft: 8 }}>NPC: {selected.npcsPresent?.join(', ') || '有NPC'}</span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {mapData.hiddenNodes?.includes(selected.nodeId) ? (
                <button
                  className="bh-button bh-button--yellow"
                  style={{ fontSize: 11, padding: '4px 8px' }}
                  onClick={() => handleReveal(selected.nodeId)}
                  type="button"
                >
                  揭示节点
                </button>
              ) : (
                <button
                  className="bh-button"
                  style={{ fontSize: 11, padding: '4px 8px' }}
                  onClick={() => handleHide(selected.nodeId)}
                  type="button"
                >
                  隐藏节点
                </button>
              )}
              {Object.keys(playerPositions).length > 0 && (
                <select
                  style={{
                    fontSize: 11, padding: '4px 8px',
                    border: '2px solid var(--bh-black)',
                    background: 'var(--bh-paper)',
                    fontFamily: 'inherit',
                  }}
                  onChange={(e) => {
                    const charId = e.target.value;
                    if (charId) {
                      const token = getHostToken();
                      fetch(`/api/host/${encodeURIComponent(roomId)}/map/move-character`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
                        body: JSON.stringify({ character_id: charId, node_id: selected.nodeId }),
                      }).then(() => fetchMap());
                    }
                  }}
                  value=""
                >
                  <option value="">强制移动...</option>
                  {Object.entries(playerPositions).map(([charId, _nodeId]) => (
                    <option key={charId} value={charId}>角色 {charId.slice(0, 4)}</option>
                  ))}
                </select>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Player position list */}
      {Object.keys(playerPositions).length > 0 && (
        <div style={{ marginTop: 12 }}>
          <span className="bh-eyebrow" style={{ fontSize: 9 }}>角色位置</span>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(playerPositions).map(([charId, nodeId]) => {
              const node = mapData.nodes.find((n) => n.nodeId === nodeId);
              return (
                <span key={charId} style={{
                  fontSize: 11, padding: '2px 6px',
                  border: '1px solid var(--bh-black)',
                  background: 'var(--bh-yellow)',
                }}>
                  {charId.slice(0, 4)} → {node?.name || nodeId}
                </span>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
