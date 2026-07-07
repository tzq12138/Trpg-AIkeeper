import { getSlotValue, setSlotValue } from './identity';

const BASE = '';

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}

export function getPlayerToken(): string {
  // Player token MUST come from the server (join/restore-session response).
  // NEVER generate a local UUID as player_token — self-made tokens are always rejected.
  // The local storage is a dev convenience only; production should use secure session storage.
  return getSlotValue('player_token') || '';
}

export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'X-Room-Token': getPlayerToken() };
  const accountToken = getSlotValue('account_token');
  if (accountToken) {
    headers['Authorization'] = `Bearer ${accountToken}`;
  }
  return headers;
}
