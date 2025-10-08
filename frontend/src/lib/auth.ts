export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string;

export function setIdToken(token: string) {
  localStorage.setItem("id_token", token);
}
export function getIdToken(): string | null {
  return localStorage.getItem("id_token");
}
export function clearIdToken() {
  localStorage.removeItem("id_token");
}

/** 一律回傳 Record<string,string>，避免聯合型別 */
export function authHeader(): Record<string, string> {
  const t = getIdToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** 建 headers 的工具：可加 Content-Type，並自動帶 Authorization */
export function buildHeaders(init?: Record<string, string>): HeadersInit {
  const h: Record<string, string> = { ...(init ?? {}) };
  const t = getIdToken();
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

export function isSignedIn() {
  return !!getIdToken();
}
