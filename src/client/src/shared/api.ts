import { getSlotValue, setSlotValue } from './identity';

const BASE = '';

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detailMessage: string | null;

  constructor(status: number, code: string | null, detailMessage: string | null) {
    // Never stringify an object into the visible message: structured FastAPI
    // detail ({code, reason}) is surfaced as fields, and anything else falls
    // back to a stable text — no "[object Object]" in player-facing copy.
    const message = code
      ? `API error ${status}: ${code}${detailMessage ? ` — ${detailMessage}` : ''}`
      : `API error ${status}${detailMessage ? ` — ${detailMessage}` : ''}`;
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = code;
    this.detailMessage = detailMessage;
  }
}

function parseErrorDetail(body: unknown): { code: string | null; detailMessage: string | null } {
  if (body && typeof body === 'object') {
    const detail = (body as { detail?: unknown }).detail;
    if (detail && typeof detail === 'object') {
      const structured = detail as { code?: unknown; reason?: unknown };
      return {
        code: typeof structured.code === 'string' ? structured.code : null,
        detailMessage: typeof structured.reason === 'string' ? structured.reason : null,
      };
    }
    if (typeof detail === 'string') return { code: null, detailMessage: detail };
  }
  return { code: null, detailMessage: null };
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!res.ok) {
    let code: string | null = null;
    let detailMessage: string | null = null;
    try {
      const body: unknown = await res.json();
      ({ code, detailMessage } = parseErrorDetail(body));
    } catch {
      // Non-JSON error body: keep the plain status message.
    }
    throw new ApiRequestError(res.status, code, detailMessage);
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
