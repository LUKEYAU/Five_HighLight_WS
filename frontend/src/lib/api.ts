import { getIdToken, authHeader } from "./auth";

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

type CreateResp = { uploadId: string; key: string };
type SignResp = { url: string };
type CompleteResp = { ok: boolean; key: string };

export async function createMultipart(filename: string, contentType: string) {
  const r = await fetch(`${API_BASE}/uploads/multipart/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ filename, contentType }),
  });
  if (!r.ok) throw new Error(`create failed: ${r.status}`);
  return (await r.json()) as CreateResp;
}

export async function signPart(key: string, uploadId: string, partNumber: number) {
  const r = await fetch(`${API_BASE}/uploads/multipart/sign`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ key, uploadId, partNumber }),
  });
  if (!r.ok) throw new Error(`sign failed: ${r.status}`);
  return (await r.json()) as SignResp;
}

export async function completeMultipart(
  key: string,
  uploadId: string,
  parts: { etag: string; partNumber: number }[],
) {
  const r = await fetch(`${API_BASE}/uploads/multipart/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ key, uploadId, parts }),
  });
  if (!r.ok) throw new Error(`complete failed: ${r.status}`);
  return (await r.json()) as CompleteResp;
}

export type RecentItem = { key: string; size: number; lastModified?: string };
export type RecentResp = { items: RecentItem[] };

export async function listRecentUploads(limit = 20) {
  const t = getIdToken();
  if (!t) throw new Error("not signed in");
  const url = `${API_BASE}/uploads/recent?limit=${limit}&token=${encodeURIComponent(t)}`;
  // 不帶 Authorization，避免預檢
  const r = await fetch(url);
  if (!r.ok) throw new Error(`recent failed: ${r.status}`);
  return (await r.json()) as RecentResp;
}

export async function deleteUpload(key: string) {
  const r = await fetch(`${API_BASE}/uploads/${encodeURIComponent(key)}`, {
    method: "DELETE",
    headers: { ...authHeader() },
  });
  if (!r.ok && r.status !== 204) throw new Error(`delete failed: ${r.status}`);
}

// 建立剪輯任務
export async function createEdit(key: string, options: { superResolution?: boolean; fps60?: boolean }) {
  const r = await fetch(`${API_BASE}/edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ key, options }),
  });
  if (!r.ok) throw new Error(`create edit failed: ${r.status}`);
  return (await r.json()) as { jobId: string };
}

// 查詢剪輯任務
export type EditStatus = {
  id: string;
  status: "queued" | "started" | "finished" | "failed" | "deferred";
  outputKey?: string;
  error?: string;
  logs?: string[];
};
export async function getEdit(jobId: string) {
  const r = await fetch(`${API_BASE}/edits/${jobId}`, { headers: { ...authHeader() } });
  if (!r.ok) throw new Error(`get edit failed: ${r.status}`);
  return (await r.json()) as EditStatus;
}

export async function presignDownload(key: string, expires = 600) {
  const r = await fetch(`${API_BASE}/downloads/presign/${encodeURIComponent(key)}?expires=${expires}`, {
    headers: { ...authHeader() },
  });
  if (!r.ok) throw new Error(`presign failed: ${r.status}`);
  return (await r.json()) as { url: string };
}
