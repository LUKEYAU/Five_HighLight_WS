import { useParams } from "react-router-dom";
import { API_BASE } from "../lib/api";
import NLEPlayer from "../components/NLEPlayer";

export default function EditorPage() {
  const { key } = useParams();
  if (!key) return <div className="page-center"><div className="card">找不到影片 key</div></div>;
  const src = `${API_BASE}/videos/stream/${key}`;
  return (
    <div style={{ height: "100vh", display: "grid", gridTemplateRows: "auto 1fr", fontFamily: "system-ui, sans-serif" }}>
      <header className="topbar">
        <strong>編輯器</strong>
        <span className="muted" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{key}</span>
      </header>
      <NLEPlayer src={src} />
    </div>
  );
}
