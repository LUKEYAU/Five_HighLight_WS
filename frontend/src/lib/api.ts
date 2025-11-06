import { getIdToken, authHeader } from "./auth";

const API = (import.meta.env.VITE_API_BASE || "/api").replace(/\/+$/, "");

export const API_BASE = API;
type CreateResp = { uploadId: string; key: string };
type SignResp = { url: string };
type CompleteResp = { ok: boolean; key: string };

async function fetchJSON<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const r = await fetch(input, init);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { msg += ` - ${await r.text()}`; } catch {}
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export async function createMultipart(filename: string, contentType: string) {
  return fetchJSON<CreateResp>(`${API}/uploads/multipart/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ filename, contentType }),
  });
}

export async function signPart(key: string, uploadId: string, partNumber: number) {
  return fetchJSON<SignResp>(`${API}/uploads/multipart/sign`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ key, uploadId, partNumber }),
  });
}

export async function completeMultipart(
  key: string,
  uploadId: string,
  parts: { etag: string; partNumber: number }[],
) {
  return fetchJSON<CompleteResp>(`${API}/uploads/multipart/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ key, uploadId, parts }),
  });
}

export type RecentItem = { key: string; size: number; lastModified?: string };
export type RecentResp = { items: RecentItem[] };

export async function listRecentUploads(limit = 20) {
  const t = getIdToken();
  if (!t) throw new Error("not signed in");
  const url = `${API}/uploads/recent?limit=${limit}&token=${encodeURIComponent(t)}`;
  return fetchJSON<RecentResp>(url); // 不帶 Authorization，避免預檢
}

export async function deleteUpload(key: string) {
  const safe = encodeURI(key); // 保留斜線
  const r = await fetch(`${API}/uploads/${safe}`, {
    method: "DELETE",
    headers: { ...authHeader() },
  });
  if (!(r.ok || r.status === 204)) {
    let msg = `HTTP ${r.status}`;
    try { msg += ` - ${await r.text()}`; } catch {}
    throw new Error(msg);
  }
}

export async function createEdit(key: string, options: { superResolution?: boolean; fps60?: boolean }) {
  return fetchJSON<{ jobId: string }>(`${API}/edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ key, options }),
  });
}

export type EditStatus = {
  id: string;
  status: "queued" | "started" | "finished" | "failed" | "deferred";
  outputKey?: string;
  error?: string;
  logs?: string[];
};
export async function getEdit(jobId: string) {
  return fetchJSON<EditStatus>(`${API}/edits/${jobId}`, {
    headers: { ...authHeader() },
  });
}

export async function presignDownload(key: string, expires = 600) {
  return fetchJSON<{ url: string }>(
    `${API}/downloads/presign/${encodeURI(key)}?expires=${expires}`,
    { headers: { ...authHeader() } }
  );
}

export async function getMe() {
  const r = await fetch(`${API}/me`, { headers: { ...authHeader() } });
  if (!r.ok) throw new Error(`me failed: ${r.status}`);
  return r.json() as Promise<{ sub: string; email: string; name: string; isAdmin: boolean }>;
}

export type AdminRecentResp = { items: RecentItem[]; isTruncated?: boolean; nextCt?: string };

export async function listAllUploads(limit = 100, ownerSub?: string, ct?: string) {
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (ownerSub) qs.set("ownerSub", ownerSub);
  if (ct) qs.set("ct", ct);
  const r = await fetch(`${API}/admin/uploads/recent?${qs.toString()}`, {
    headers: { ...authHeader() }, 
  });
  if (!r.ok) throw new Error(`admin recent failed: ${r.status}`);
  return (await r.json()) as AdminRecentResp;
}

export function streamUrlForKey(key: string) {
  ///api/videos/stream/{key}
  return `${API}/videos/stream/${encodeURI(key)}`;
}

export async function cancelEdit(jobId: string) {
  const r = await fetch(`${API}/edits/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
    headers: { ...authHeader() },
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { msg += ` - ${await r.text()}`; } catch {}
    throw new Error(msg);
  }
  return r.json() as Promise<{ ok: boolean; canceled: boolean; already_started: boolean }>;
}

// === Highlights ===
export async function listHighlightJobs() {
  return fetchJSON<{ items: { jobId: string; lastModified?: string; count: number }[] }>(`${API}/highlights/jobs`, {
    headers: { ...authHeader() },
  });
}
export type HighlightClip = { key: string; size: number; lastModified?: string; url?: string };
export type HighlightGroup = { jerseyTeam: string; jersey: string; color: string; clips: HighlightClip[] };
export async function listHighlightsByJersey(jobId: string, presign = false) {
  const url = `${API}/highlights/by-jersey?jobId=${encodeURIComponent(jobId)}&presign=${presign ? "true" : "false"}`;
  return fetchJSON<{ groups: HighlightGroup[] }>(url, { headers: { ...authHeader() } });
}
