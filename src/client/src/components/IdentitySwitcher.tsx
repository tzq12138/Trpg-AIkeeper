import { useState, useEffect, useCallback } from 'react';
import {
  getSlots, getActiveSlotId, getActiveSlot, setActiveSlot,
  createSlot, deleteSlot, IdentitySlot,
} from '../shared/identity';

interface Props {
  /** If true, show only the current identity badge (compact mode). */
  compact?: boolean;
}

export default function IdentitySwitcher({ compact = false }: Props) {
  const [slots, setSlots] = useState<IdentitySlot[]>([]);
  const [activeId, setActiveId] = useState('');
  const [open, setOpen] = useState(false);
  const [newLabel, setNewLabel] = useState('');

  const refresh = useCallback(() => {
    setSlots(getSlots());
    setActiveId(getActiveSlotId());
  }, []);

  useEffect(() => {
    refresh();
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refresh]);

  const activeSlot = slots.find((s) => s.id === activeId);

  const handleSwitch = (slotId: string) => {
    setActiveSlot(slotId);
    refresh();
    setOpen(false);
    window.location.reload();
  };

  const handleCreate = () => {
    if (!newLabel.trim()) return;
    const slot = createSlot(newLabel.trim());
    setActiveSlot(slot.id);
    refresh();
    setNewLabel('');
    setOpen(false);
    // Clear current tokens for new identity
    ['account_token', 'account', 'owner_token', 'player_token'].forEach((k) => localStorage.removeItem(k));
    window.location.href = '/login';
  };

  const handleDelete = (slotId: string) => {
    deleteSlot(slotId);
    refresh();
  };

  if (compact) {
    return (
      <span style={{ fontSize: 11, padding: '2px 6px', border: '1px solid var(--bh-black)', background: 'var(--bh-yellow)' }}>
        {activeSlot?.label || activeSlot?.account?.username || '未选择身份'}
      </span>
    );
  }

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button
        className="bh-button"
        style={{ fontSize: 11, padding: '4px 8px' }}
        onClick={() => setOpen(!open)}
        type="button"
      >
        {activeSlot
          ? `${activeSlot.account?.role === 'admin' ? '👑' : activeSlot.account?.role === 'host' ? '🎭' : '👤'} ${activeSlot.label || activeSlot.account?.username || '身份'}`
          : '未选择身份'}
        {' ▾'}
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, zIndex: 1000,
          background: 'var(--bh-paper)', border: '2px solid var(--bh-black)',
          padding: 12, minWidth: 220, boxShadow: '4px 4px 0 var(--bh-black)',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 8, fontSize: 13 }}>身份槽</div>

          {slots.length === 0 && (
            <p style={{ fontSize: 11, color: 'var(--bh-dim)', marginBottom: 8 }}>
              暂无身份。创建第一个身份槽开始使用。
            </p>
          )}

          {slots.map((slot) => (
            <div
              key={slot.id}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '4px 6px', marginBottom: 4,
                border: slot.id === activeId ? '2px solid var(--bh-black)' : '1px solid var(--bh-black)',
                background: slot.id === activeId ? 'var(--bh-yellow)' : 'var(--bh-paper)',
                fontSize: 12,
              }}
            >
              <button
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  fontFamily: 'inherit', fontSize: 12, textAlign: 'left', flex: 1,
                  fontWeight: slot.id === activeId ? 700 : 400,
                }}
                onClick={() => handleSwitch(slot.id)}
                type="button"
              >
                {slot.account?.role === 'admin' ? '👑 ' : slot.account?.role === 'host' ? '🎭 ' : '👤 '}
                {slot.label}
                {slot.account ? ` (${slot.account.username})` : ''}
                {slot.id === activeId ? ' ◀' : ''}
              </button>
              <button
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--bh-red)', fontSize: 14, padding: '0 4px',
                }}
                onClick={() => handleDelete(slot.id)}
                type="button"
                title="删除身份槽"
              >
                ✕
              </button>
            </div>
          ))}

          <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
            <input
              style={{
                flex: 1, padding: '4px 6px', fontSize: 12,
                border: '1px solid var(--bh-black)', fontFamily: 'inherit',
              }}
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="新身份名称..."
            />
            <button
              className="bh-button bh-button--yellow"
              style={{ fontSize: 11, padding: '4px 8px' }}
              onClick={handleCreate}
              type="button"
            >
              + 添加
            </button>
          </div>
          <p style={{ fontSize: 10, color: 'var(--bh-dim)', marginTop: 6 }}>
            每个标签页独立切换。添加后需重新登录。
          </p>
        </div>
      )}
    </div>
  );
}
