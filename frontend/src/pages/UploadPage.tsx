import { useCallback, useEffect, useRef, useState } from "react";
import { useMultipartUpload } from "../hooks/useMultipartUpload";
import { listRecentUploads, type RecentItem } from "../lib/api";
import { deleteUpload, presignDownload } from "../lib/api"; // ← 新增
import { isSignedIn, clearIdToken } from "../lib/auth";
import GoogleLogin from "../components/GoogleLogin";

export default function UploadPage() {
  const signedIn = isSignedIn();
  const { isUploading, progress, error, start, cancel } = useMultipartUpload();
  const inputRef = useRef<HTMLInputElement>(null);

  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [loadingRecent, setLoadingRecent] = useState(false);
  const [recentErr, setRecentErr] = useState<string | null>(null);
  const [deletingKey, setDeletingKey] = useState<string | null>(null); // ← 新增

  const refreshRecent = useCallback(async () => {
    setLoadingRecent(true);
    setRecentErr(null);
    try {
      const r = await listRecentUploads(50); // 多拿一點
      setRecent(r.items);
    } catch (e: any) {
      setRecentErr(e?.message ?? String(e));
    } finally {
      setLoadingRecent(false);
    }
  }, []);

  useEffect(() => { if (signedIn) refreshRecent(); }, [signedIn, refreshRecent]);

  const onFiles = useCallback(async (files: FileList | null) => {
    if (!files || !files[0]) return;
    const file = files[0];
    try {
      const { key } = await start(file);
      await refreshRecent();
      window.location.href = `/editor/${encodeURIComponent(key)}`;
    } catch {}
  }, [start, refreshRecent]);

  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    onFiles(e.dataTransfer.files);
  }, [onFiles]);

  const onDelete = useCallback(async (key: string) => {
    if (!confirm("確定要刪除這個上傳嗎？動作無法復原。")) return;
    try {
      setDeletingKey(key);
      await deleteUpload(key);
      await refreshRecent();
    } catch (e: any) {
      alert(e?.message ?? String(e));
    } finally {
      setDeletingKey(null);
    }
  }, [refreshRecent]);

  
  if (!signedIn) {
    return (
      <div className="page page-center">
        <div className="card">
          <h2>登入以開始上傳</h2>
          <p className="muted">使用 Google 帳戶登入後，你只會看到自己的上傳紀錄。</p>
          <GoogleLogin onSignedIn={() => window.location.reload()} />
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      {/* 頂部列 */}
      <header className="topbar">
        <h2 className="title">FootBall High Light</h2>
        <div className="actions">
          <button className="ghost" onClick={() => { clearIdToken(); window.location.reload(); }}>登出</button>
        </div>
      </header>

      {/* 主區域：左右分欄（左：上傳；右：列表） */}
      <main className="main two-col">
        {/* 左欄：上傳區 */}
        <section className="panel">
          <h3>新增上傳</h3>
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            className="dropzone"
          >
            拖拉 MP4 到這裡，或點擊選取
            <input
              ref={inputRef}
              type="file"
              accept="video/mp4,video/quicktime,video/x-matroska"
              style={{ display: "none" }}
              onChange={(e) => onFiles(e.target.files)}
            />
          </div>

          {isUploading && (
            <div className="progress">
              <div className="bar" style={{ width: `${(progress * 100).toFixed(1)}%` }} />
              <div className="meta">
                <span>上傳中… {(progress * 100).toFixed(1)}%</span>
                <button className="ghost" onClick={cancel}>取消</button>
              </div>
            </div>
          )}

          {error && <p className="error">錯誤：{error}</p>}
        </section>

        {/* 右欄：以往上傳（填滿、可滾動） */}
        <section className="panel fill">
          <div className="panel-head">
            <h3>以往上傳</h3>
            <div className="actions">
              <button className="ghost" onClick={refreshRecent} disabled={loadingRecent}>
                {loadingRecent ? "載入中…" : "重新整理"}
              </button>
              {recentErr && <span className="error">（{recentErr}）</span>}
            </div>
          </div>

          <div className="table-wrap">
            {recent.length === 0 ? (
              <p className="muted">尚無記錄</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>檔名</th>
                    <th>大小</th>
                    <th>時間</th>
                    <th style={{ width: 220 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((it) => {
                    const filename = it.key.split("/").pop() || it.key;
                    const when = it.lastModified ? new Date(it.lastModified) : null;
                    const busy = deletingKey === it.key;
                    return (
                      <tr key={it.key} className={busy ? "row-busy" : ""}>
                        <td><code title={it.key}>{filename}</code></td>
                        <td>{fmtBytes(it.size)}</td>
                        <td>{when ? when.toLocaleString() : "-"}</td>
                        <td style={{ ...td, textAlign: "right", display: "flex", gap: 8, justifyContent: "flex-end" }}>
                          {/* 精華空間（左） */}
                          <a
                            className="ghost btn"
                            href={`/highlights?key=${encodeURIComponent(it.key)}`}
                            aria-disabled={busy}
                            onClick={(e) => { if (busy) e.preventDefault(); }}
                          >精華空間</a>

                          {/* 打開編輯器（中） */}
                          <a
                            className="btn"
                            href={`/editor/${encodeURIComponent(it.key)}`}
                            aria-disabled={busy}
                            onClick={(e) => { if (busy) e.preventDefault(); }}
                          >打開編輯器</a>

                          {/* 下載（右） */}
                          <button
                            className="ghost"
                            disabled={busy}
                            onClick={async () => {
                              try {
                                const { url } = await presignDownload(it.key, 600);
                                window.open(url, "_blank");
                              } catch (e: any) {
                                alert(e?.message ?? String(e));
                              }
                            }}
                          >下載</button>

                          {/* 刪除（沿用） */}
                          <button className="danger" disabled={busy} onClick={() => onDelete(it.key)}>
                            {busy ? "刪除中…" : "刪除"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

const td: React.CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid #f2f2f2",
};

function fmtBytes(n: number) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}
