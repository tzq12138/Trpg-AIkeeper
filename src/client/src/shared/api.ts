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
  let token = getSlotValue('player_token');
  if (!token) {
    token = crypto.randomUUID();
    setSlotValue('player_token', token);
  }
  return token;
}

export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'X-Room-Token': getPlayerToken() };
  const accountToken = getSlotValue('account_token');
  if (accountToken) {
    headers['Authorization'] = `Bearer ${accountToken}`;
  }
  return headers;
}
