import { useState, useEffect, useCallback } from 'react';
import { getSlotValue } from '../shared/identity';

interface HostMapNode {
  nodeId: string; name: string; description: string;
  position: { x: number; y: number };
  explored: boolean; hidden: boolean;
  hasClues: boolean; hasNpcs: boolean;
  npcsPresent: string[]; cluesAvailable: string[];
}

export interface HostMapRegion {
  regionId: string;
  nodeId: string;
  label: string;
}

interface HostMapData {
  mapId: string; mapName: string;
  nodes: HostMapNode[];
  edges: Array<{ from: string; to: string }>;
  playerPositions: Record<string, string>;
  exploredNodes: string[]; hiddenNodes: string[];
  regions: Array<{ regionId: string; nodeId: string }>;
  fogRegions: string[];
  mapStatus: string;
}

interface HostMapPanelProps {
  roomId: string;
  mapRefresh: number;
}

export function RegionFogControls({
  regions,
  fogRegions,
  disabled = false,
}: {
  regions: HostMapRegion[];
  fogRegions: string[];
  disabled?: boolean;
}) {
  if (regions.length === 0) return null;
  const fogged = new Set(fogRegions);
  return (
    <div className="bh-map-info" style={{ marginTop: 12, padding: 12, border: '2px solid var(--bh-black)' }}>
      <span className="bh-eyebrow" style={{ fontSize: 9 }}>区域迷雾 · 只读</span>
      <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
        {regions.map((region) => {
          const visible = !fogged.has(region.regionId);
          return (
            <div key={region.regionId} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 12 }}>{region.label}：{visible ? '已显示' : '迷雾中'}</span>
              <span className="bh-eyebrow" style={{ fontSize: 9 }}>{disabled ? '只读' : '只读'}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function HostMapPanel({ roomId, mapRefresh }: HostMapPanelProps) {
  const [mapData, setMapData] = useState<HostMapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [mapStatus, setMapStatus] = useState('no_map');
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const fetchMap = useCallback(() => {
    const token = getSlotValue('owner_token') || '';
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

      <RegionFogControls
        regions={(mapData.regions || []).map((region) => ({
          ...region,
          label: mapData.nodes.find((node) => node.nodeId === region.nodeId)?.name || region.regionId,
        }))}
        fogRegions={mapData.fogRegions || []}
        disabled
      />

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
              <span className="bh-eyebrow" style={{ fontSize: 9 }}>只读导演台</span>
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
