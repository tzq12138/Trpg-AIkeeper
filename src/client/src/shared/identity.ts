/** Multi-identity slot system for single-machine multi-account testing.

 * Each identity slot stores a separate set of tokens (account, owner, player).
 * The active slot is tracked per browser tab via sessionStorage.
 * All slots persist in localStorage under 'aikeeper_slots'.
 */

const SLOTS_KEY = 'aikeeper_slots';
const ACTIVE_SLOT_KEY = 'aikeeper_active_slot';
const LEGACY_KEYS = ['account_token', 'account', 'owner_token', 'player_token'];

export interface AccountInfo {
  account_id: string;
  username: string;
  display_name?: string;
  role: string;
}

export interface IdentitySlot {
  id: string;
  label: string;
  accountToken?: string;
  account?: AccountInfo;
  ownerToken?: string;
  playerToken?: string;
}

function loadSlots(): IdentitySlot[] {
  try {
    const raw = localStorage.getItem(SLOTS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveSlots(slots: IdentitySlot[]): void {
  localStorage.setItem(SLOTS_KEY, JSON.stringify(slots));
}

export function getSlots(): IdentitySlot[] {
  return loadSlots();
}

export function getActiveSlotId(): string {
  return sessionStorage.getItem(ACTIVE_SLOT_KEY) || '';
}

export function getActiveSlot(): IdentitySlot | undefined {
  const id = getActiveSlotId();
  if (!id) return undefined;
  return loadSlots().find((s) => s.id === id);
}

export function setActiveSlot(slotId: string): void {
  sessionStorage.setItem(ACTIVE_SLOT_KEY, slotId);
  // Sync slot tokens to legacy localStorage for backward compat
  const slots = loadSlots();
  const slot = slots.find((s) => s.id === slotId);
  if (slot) {
    if (slot.accountToken) localStorage.setItem('account_token', slot.accountToken);
    else localStorage.removeItem('account_token');
    if (slot.account) localStorage.setItem('account', JSON.stringify(slot.account));
    else localStorage.removeItem('account');
    if (slot.ownerToken) localStorage.setItem('owner_token', slot.ownerToken);
    else localStorage.removeItem('owner_token');
    if (slot.playerToken) localStorage.setItem('player_token', slot.playerToken);
    else localStorage.removeItem('player_token');
  }
}

export function getSlotValue(key: string): string | null {
  // Read from active slot if available, fall back to localStorage
  const slot = getActiveSlot();
  if (slot) {
    if (key === 'account_token') return slot.accountToken || null;
    if (key === 'owner_token') return slot.ownerToken || null;
    if (key === 'player_token') return slot.playerToken || null;
    if (key === 'account') return slot.account ? JSON.stringify(slot.account) : null;
  }
  return localStorage.getItem(key);
}

export function setSlotValue(key: string, value: string): void {
  const slot = getActiveSlot();
  if (slot) {
    if (key === 'account_token') slot.accountToken = value;
    else if (key === 'owner_token') slot.ownerToken = value;
    else if (key === 'player_token') slot.playerToken = value;
    else if (key === 'account') {
      try { slot.account = JSON.parse(value); } catch { slot.account = undefined; }
    }
    const slots = loadSlots();
    const idx = slots.findIndex((s) => s.id === slot.id);
    if (idx >= 0) slots[idx] = slot;
    saveSlots(slots);
    // Also update legacy localStorage
    localStorage.setItem(key, value);
  } else {
    localStorage.setItem(key, value);
  }
}

export function createSlot(label: string): IdentitySlot {
  const slot: IdentitySlot = {
    id: 'slot_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    label,
  };
  const slots = loadSlots();
  slots.push(slot);
  saveSlots(slots);
  return slot;
}

export function deleteSlot(slotId: string): void {
  let slots = loadSlots();
  const wasActive = getActiveSlotId() === slotId;
  slots = slots.filter((s) => s.id !== slotId);
  saveSlots(slots);
  if (wasActive) {
    sessionStorage.removeItem(ACTIVE_SLOT_KEY);
    LEGACY_KEYS.forEach((k) => localStorage.removeItem(k));
  }
}

export function migrateFromLegacy(): boolean {
  /** Migrate existing localStorage tokens into a default identity slot. */
  const existingSlots = loadSlots();
  if (existingSlots.length > 0) return false; // Already has slots

  const accountToken = localStorage.getItem('account_token');
  const accountRaw = localStorage.getItem('account');
  const ownerToken = localStorage.getItem('owner_token');
  const playerToken = localStorage.getItem('player_token');

  if (!accountToken && !ownerToken && !playerToken) return false;

  let account: AccountInfo | undefined;
  if (accountRaw) {
    try { account = JSON.parse(accountRaw); } catch { /* ignore */ }
  }

  const slot: IdentitySlot = {
    id: 'slot_default',
    label: account?.username || '默认身份',
    accountToken: accountToken || undefined,
    account,
    ownerToken: ownerToken || undefined,
    playerToken: playerToken || undefined,
  };

  saveSlots([slot]);
  setActiveSlot(slot.id);
  return true;
}

/** Initialize: migrate legacy tokens on first load. */
migrateFromLegacy();
