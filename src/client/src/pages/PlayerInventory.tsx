import { useState, useEffect } from 'react';
import { apiFetch, authHeaders } from '../api';
import type { InventoryItem, Clue } from '../types';
import { describeClueShare, describeItemUse } from '../shared/player-inventory-intents';

export default function PlayerInventory({
  onDescribeInNarration,
  onOpenCampaignHome,
}: {
  onDescribeInNarration: (text: string) => void;
  onOpenCampaignHome: () => void;
}) {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [clues, setClues] = useState<Clue[]>([]);
  const [selectedItem, setSelectedItem] = useState<InventoryItem | null>(null);
  const [selectedClue, setSelectedClue] = useState<Clue | null>(null);
  const [activeSection, setActiveSection] = useState<'items' | 'clues' | 'evidence'>('items');

  useEffect(() => {
    apiFetch<{ clues: Clue[] }>('/api/player/clues', { headers: authHeaders() })
      .then((d) => setClues(d.clues))
      .catch(() => {});
    apiFetch<InventoryItem[]>('/api/player/inventory', { headers: authHeaders() })
      .then(setItems)
      .catch(() => {});
  }, []);

  const cluePosition = (id: string, index: number) => {
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
      hash = ((hash << 5) - hash + id.charCodeAt(i)) | 0;
    }
    const x = (Math.abs(hash) % 80) + 10;
    const y = index * 90 + 10;
    return { x, y };
  };

  return (
    <div>
      <section className="bh-panel" style={{ marginBottom: 16 }}>
        <span className="bh-eyebrow">PLAYER MATERIALS</span>
        <h2 className="bh-panel-title">物品、线索与证据</h2>
        <div className="bh-source-toggle" style={{ marginTop: 12 }}>
          <button className={`bh-button ${activeSection === 'items' ? 'bh-button--yellow' : ''}`} type="button" onClick={() => setActiveSection('items')}>背包</button>
          <button className={`bh-button ${activeSection === 'clues' ? 'bh-button--yellow' : ''}`} type="button" onClick={() => setActiveSection('clues')}>个人线索</button>
          <button className={`bh-button ${activeSection === 'evidence' ? 'bh-button--yellow' : ''}`} type="button" onClick={() => setActiveSection('evidence')}>队伍证据</button>
        </div>
      </section>

      {activeSection === 'items' && <section className="bh-panel">
      <h3 style={{ marginBottom: 12 }}>背包</h3>
      {items.length === 0 ? (
        <p style={{ color: '#666', fontSize: 13 }}>暂无物品</p>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 24 }}>
          {items.map((item) => (
            <div
              key={item.id}
              onClick={() => setSelectedItem(item)}
              style={{
                background: 'rgba(255,255,255,0.05)',
                borderRadius: 8,
                padding: 10,
                textAlign: 'center',
                cursor: 'pointer',
                border: item.is_secret ? '1px solid #ff9800' : '1px solid transparent',
                position: 'relative',
              }}
            >
              {item.is_secret ? (
                <div style={{ position: 'absolute', top: 4, right: 6, fontSize: 10, color: '#ff9800' }}>
                  秘密
                </div>
              ) : null}
              <div style={{ fontSize: 13, fontWeight: 'bold' }}>{item.name}</div>
              {item.quantity > 1 && (
                <div style={{ fontSize: 11, color: '#888' }}>x{item.quantity}</div>
              )}
            </div>
          ))}
        </div>
      )}
      </section>}

      {activeSection === 'clues' && <section className="bh-panel">
      <h3 style={{ marginBottom: 12 }}>个人线索</h3>
      {clues.length === 0 ? (
        <p style={{ color: '#666', fontSize: 13 }}>暂无线索</p>
      ) : (
        <div style={{
          position: 'relative',
          background: 'rgba(139,90,43,0.15)',
          borderRadius: 12,
          border: '2px solid #5d4037',
          minHeight: clues.length * 90 + 20,
          padding: 10,
        }}>
          {clues.map((clue, i) => {
            const pos = cluePosition(clue.id, i);
            return (
              <div
                key={clue.id}
                onClick={() => setSelectedClue(clue)}
                style={{
                  position: 'absolute',
                  left: `${pos.x}%`,
                  top: pos.y,
                  background: clue.is_private ? '#fff9c4' : '#e8f5e9',
                  color: '#333',
                  padding: '8px 10px',
                  borderRadius: 4,
                  boxShadow: '2px 2px 6px rgba(0,0,0,0.3)',
                  maxWidth: 180,
                  fontSize: 12,
                  cursor: 'pointer',
                  transform: `rotate(${(i % 3 - 1) * 3}deg)`,
                }}
              >
                {clue.text.length > 40 ? clue.text.slice(0, 40) + '...' : clue.text}
                {clue.source && (
                  <div style={{ fontSize: 10, color: '#888', marginTop: 4 }}>
                    来源: {clue.source}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      </section>}

      {activeSection === 'evidence' && (
        <section className="bh-panel">
          <span className="bh-eyebrow">TEAM EVIDENCE</span>
          <h3 style={{ marginBottom: 8 }}>队伍证据板</h3>
          <p style={{ color: 'var(--bh-dim)', fontSize: 13 }}>
            这里仅展示所有玩家已公开的证据、关系与已确认事实；私人线索不会自动公开。
          </p>
          <button className="bh-button bh-button--yellow" type="button" onClick={onOpenCampaignHome}>打开队伍证据板</button>
        </section>
      )}

      {selectedItem && (
        <div
          onClick={() => setSelectedItem(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'flex-end', justifyContent: 'center', zIndex: 100,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#1a1a2e', borderRadius: '16px 16px 0 0', padding: 24,
              width: '100%', maxWidth: 480, maxHeight: '50vh', overflow: 'auto',
            }}
          >
            <h3 style={{ margin: 0 }}>{selectedItem.name}</h3>
            <p style={{ color: '#aaa', fontSize: 14, marginTop: 8 }}>{selectedItem.description || '无描述'}</p>
            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button
                onClick={() => {
                  onDescribeInNarration(describeItemUse(selectedItem.name));
                  setSelectedItem(null);
                }}
                style={{ flex: 1, padding: 10, borderRadius: 8, border: 'none', background: '#3f51b5', color: '#fff', fontSize: 14 }}
              >
                在叙事中使用
              </button>
              <button
                onClick={() => {
                  onDescribeInNarration(`我想把${selectedItem.name}展示给队友。`);
                  setSelectedItem(null);
                }}
                style={{ flex: 1, padding: 10, borderRadius: 8, border: 'none', background: '#4caf50', color: '#fff', fontSize: 14 }}
              >
                展示给队友
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedClue && (
        <div
          onClick={() => setSelectedClue(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#1a1a2e', borderRadius: 12, padding: 24,
              width: '90%', maxWidth: 400,
            }}
          >
            <h3 style={{ margin: 0, marginBottom: 8 }}>线索详情</h3>
            <p style={{ color: '#ddd', fontSize: 14 }}>{selectedClue.text}</p>
            {selectedClue.source && (
              <p style={{ color: '#888', fontSize: 12, marginTop: 8 }}>来源: {selectedClue.source}</p>
            )}
            <div style={{ fontSize: 12, color: selectedClue.is_private ? '#ff9800' : '#4caf50', marginTop: 8 }}>
              {selectedClue.is_private ? '私密线索' : '已分享'}
            </div>
            {selectedClue.is_private && (
              <button
                onClick={() => {
                  onDescribeInNarration(describeClueShare(selectedClue.text));
                  setSelectedClue(null);
                }}
                style={{
                  marginTop: 12, width: '100%', padding: 10, borderRadius: 8,
                  border: 'none', background: '#ff9800', color: '#fff', fontSize: 14,
                }}
              >
                在叙事中分享
              </button>
            )}
            <button
              onClick={() => setSelectedClue(null)}
              style={{
                marginTop: 8, width: '100%', padding: 10, borderRadius: 8,
                border: '1px solid #333', background: 'transparent', color: '#aaa', fontSize: 14,
              }}
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
