import { useParams, useSearchParams } from "react-router-dom";
import { API_BASE, presignDownload, getEdit, createEdit, type EditStatus } from "../lib/api";
import NLEPlayer from "../components/NLEPlayer";
import { useEffect, useMemo, useState } from "react";
import { isSignedIn, getIdToken } from "../lib/auth";
import GoogleLogin from "../components/GoogleLogin";
import { cancelEdit } from "../lib/api";

type EditStatusEx = EditStatus & {
  jsonKey?: string;
  detectMp4Key?: string;
};

export default function EditorPage() {
  const { key } = useParams();
  const [search, setSearch] = useSearchParams();
  const storageKeyJob = `editor:lastJobId:${key}`;
  const storageKeyLogs = `editor:showLogs:${key}`;

  if (!key) {
    return (
      <div className="page-center">
        <div className="card">找不到影片 key</div>
      </div>
    );
  }

  if (!isSignedIn()) {
    return (
      <div className="page-center">
        <div className="card">
          <h3>請先登入以檢視影片</h3>
          <GoogleLogin onSignedIn={() => window.location.reload()} />
        </div>
      </div>
    );
  }

  const token = getIdToken()!;
  const src = useMemo(
    () => `${API_BASE}/videos/stream/${encodeURIComponent(key)}?token=${encodeURIComponent(token)}`,
    [key, token]
  );

  // 自動剪輯 UI 狀態
  const [showModal, setShowModal] = useState(false);
  const [optDetect, setOptDetect] = useState(true); // 新增：YOLO 偵測
  const [optSR, setOptSR] = useState(true);         // 超解析
  const [optFPS, setOptFPS] = useState(true);       // 30→60fps

  // 任務狀態
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<EditStatusEx | null>(null);
  const [showLogs, setShowLogs] = useState(
    () => (localStorage.getItem(storageKeyLogs) ?? "0") === "1"
  );
  
  useEffect(() => {
    localStorage.setItem(storageKeyLogs, showLogs ? "1" : "0");
  }, [showLogs, storageKeyLogs]);

  useEffect(() => {
    const byQuery = search.get("job");
    const byStore = localStorage.getItem(storageKeyJob);
    const pick = byQuery || byStore;
    if (pick && !jobId) {
      setJobId(pick);
      setStatus({ id: pick, status: "queued" });
    }
  }, [jobId, search, storageKeyJob]);

  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let delay = 1200;

    const tick = async () => {
      if (stopped) return;
      try {
        const s = (await getEdit(jobId)) as EditStatusEx;
        setStatus(s);
        if (s.status === "finished" || s.status === "failed") return; // 停止輪詢
        delay = Math.min(6000, Math.round(delay * 1.4));
      } catch {
        delay = Math.min(6000, Math.round(delay * 1.6));
      }
      setTimeout(tick, delay);
    };

    tick();
    return () => {
      stopped = true;
    };
  }, [jobId]);

  const startAutoEdit = async () => {
    const { jobId } = await createEdit(key!, {
      superResolution: optSR,
      fps60: optFPS,
      // @ts-expect-error
      detect: optDetect,
    });
    setJobId(jobId);
    setStatus({ id: jobId, status: "queued" });
    setShowModal(false);
    search.set("job", jobId);
    setSearch(search, { replace: true });
    localStorage.setItem(storageKeyJob, jobId);
  };

const clearJob = async () => {
  try {
    if (jobId) {
      await cancelEdit(jobId);
    }
  } catch (e) {
    console.warn("cancel failed:", e);
  } finally {
    setJobId(null);
    setStatus(null);
    search.delete("job");
    setSearch(search, { replace: true });
    localStorage.removeItem(storageKeyJob);
  }
};
  
  const openResultInNewEditor = (k: string) => {
    window.location.href = `/editor/${encodeURIComponent(k)}`;
  };

  const downloadByPresign = async (k: string) => {
    const { url } = await presignDownload(k, 10 * 60);
    window.open(url, "_blank");
  };

  return (
    <div style={{ height: "100vh", display: "grid", gridTemplateRows: "auto auto 1fr" }}>
      {/* 頂部列 */}
      <header className="topbar">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <strong>編輯器</strong>
          <span className="muted" style={{ maxWidth: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {key}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button id="auto-edit-btn" onClick={() => setShowModal(true)}>自動剪輯</button>
        </div>
      </header>

      {/* 任務狀態列 */}
      {(jobId || status) && (
        <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "var(--surface)", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span>任務：{status?.id || jobId}</span>
          <span>狀態：{pretty(status?.status || "queued")}</span>

          {status?.status === "finished" && status.outputKey && (
            <>
              <button className="btn" onClick={() => openResultInNewEditor(status.outputKey!)}>打開結果</button>
              <button className="btn" onClick={() => downloadByPresign(status.outputKey!)}>下載結果</button>
            </>
          )}

          {status?.status === "failed" && <span className="error">失敗：{status.error || "unknown"}</span>}

          <button className="ghost" onClick={() => setShowLogs(v => !v)}>{showLogs ? "隱藏紀錄" : "顯示紀錄"}</button>
          <button className="ghost" onClick={clearJob}>清除任務</button>

          {showLogs && (
            <pre style={{ maxHeight: 160, overflow: "auto", margin: 0, padding: "6px 10px", background: "var(--sunken)", borderRadius: 6, width: "100%" }}>
              {(status?.logs || []).join("\n")}
            </pre>
          )}
        </div>
      )}

      {/* 播放器 */}
      <NLEPlayer src={src} />

      {/* 自動剪輯選項 Modal */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>自動剪輯選項</h3>

            <label className="row">
              <input type="checkbox" checked={optDetect} onChange={e => setOptDetect(e.target.checked)} />
              <span>強化偵測(推薦)</span>
            </label>

            <label className="row">
              <input type="checkbox" checked={optSR} onChange={e => setOptSR(e.target.checked)} />
              <span>超解析（Super Resolution）</span>
            </label>

            <label className="row">
              <input type="checkbox" checked={optFPS} onChange={e => setOptFPS(e.target.checked)} />
              <span>30fps 擴幀至 60fps</span>
            </label>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
              <button className="ghost" onClick={() => setShowModal(false)}>取消</button>
              <button onClick={startAutoEdit}>確認開始</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function pretty(s: EditStatus["status"]) {
  switch (s) {
    case "queued": return "排隊中";
    case "started": return "處理中";
    case "finished": return "已完成";
    case "failed": return "失敗";
    case "deferred": return "延後";
  }
}
