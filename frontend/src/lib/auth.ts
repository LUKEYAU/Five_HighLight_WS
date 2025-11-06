export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string;

const TOKEN_KEYS = ["fivecut:id_token", "google_id_token", "id_token"] as const;

export function setIdToken(token: string) {
  for (const k of TOKEN_KEYS) localStorage.setItem(k, token);
}

export function getIdToken(): string | null {
  for (const k of TOKEN_KEYS) {
    const v = localStorage.getItem(k);
    if (v) return v;
  }
  return null;
}

export function clearIdToken() {
  for (const k of TOKEN_KEYS) localStorage.removeItem(k);
}

export function isSignedIn() {
  return !!getIdToken();
}

export function authHeader(): Record<string, string> {
  const t = getIdToken();
  return t ? { Authorization: `Bearer ${t}`, "X-Id-Token": t } : {};
}

export function buildHeaders(init?: Record<string, string>): HeadersInit {
  const h: Record<string, string> = { ...(init ?? {}) };
  const t = getIdToken();
  if (t) {
    h.Authorization = `Bearer ${t}`;
    h["X-Id-Token"] = t;
  }
  return h;
}

export function withQueryToken(pathOrUrl: string): string {
  const t = getIdToken();
  if (!t) return pathOrUrl;
  const u = new URL(pathOrUrl, window.location.origin);
  if (!u.searchParams.get("token")) u.searchParams.set("token", t);
  return u.pathname + u.search;
}
