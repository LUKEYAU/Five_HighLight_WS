import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { isSignedIn, getIdToken } from "../lib/auth";
import GoogleLogin from "../components/GoogleLogin";
import { listHighlightJobs, listHighlightsByJersey, type HighlightGroup } from "../lib/api";
import { API_BASE } from "../lib/api";

export default function HighlightsPage() {
  const [sp, setSp] = useSearchParams();
  const incomingKey = sp.get("key");
  const qJob = sp.get("job") || "";

  if (!isSignedIn()) {
    return (
      <div className="page-center">
        <div className="card">
          <h3>請先登入以檢視精華</h3>
          <GoogleLogin onSignedIn={() => window.location.reload()} />
        </div>
      </div>
    );
  }

  const [jobs, setJobs] = useState<{ jobId: string; lastModified?: string; count: number }[]>([]);
  const [jobId, setJobId] = useState<string>("");
  const [groups, setGroups] = useState<HighlightGroup[] | null>(null); // null = loading, [] = loaded empty
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [loadingGroups, setLoadingGroups] = useState(false);

  const [filter, setFilter] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await listHighlightJobs();
        if (!alive) return;
        setJobs(r.items || []);
        const pick = qJob && r.items.some(x => x.jobId === qJob) ? qJob : (r.items[0]?.jobId ?? "");
        setJobId(pick);
        if (pick && (!qJob || qJob !== pick)) {
          sp.set("job", pick);
          setSp(sp, { replace: true });
        }
      } catch {
        if (!alive) return;
        setJobs([]);
        setJobId("");
      } finally {
        if (alive) setLoadingJobs(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    setGroups(null);
    if (!jobId) { setGroups([]); return; }

    let alive = true;
    setLoadingGroups(true);
    (async () => {
      try {
        const r = await listHighlightsByJersey(jobId, false);
        if (!alive) return;
        setGroups(r.groups || []);
      } catch {
        if (!alive) return;
        setGroups([]);
      } finally {
        if (alive) setLoadingGroups(false);
      }
    })();
    return () => { alive = false; };
  }, [jobId]);

  const clipsByNumber = useMemo(() => {
    const m = new Map<number, HighlightGroup["clips"]>();
    (groups || []).forEach(g => {
      const n = parseInt(g.jersey, 10);
      if (!Number.isFinite(n)) return; // skip unknown
      const arr = m.get(n) || [];
      arr.push(...g.clips);
      m.set(n, arr);
    });
    return m;
  }, [groups]);

  const availableNumbers = useMemo(() => {
    const nums = Array.from(clipsByNumber.keys()).sort((a, b) => a - b);
    return filter ? nums.filter(n => String(n).includes(filter)) : nums;
  }, [clipsByNumber, filter]);

  const token = getIdToken()!;
  const streamUrl = (k: string) =>
    `${API_BASE}/videos/stream/${encodeURIComponent(k)}?token=${encodeURIComponent(token)}`;

  const isLoading = loadingJobs || loadingGroups || groups === null;

  return (
    <div className="page" style={{ height: "100vh", gridTemplateRows: "auto auto 1fr" }}>
      <header className="topbar">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <strong>精華空間</strong>
          <select
            value={jobId}
            onChange={(e) => {
              const v = e.target.value;
              setJobId(v);
              if (v) { sp.set("job", v); setSp(sp, { replace: true }); }
            }}
            style={{ background: "transparent", color: "var(--fg)", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 8px" }}
          >
            {jobs.map(j => (
              <option key={j.jobId} value={j.jobId}>
                {j.jobId} {j.lastModified ? ` / ${new Date(j.lastModified).toLocaleString()}` : ""} ({j.count})
              </option>
            ))}
          </select>

          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="篩選背號…"
            style={{ background: "transparent", color: "var(--fg)", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 10px" }}
          />
        </div>
        <div className="actions">{isLoading && <span className="muted">載入中…</span>}</div>
      </header>

      {incomingKey && (
        <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface)", display: "flex", gap: 12, alignItems: "center" }}>
          <span className="muted">待分配影片：</span>
          <code style={{ maxWidth: "60vw", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{incomingKey}</code>
          <span className="muted">（之後可拖曳到對應背號）</span>
        </div>
      )}

      <main className="main" style={{ padding: 16, minHeight: 0, overflow: "auto" }}>
        {isLoading ? (
          <div className="muted" style={{ padding: 24 }}>載入中…</div>
        ) : availableNumbers.length === 0 ? (
          <div className="muted" style={{ padding: 24 }}>目前沒有可顯示的精華片段。</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
            {availableNumbers.map((n) => {
              const clips = clipsByNumber.get(n) || [];
              return (
                <section key={n} className="panel" style={{ padding: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <strong># {n}</strong>
                    <span className="muted" style={{ fontSize: 12 }}>{clips.length} 段</span>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8, marginTop: 8 }}>
                    {clips.map((c, i) => (
                      <div key={i} style={{ display: "flex", flexDirection: "column", gap: 6, border: "1px solid var(--border)", borderRadius: 8, padding: 8 }}>
                        <video
                          src={streamUrl(c.key)}
                          style={{ width: "100%", borderRadius: 6 }}
                          controls
                          preload="metadata"
                        />
                        <div className="muted" style={{ fontSize: 12, display: "flex", justifyContent: "space-between" }}>
                          <span title={c.key} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "70%" }}>
                            {c.key.split("/").slice(-1)[0]}
                          </span>
                          <span>{(c.size / 1024 / 1024).toFixed(1)} MB</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
