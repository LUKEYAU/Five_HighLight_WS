import { useParams } from "react-router-dom";
import { API_BASE } from "../lib/api";
import NLEPlayer from "../components/NLEPlayer";
import { useEffect, useState } from "react";
import { createEdit, getEdit, type EditStatus } from "../lib/api";
import { isSignedIn, getIdToken } from "../lib/auth";
import GoogleLogin from "../components/GoogleLogin";

export default function EditorPage() {
  const { key } = useParams();
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
  const src = `${API_BASE}/videos/stream/${encodeURIComponent(key)}?token=${encodeURIComponent(token)}`;


  // 自動剪輯 UI 狀態
  const [showModal, setShowModal] = useState(false);
  const [optSR, setOptSR] = useState(true);   // 超解析
  const [optFPS, setOptFPS] = useState(true); // 30→60fps

  // 任務狀態
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<EditStatus | null>(null);

  // 輪詢任務狀態
  useEffect(() => {
    if (!jobId) return;
    let t: any;
    const tick = async () => {
      try {
        const s = await getEdit(jobId);
        setStatus(s);
        if (s.status === "finished" || s.status === "failed") return; // 停止輪詢
      } catch {}
      t = setTimeout(tick, 2000);
    };
    tick();
    return () => clearTimeout(t);
  }, [jobId]);

  const startAutoEdit = async () => {
    const { jobId } = await createEdit(key!, { superResolution: optSR, fps60: optFPS });
    setJobId(jobId);
    setStatus({ id: jobId, status: "queued" });
    setShowModal(false);
  };

  return (
    <div style={{ height: "100vh", display: "grid", gridTemplateRows: "auto auto 1fr" }}>
      {/* 頂部列（右上有自動剪輯） */}
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

      {/* 任務狀態列（可選） */}
      {status && (
        <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "var(--surface)", display: "flex", alignItems: "center", gap: 12 }}>
          <span>任務：{status.id}</span>
          <span>狀態：{pretty(status.status)}</span>
          {status.status === "finished" && status.outputKey && (
            <a className="btn" href={`/editor/${encodeURIComponent(status.outputKey)}`}>打開結果</a>
          )}
          {status.status === "failed" && <span className="error">失敗：{status.error || "unknown"}</span>}
        </div>
      )}

      {/* NLE 播放器 */}
      <NLEPlayer src={src} />

      {/* 自動剪輯選項 Modal */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>自動剪輯選項</h3>
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
