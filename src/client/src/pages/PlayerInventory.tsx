import { useState, useEffect } from 'react';
import { apiFetch, authHeaders } from '../api';
import type { InventoryItem, Clue } from '../types';

export default function PlayerInventory() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [clues, setClues] = useState<Clue[]>([]);
  const [selectedItem, setSelectedItem] = useState<InventoryItem | null>(null);
  const [selectedClue, setSelectedClue] = useState<Clue | null>(null);

  useEffect(() => {
    apiFetch<{ clues: Clue[] }>('/api/player/clues', { headers: authHeaders() })
      .then((d) => setClues(d.clues))
      .catch(() => {});
    apiFetch<InventoryItem[]>('/api/player/inventory', { headers: authHeaders() })
      .then(setItems)
      .catch(() => {});
  }, []);

  const shareClue = async (clueId: string) => {
    try {
      await apiFetch(`/api/player/clues/${clueId}/share`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({}),
      });
      setClues((prev) =>
        prev.map((c) => (c.id === clueId ? { ...c, is_private: false } : c))
      );
      setSelectedClue(null);
    } catch {
      // ignore
    }
  };

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

      <h3 style={{ marginBottom: 12 }}>线索板</h3>
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
                  apiFetch('/api/player/intent', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({ intent_type: 'use_item', params: { itemId: selectedItem.id } }),
                  });
                  setSelectedItem(null);
                }}
                style={{ flex: 1, padding: 10, borderRadius: 8, border: 'none', background: '#3f51b5', color: '#fff', fontSize: 14 }}
              >
                尝试使用
              </button>
              <button
                onClick={() => {
                  apiFetch('/api/player/intent', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({ intent_type: 'dialogue', params: { itemId: selectedItem.id, action: 'show_item' } }),
                  });
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
                onClick={() => shareClue(selectedClue.id)}
                style={{
                  marginTop: 12, width: '100%', padding: 10, borderRadius: 8,
                  border: 'none', background: '#ff9800', color: '#fff', fontSize: 14,
                }}
              >
                分享给队伍
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
