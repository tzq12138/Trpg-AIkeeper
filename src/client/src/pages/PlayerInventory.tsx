import { useState, useEffect } from 'react';
import { apiFetch, authHeaders } from '../api';
import type { InventoryItem, Clue, PlayerNoteDTO } from '../types';
import { describeItemUse } from '../shared/player-inventory-intents';
import { updatePlayerNote } from '../shared/player-api';
import {
  requestInventoryTransfer,
  resolveInventoryTransfer,
  type InventoryTransferDTO,
} from '../shared/inventory-transfer-api';

interface TransferCandidate {
  characterId: string;
  playerName: string;
}

export default function PlayerInventory({
  onDescribeInNarration,
  onOpenCampaignHome,
}: {
  onDescribeInNarration: (text: string) => void;
  onOpenCampaignHome: () => void;
}) {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [clues, setClues] = useState<Clue[]>([]);
  const [notes, setNotes] = useState<PlayerNoteDTO[]>([]);
  const [selectedItem, setSelectedItem] = useState<InventoryItem | null>(null);
  const [selectedClue, setSelectedClue] = useState<Clue | null>(null);
  const [shareDraft, setShareDraft] = useState<{ clueId: string; summary: string } | null>(null);
  const [shareError, setShareError] = useState('');
  const [noteDraft, setNoteDraft] = useState<{ noteId?: string; title: string; body: string } | null>(null);
  const [noteError, setNoteError] = useState('');
  const [savingNote, setSavingNote] = useState(false);
  const [activeSection, setActiveSection] = useState<'items' | 'clues' | 'notes' | 'evidence'>('items');
  const [transferCandidates, setTransferCandidates] = useState<TransferCandidate[]>([]);
  const [transfers, setTransfers] = useState<{ incoming: InventoryTransferDTO[]; outgoing: InventoryTransferDTO[] }>({ incoming: [], outgoing: [] });
  const [transferDraft, setTransferDraft] = useState<{ item: InventoryItem; toCharacterId: string; quantity: number } | null>(null);
  const [transferError, setTransferError] = useState('');
  const [resolvingTransferId, setResolvingTransferId] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ clues: Clue[] }>('/api/player/clues', { headers: authHeaders() })
      .then((d) => setClues(d.clues))
      .catch(() => {});
    apiFetch<InventoryItem[]>('/api/player/inventory', { headers: authHeaders() })
      .then(setItems)
      .catch(() => {});
    apiFetch<{ notes: PlayerNoteDTO[] }>('/api/player/notes', { headers: authHeaders() })
      .then((data) => setNotes(data.notes.filter((note) => note.visibility === 'private')))
      .catch(() => {});
    apiFetch<{ candidates: TransferCandidate[] }>('/api/player/inventory-transfer-candidates', { headers: authHeaders() })
      .then((data) => setTransferCandidates(data.candidates || []))
      .catch(() => {});
    apiFetch<{ incoming: InventoryTransferDTO[]; outgoing: InventoryTransferDTO[] }>('/api/player/inventory-transfers', { headers: authHeaders() })
      .then((data) => setTransfers({ incoming: data.incoming || [], outgoing: data.outgoing || [] }))
      .catch(() => {});
  }, []);

  const refreshItems = async () => {
    const data = await apiFetch<InventoryItem[]>('/api/player/inventory', { headers: authHeaders() });
    setItems(data);
  };

  const refreshTransfers = async () => {
    const data = await apiFetch<{ incoming: InventoryTransferDTO[]; outgoing: InventoryTransferDTO[] }>(
      '/api/player/inventory-transfers', { headers: authHeaders() },
    );
    setTransfers({ incoming: data.incoming || [], outgoing: data.outgoing || [] });
  };

  const refreshClues = async () => {
    const data = await apiFetch<{ clues: Clue[] }>('/api/player/clues', { headers: authHeaders() });
    setClues(data.clues);
  };

  const shareClue = async () => {
    if (!shareDraft || !shareDraft.summary.trim()) return;
    setShareError('');
    try {
      await apiFetch(`/api/player/clues/${encodeURIComponent(shareDraft.clueId)}/share`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ public_version: shareDraft.summary.trim() }),
      });
      await refreshClues();
      setShareDraft(null);
      setSelectedClue(null);
    } catch {
      setShareError('分享未完成。请检查摘要是否包含未公开信息后重试。');
    }
  };

  const saveNote = async () => {
    const draft = noteDraft;
    if (!draft?.title.trim() || !draft.body.trim() || savingNote) return;
    setSavingNote(true);
    setNoteError('');
    try {
      const title = draft.title.trim();
      const body = draft.body.trim();
      const note = draft.noteId
        ? await updatePlayerNote(draft.noteId, title, body)
        : await apiFetch<PlayerNoteDTO>('/api/player/notes', {
          method: 'POST',
          headers: { ...authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, body }),
        });
      setNotes((previous) => draft.noteId
        ? previous.map((current) => current.note_id === note.note_id ? note : current)
        : [note, ...previous]);
      setNoteDraft(null);
    } catch {
      setNoteError('笔记未保存。请检查连接后重试。');
    } finally {
      setSavingNote(false);
    }
  };

  const requestTransfer = async () => {
    const draft = transferDraft;
    if (!draft?.toCharacterId || draft.quantity < 1 || draft.quantity > draft.item.quantity) return;
    setTransferError('');
    try {
      await requestInventoryTransfer(draft.item.id, draft.toCharacterId, draft.quantity, authHeaders());
      await refreshTransfers();
      setTransferDraft(null);
      setSelectedItem(null);
    } catch {
      setTransferError('转交请求未创建。物品可能已不可用，或接收方已离开房间。');
    }
  };

  const resolveTransfer = async (transferId: string, decision: 'accept' | 'reject') => {
    setResolvingTransferId(transferId);
    setTransferError('');
    try {
      await resolveInventoryTransfer(transferId, decision, authHeaders());
      await Promise.all([refreshItems(), refreshTransfers()]);
    } catch {
      setTransferError('处理转交失败。物品可能已被使用或请求已过期。');
      await refreshTransfers().catch(() => {});
    } finally {
      setResolvingTransferId(null);
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
      <section className="bh-panel" style={{ marginBottom: 16 }}>
        <span className="bh-eyebrow">PLAYER MATERIALS</span>
        <h2 className="bh-panel-title">物品、线索与证据</h2>
        <div className="bh-source-toggle" style={{ marginTop: 12 }}>
          <button className={`bh-button ${activeSection === 'items' ? 'bh-button--yellow' : ''}`} type="button" onClick={() => setActiveSection('items')}>背包</button>
          <button className={`bh-button ${activeSection === 'clues' ? 'bh-button--yellow' : ''}`} type="button" onClick={() => setActiveSection('clues')}>个人线索</button>
          <button className={`bh-button ${activeSection === 'notes' ? 'bh-button--yellow' : ''}`} type="button" onClick={() => setActiveSection('notes')}>我的笔记</button>
          <button className={`bh-button ${activeSection === 'evidence' ? 'bh-button--yellow' : ''}`} type="button" onClick={() => setActiveSection('evidence')}>队伍证据</button>
        </div>
        <button
          className="bh-button"
          type="button"
          style={{ marginTop: 12 }}
          onClick={() => {
            setActiveSection('notes');
            setNoteError('');
            setNoteDraft((current) => current || { title: '', body: '' });
          }}
        >
          新建笔记
        </button>
      </section>

      {activeSection === 'items' && <section className="bh-panel">
      <h3 style={{ marginBottom: 12 }}>背包</h3>
      {transfers.incoming.some((transfer) => transfer.status === 'pending') && (
        <section className="bh-muted-box" style={{ marginBottom: 12 }} aria-label="待接收物品">
          <strong>待接收物品</strong>
          <p style={{ marginTop: 6, fontSize: 13 }}>接收后才会写入你的背包；拒绝不会改变双方库存。</p>
          {transfers.incoming.filter((transfer) => transfer.status === 'pending').map((transfer) => (
            <article key={transfer.transferId} style={{ borderTop: '1px solid var(--bh-black)', marginTop: 8, paddingTop: 8 }}>
              <strong>{transfer.itemName} × {transfer.quantity}</strong>
              <small style={{ display: 'block' }}>来自 {transfer.fromPlayerName}</small>
              {transfer.isSecret && <small style={{ display: 'block', color: 'var(--bh-red)' }}>仅你和转交方可见的私密物品</small>}
              <div className="bh-action-row bh-action-row--responsive" style={{ marginTop: 8 }}>
                <button className="bh-button bh-button--yellow" type="button" disabled={resolvingTransferId === transfer.transferId} onClick={() => void resolveTransfer(transfer.transferId, 'accept')}>接收</button>
                <button className="bh-button" type="button" disabled={resolvingTransferId === transfer.transferId} onClick={() => void resolveTransfer(transfer.transferId, 'reject')}>拒绝</button>
              </div>
            </article>
          ))}
        </section>
      )}
      {transfers.outgoing.some((transfer) => transfer.status === 'pending') && (
        <section className="bh-muted-box" style={{ marginBottom: 12 }} aria-label="等待接收的物品">
          <strong>等待对方确认</strong>
          {transfers.outgoing.filter((transfer) => transfer.status === 'pending').map((transfer) => (
            <p key={transfer.transferId} style={{ marginTop: 6 }}>{transfer.itemName} × {transfer.quantity} 等待 {transfer.toPlayerName} 接收</p>
          ))}
        </section>
      )}
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

      {activeSection === 'notes' && (
        <section className="bh-panel">
          <span className="bh-eyebrow">PRIVATE NOTES</span>
          <h3 style={{ marginBottom: 8 }}>我的笔记</h3>
          <p style={{ color: 'var(--bh-dim)', fontSize: 13 }}>
            私密笔记不会进入剧情、规则或世界状态。只有你能在这里查看原文。
          </p>
          {noteDraft && (
            <section className="bh-muted-box" style={{ marginTop: 12 }} aria-label={noteDraft.noteId ? '编辑私密笔记' : '新建私密笔记'}>
              <h4 style={{ margin: '0 0 10px' }}>{noteDraft.noteId ? '编辑私密笔记' : '新建私密笔记'}</h4>
              <label className="bh-field-label" htmlFor="private-note-title">标题</label>
              <input
                className="bh-input"
                id="private-note-title"
                value={noteDraft.title}
                maxLength={200}
                onChange={(event) => setNoteDraft({ ...noteDraft, title: event.target.value })}
              />
              <label className="bh-field-label" htmlFor="private-note-body" style={{ marginTop: 8 }}>内容</label>
              <textarea
                className="bh-textarea"
                id="private-note-body"
                value={noteDraft.body}
                rows={5}
                maxLength={20000}
                placeholder="仅自己可见的笔记内容"
                onChange={(event) => setNoteDraft({ ...noteDraft, body: event.target.value })}
              />
              {noteError && <p className="bh-error">{noteError}</p>}
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button className="bh-button bh-button--yellow" type="button" disabled={!noteDraft.title.trim() || !noteDraft.body.trim() || savingNote} onClick={() => void saveNote()}>
                  {savingNote ? '保存中...' : noteDraft.noteId ? '保存修改' : '保存私密笔记'}
                </button>
                <button className="bh-button" type="button" disabled={savingNote} onClick={() => setNoteDraft(null)}>取消</button>
              </div>
            </section>
          )}
          {notes.length === 0 ? (
            <p style={{ color: '#666', fontSize: 13 }}>暂无私密笔记</p>
          ) : (
            <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
              {notes.map((note) => (
                <article key={note.note_id} className="bh-muted-box">
                  <strong>{note.title}</strong>
                  <p style={{ whiteSpace: 'pre-wrap', margin: '8px 0 0' }}>{note.body}</p>
                  <button
                    className="bh-button"
                    type="button"
                    style={{ marginTop: 8 }}
                    onClick={() => {
                      setNoteError('');
                      setNoteDraft({ noteId: note.note_id, title: note.title, body: note.body });
                    }}
                  >
                    编辑
                  </button>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

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
              <button
                onClick={() => {
                  setTransferError('');
                  setTransferDraft({ item: selectedItem, toCharacterId: '', quantity: 1 });
                }}
                style={{ flex: 1, padding: 10, borderRadius: 8, border: 'none', background: '#ff9800', color: '#fff', fontSize: 14 }}
              >
                转交给队友
              </button>
            </div>
          </div>
        </div>
      )}

      {transferDraft && (
        <div
          onClick={() => setTransferDraft(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 110 }}
        >
          <section onClick={(event) => event.stopPropagation()} className="bh-panel" style={{ width: 'min(92vw, 480px)' }} aria-label="确认物品转交">
            <span className="bh-eyebrow">TRANSFER</span>
            <h3 className="bh-panel-title">转交 {transferDraft.item.name}</h3>
            <p>对方接收前，物品仍在你的背包中；不会自动进入公共叙事。</p>
            <label className="bh-field-label" htmlFor="transfer-recipient">接收调查员</label>
            <select id="transfer-recipient" className="bh-input" value={transferDraft.toCharacterId} onChange={(event) => setTransferDraft({ ...transferDraft, toCharacterId: event.target.value })}>
              <option value="">选择接收方</option>
              {transferCandidates.map((candidate) => <option key={candidate.characterId} value={candidate.characterId}>{candidate.playerName}</option>)}
            </select>
            <label className="bh-field-label" htmlFor="transfer-quantity" style={{ marginTop: 8 }}>数量</label>
            <input id="transfer-quantity" className="bh-input" type="number" min={1} max={transferDraft.item.quantity} value={transferDraft.quantity} onChange={(event) => setTransferDraft({ ...transferDraft, quantity: Number(event.target.value) || 0 })} />
            {transferDraft.item.is_secret && <p className="bh-error">私密物品只会告知接收方，不会向队伍公开。</p>}
            {transferError && <p className="bh-error">{transferError}</p>}
            <div className="bh-action-row bh-action-row--responsive" style={{ marginTop: 12 }}>
              <button className="bh-button bh-button--yellow" type="button" disabled={!transferDraft.toCharacterId || transferDraft.quantity < 1 || transferDraft.quantity > transferDraft.item.quantity} onClick={() => void requestTransfer()}>发起转交请求</button>
              <button className="bh-button" type="button" onClick={() => setTransferDraft(null)}>取消</button>
            </div>
          </section>
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
              {selectedClue.is_shared
                ? '已创建队伍摘要；你的原始线索仍私密'
                : selectedClue.is_private ? '私密线索' : '队伍线索'}
            </div>
            {selectedClue.is_owner && selectedClue.is_private && !selectedClue.is_shared && !shareDraft && (
              <button
                onClick={() => {
                  setShareError('');
                  setShareDraft({ clueId: selectedClue.id, summary: '' });
                }}
                style={{
                  marginTop: 12, width: '100%', padding: 10, borderRadius: 8,
                  border: 'none', background: '#ff9800', color: '#fff', fontSize: 14,
                }}
              >
                分享给队伍
              </button>
            )}
            {shareDraft?.clueId === selectedClue.id && (
              <section className="bh-muted-box" style={{ marginTop: 12 }} aria-label="确认线索分享">
                <strong>准备分享</strong>
                <p>只填写队伍应看到的摘要。原始线索、私人笔记、假说和判定依据不会自动公开。</p>
                <textarea
                  className="bh-textarea"
                  value={shareDraft.summary}
                  onChange={(event) => setShareDraft({ ...shareDraft, summary: event.target.value })}
                  placeholder="用自己的话写给队伍看的摘要"
                  rows={3}
                />
                {shareError && <p className="bh-error">{shareError}</p>}
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <button className="bh-button bh-button--yellow" type="button" disabled={!shareDraft.summary.trim()} onClick={() => void shareClue()}>确认分享</button>
                  <button className="bh-button" type="button" onClick={() => setShareDraft(null)}>取消</button>
                </div>
              </section>
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
