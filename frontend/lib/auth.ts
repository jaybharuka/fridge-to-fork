// Swiggy connection state + the bearer used on the direct-to-Render /api calls.
//
// The OAuth session cookie is host-only on the Vercel origin (/auth/* is
// proxied same-origin), so the browser never sends it to the Render origin
// that /api/scan and /api/order hit directly. Instead we fetch a signed
// bearer from the same-origin /auth/session-token on load and send it as an
// Authorization header. It lives in memory only: the cookie is the
// persistent store, so a reload just re-fetches it (nothing to leak from
// storage). Swiggy issues no refresh token — an expired/rejected token means
// re-running the Connect flow, never a silent retry.

export interface AuthState {
  status: 'loading' | 'connected' | 'disconnected';
  token: string | null;
  expiresAt: string | null;
}

const LOADING: AuthState = { status: 'loading', token: null, expiresAt: null };
const DISCONNECTED: AuthState = { status: 'disconnected', token: null, expiresAt: null };

let state: AuthState = LOADING;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function setState(next: AuthState) {
  state = next;
  listeners.forEach(l => l());
}

export const getAuthState = () => state;
export const getServerAuthState = () => LOADING;
export function subscribeAuth(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function isExpired(expiresAt: string | null) {
  return !!expiresAt && Date.parse(expiresAt) <= Date.now();
}

// One shared request: the header chip, the order button and the fetch
// helpers all await the same promise, so nothing races the first check.
export function loadAuth(): Promise<void> {
  inflight ??= fetch('/auth/session-token', { cache: 'no-store' })
    .then(r => (r.ok ? r.json() : null))
    .then(body => {
      const connected = body?.authenticated && body.token && !isExpired(body.expires_at);
      setState(connected ? { status: 'connected', token: body.token, expiresAt: body.expires_at } : DISCONNECTED);
    })
    .catch(() => setState(DISCONNECTED));
  return inflight;
}

export function markDisconnected() {
  inflight = Promise.resolve();
  setState(DISCONNECTED);
}

export async function authHeaders(): Promise<Record<string, string>> {
  await loadAuth();
  if (state.status === 'connected' && isExpired(state.expiresAt)) markDisconnected();
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}
