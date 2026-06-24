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
  let token = localStorage.getItem('player_token');
  if (!token) {
    token = crypto.randomUUID();
    localStorage.setItem('player_token', token);
  }
  return token;
}

export function authHeaders(): Record<string, string> {
  return { 'X-Room-Token': getPlayerToken() };
}
