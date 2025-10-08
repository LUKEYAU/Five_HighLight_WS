import { useCallback, useEffect, useMemo, useRef, useState } from "react";

function cssVar(name: string, fallback: string){
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export default function NLEPlayer({ src }: { src: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setPlaying] = useState(false);

  const [zoom, setZoom] = useState(100); // px/s
  const [scrollX, setScrollX] = useState(0);
  const [dragging, setDragging] = useState<null | "playhead" | "scroll">(null);
  const [inPoint, setInPoint] = useState<number | null>(null);
  const [outPoint, setOutPoint] = useState<number | null>(null);

  const fpsRef = useRef(30);
  const rVFCId = useRef<number | null>(null);

  const viewW = 960;
  const viewH = 540;

  const tick = useMemo(() => {
    const pps = zoom;
    if (pps > 300) return 0.1;
    if (pps > 150) return 0.2;
    if (pps > 80) return 0.5;
    if (pps > 40) return 1;
    if (pps > 20) return 2;
    if (pps > 10) return 5;
    if (pps > 5) return 10;
    return 30;
  }, [zoom]);

  useEffect(() => {
    const v = videoRef.current!;
    v.crossOrigin = "anonymous";
    v.playsInline = true;
    v.preload = "auto";
    const onMeta = () => setDuration(v.duration || 0);
    const onTime = () => setCurrentTime(v.currentTime);
    v.addEventListener("loadedmetadata", onMeta);
    v.addEventListener("timeupdate", onTime);
    return () => {
      v.removeEventListener("loadedmetadata", onMeta);
      v.removeEventListener("timeupdate", onTime);
    };
  }, [src]);

  const drawFrame = useCallback(() => {
    const v = videoRef.current!, c = canvasRef.current!;
    const ctx = c.getContext("2d")!;
    // 背景
    ctx.fillStyle = cssVar("--viewer-bg", "#000");
    ctx.fillRect(0, 0, viewW, viewH);

    const videoAR = (v.videoWidth || 16) / (v.videoHeight || 9);
    const canvasAR = viewW / viewH;
    let dw = viewW, dh = viewH, dx = 0, dy = 0;
    if (videoAR > canvasAR) { dh = Math.round(viewW / videoAR); dy = Math.floor((viewH - dh) / 2); }
    else { dw = Math.round(viewH * videoAR); dx = Math.floor((viewW - dw) / 2); }
    try { ctx.drawImage(v, dx, dy, dw, dh); } catch {}
  }, []);

  const loop = useCallback((now: number, metadata: any) => {
    drawFrame();
    if (rVFCId.current !== null && (videoRef.current as any).requestVideoFrameCallback) {
      rVFCId.current = (videoRef.current as any).requestVideoFrameCallback(loop);
    }
    if (metadata?.presentedFrames > 5 && metadata?.mediaTime > 0) {
      const est = metadata.presentedFrames / metadata.mediaTime;
      if (est > 5 && est < 120) fpsRef.current = est;
    }
  }, [drawFrame]);

  useEffect(() => {
    const v = videoRef.current!;
    const onSeeked = () => drawFrame();
    v.addEventListener("seeked", onSeeked);
    if (isPlaying) {
      (videoRef.current as any).requestVideoFrameCallback &&
        (rVFCId.current = (videoRef.current as any).requestVideoFrameCallback(loop));
      v.play().catch(() => setPlaying(false));
    } else {
      if (rVFCId.current !== null && (videoRef.current as any).cancelVideoFrameCallback) {
        (videoRef.current as any).cancelVideoFrameCallback(rVFCId.current);
        rVFCId.current = null;
      }
      v.pause(); drawFrame();
    }
    return () => { v.removeEventListener("seeked", onSeeked); };
  }, [isPlaying, loop, drawFrame]);

  useEffect(() => { const t = setTimeout(drawFrame, 200); return () => clearTimeout(t); }, [drawFrame]);

  const togglePlay = () => setPlaying(p => !p);
  const stepBy = (frames: number) => {
    const fps = fpsRef.current || 30, dt = frames / fps;
    const v = videoRef.current!; setPlaying(false);
    v.currentTime = Math.max(0, Math.min(duration, v.currentTime + dt));
  };
  const setIn = () => setInPoint(currentTime);
  const setOut = () => setOutPoint(currentTime);

  const timelineWidth = Math.max(zoom * duration, 1);

  const onMouseDownTimeline = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.dataset.handle === "playhead") setDragging("playhead");
    else setDragging("scroll");
  };
  const onMouseMoveTimeline = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const el = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - el.left + scrollX;
    if (dragging === "playhead") {
      const t = Math.min(Math.max(0, x / zoom), duration || 0);
      const v = videoRef.current!; setPlaying(false);
      v.currentTime = t; setCurrentTime(t); drawFrame();
    } else if (dragging === "scroll") {
      const dx = -e.movementX;
      setScrollX(s => Math.max(0, Math.min(timelineWidth - el.width + 40, s + dx)));
    }
  };
  const onMouseUpTimeline = () => setDragging(null);

  const onWheelTimeline = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
    const pointerX = e.clientX - rect.left + scrollX;
    const pointerT = pointerX / zoom;
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const newZoom = Math.min(800, Math.max(10, zoom * factor));
    const newScrollX = Math.max(0, pointerT * newZoom - (pointerX - scrollX));
    setZoom(newZoom); setScrollX(newScrollX);
  };

  const rulerRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = rulerRef.current!, ctx = c.getContext("2d")!;
    const W = c.width = (c.parentElement?.clientWidth || 0), H = c.height = 28;
    // 背景與刻度色來自 CSS 變數
    ctx.fillStyle = cssVar("--ruler-bg", "#0c1320"); ctx.fillRect(0,0,W,H);
    ctx.strokeStyle = cssVar("--border", "#243244"); ctx.beginPath(); ctx.moveTo(0,H-0.5); ctx.lineTo(W,H-0.5); ctx.stroke();
    if (!duration) return;
    const startT = scrollX / zoom, endT = startT + W / zoom;
    const tick = pickTick(zoom);
    ctx.fillStyle = cssVar("--ruler-tick", "#475569");
    for (let t = Math.floor(startT/tick)*tick; t <= endT; t += tick) {
      const x = Math.round((t - startT) * zoom);
      const major = Math.abs((t / (tick*5)) - Math.round(t/(tick*5))) < 1e-6;
      const h = major ? 16 : 10;
      ctx.fillRect(x, H - h, 1, h);
      if (major) {
        ctx.fillStyle = cssVar("--muted", "#9ca3af");
        const label = secToTime(t);
        ctx.fillText(label, x + 4, 14);
        ctx.fillStyle = cssVar("--ruler-tick", "#475569");
      }
    }
  }, [duration, zoom, scrollX]);

  function pickTick(z:number){
    if (z > 300) return 0.1; if (z > 150) return 0.2; if (z > 80) return 0.5;
    if (z > 40) return 1; if (z > 20) return 2; if (z > 10) return 5; if (z > 5) return 10; return 30;
  }

  const playheadX = Math.round(currentTime * zoom - scrollX);

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto auto 1fr", height: "100%" }}>
      {/* 控制列 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
        <button onClick={togglePlay}>{isPlaying ? "⏸ 暫停" : "▶ 播放"}</button>
        <button onClick={() => stepBy(-1)}>◀ 逐格</button>
        <button onClick={() => stepBy(+1)}>逐格 ▶</button>
        <button onClick={setIn}>標記 In</button>
        <button onClick={setOut}>標記 Out</button>
        <span style={{ marginLeft: 12, fontVariantNumeric: "tabular-nums", color: "var(--fg)" }}>{secToTime(currentTime)} / {secToTime(duration)}</span>
        <span style={{ marginLeft: "auto", color: "var(--muted)" }}>Zoom: {Math.round(zoom)} px/s</span>
      </div>

      {/* 畫面窗 */}
      <div className="viewer" style={{ display: "grid", placeItems: "center", padding: 8 }}>
        <canvas ref={canvasRef} width={viewW} height={viewH} style={{ borderRadius: 8, background: "transparent", width: viewW, height: viewH }} />
        <video ref={videoRef} src={src} style={{ display: "none" }} />
      </div>

      {/* 時間尺 + 軌道 */}
      <div
        onMouseDown={onMouseDownTimeline}
        onMouseMove={onMouseMoveTimeline}
        onMouseUp={onMouseUpTimeline}
        onMouseLeave={onMouseUpTimeline}
        onWheel={onWheelTimeline}
        style={{ userSelect: "none", position: "relative", overflow: "hidden", borderTop: "1px solid var(--border)" }}
      >
        {/* 尺 */}
        <canvas ref={rulerRef} className="timeline-ruler" style={{ width: "100%", height: 28, display: "block" }} />

        {/* 軌道區 */}
        <div className="timeline-track" style={{ position: "relative", height: 80 }}>
          {inPoint !== null && outPoint !== null && outPoint > inPoint && (
            <div
              className="selection"
              style={{
                position: "absolute",
                left: inPoint * zoom - scrollX,
                width: (outPoint - inPoint) * zoom,
                top: 0, bottom: 0,
                borderRadius: 4
              }}
              title={`選取：${secToTime(inPoint)} ~ ${secToTime(outPoint)}`}
            />
          )}
          {/* playhead */}
          <div
            data-handle="playhead"
            className="playhead"
            style={{ position: "absolute", left: playheadX, top: 0, bottom: 0, width: 2, cursor: "ew-resize" }}
            title="拖曳可 scrub"
          />
        </div>

        {/* 底部捲動條 */}
        <div className="scrollbar-rail" style={{ height: 10, position: "relative" }}>
          <div
            className="scrollbar-thumb"
            style={{
              position: "absolute",
              left: (scrollX / Math.max(zoom * (duration||0), 1)) * 100 + "%",
              width: Math.min(100, (((rulerRef.current?.clientWidth || 1)) / Math.max(zoom * (duration||0), 1)) * 100) + "%",
              top: 0, bottom: 0, borderRadius: 8
            }}
          />
        </div>
      </div>
    </div>
  );
}

function secToTime(t: number) {
  t = Math.max(0, t);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  const ms = Math.floor((t * 1000) % 1000);
  const pad = (n: number, w=2) => n.toString().padStart(w, "0");
  return (h ? pad(h) + ":" : "") + pad(m) + ":" + pad(s) + "." + ms.toString().padStart(3, "0");
}
