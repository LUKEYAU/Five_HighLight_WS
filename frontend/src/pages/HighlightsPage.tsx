import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * 精華空間（初版）
 * - 右上可放全域操作（未來：生成精華、批次操作…）
 * - 左側固定捲動區顯示背號 1~99，每條可放置該背號精華（之後串資料）
 * - 若網址 query 帶 ?key=...，頂部會顯示「待分配影片」區塊，之後可拖曳到背號
 */
export default function HighlightsPage() {
  const [sp] = useSearchParams();
  const incomingKey = sp.get("key"); // 從上傳列表點「精華空間」帶進來

  // 假資料（之後改成呼叫 API 取每個背號的 clips）
  const jerseyNumbers = useMemo(() => Array.from({ length: 99 }, (_, i) => i + 1), []);
  const [filter, setFilter] = useState<string>("");

  useEffect(() => {
    // 之後：若 incomingKey 存在，向後端查影片基本資料顯示縮圖/長度
  }, [incomingKey]);

  const filtered = jerseyNumbers.filter(n => (filter ? String(n).includes(filter) : true));

  return (
    <div className="page" style={{ height: "100vh", gridTemplateRows: "auto 1fr" }}>
      <header className="topbar">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <strong>精華空間 待完善</strong>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="篩選背號…"
            style={{ background: "transparent", color: "var(--fg)", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 10px" }}
          />
        </div>
        <div className="actions">
          {/* 未來：一鍵導出所有精華、同步到雲、分享連結… */}
        </div>
      </header>

      {incomingKey && (
        <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface)", display: "flex", gap: 12, alignItems: "center" }}>
          <span className="muted">待分配影片：</span>
          <code style={{ maxWidth: "60vw", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{incomingKey}</code>
          <span className="muted">（之後可拖曳到對應背號）</span>
        </div>
      )}

      <main className="main" style={{ padding: 16, minHeight: 0, overflow: "auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
          {filtered.map((n) => (
            <section key={n} className="panel" style={{ padding: 12 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <strong># {n}</strong>
                {/* 未來：每個背號的分享/導出/設定 */}
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>尚無精華（之後顯示卡片列表）</div>
              {/* 未來：這裡放 Clip 卡片清單，可拖放排序 */}
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}
