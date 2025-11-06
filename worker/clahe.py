#clahe.py PROC_VIDEO_PATH的來源
import os, json, cv2, numpy as np
from typing import Dict, List, Tuple, Optional
from tqdm import tqdm

VIDEO_PATH   = r"C:\Users\yauka\OneDrive\桌面\PYfile\All_Data\Project_root\data\video17s.mp4"
TRACKING_JSON = r"C:\Users\yauka\OneDrive\桌面\PYfile\All_Data\Project_root\data\video17s.json"
OUTPUT_DIR   = r"C:\Users\yauka\OneDrive\桌面\PYfile\All_Data\firmRoot\tools"
os.makedirs(OUTPUT_DIR, exist_ok=True)

PERSON_SCORE_THR = 0.35     # 人框分數門檻（保留 >= 此分數）
OVERLAP_SKIP_IOU = 0.60     # ROI 兩兩 IoU > 這個值就跳過（避免重複處理）
ADAPTIVE_TILES   = True     # 依 ROI 大小自動調整 tileGridSize（不影響顏色，只影響對比細緻度）
MIN_TILE, MAX_TILE = 2, 4  # 自適應 tiles 的範圍
TILE_PER_PX      = 64       # min(w,h)/這個值 ≈ tiles

def clamp_int(v: float, lo: int, hi: int) -> int:
    return int(v if v >= lo else lo) if v <= hi else int(hi)

def torso_roi_from_bbox(
    bbox_xyxy: Tuple[float, float, float, float], frame_w: int, frame_h: int
) -> Optional[Tuple[int, int, int, int]]:
    x1f, y1f, x2f, y2f = bbox_xyxy
    x1 = clamp_int(x1f, 0, frame_w - 1)
    y1 = clamp_int(y1f, 0, frame_h - 1)
    x2 = clamp_int(x2f, 0, frame_w - 1)
    y2 = clamp_int(y2f, 0, frame_h - 1)
    if x2 <= x1 or y2 <= y1:
        return None
    w = x2 - x1
    h = y2 - y1
    if w <= 1 or h <= 1:
        return None
    return (x1, y1, w, h)

def iou_xywh(a: Tuple[int,int,int,int], b: Tuple[int,int,int,int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    inter_w = max(0, min(ax2, bx2) - max(ax, bx))
    inter_h = max(0, min(ay2, by2) - max(ay, by))
    inter = inter_w * inter_h
    if inter == 0:
        return 0.0
    area_a, area_b = aw * ah, bw * bh
    return inter / float(area_a + area_b - inter)

class RoiClaheApplier:
    def __init__(self, clip: float = 2.0, tiles: int = 2):
        self._clip  = clip
        self._tiles = tiles
        self.clahe  = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tiles, tiles))
        self._ycrcb = None
        self._roi_shape = None

    def _ensure_tiles(self, tiles: int):
        if tiles != self._tiles:
            self._tiles = tiles
            self.clahe = cv2.createCLAHE(clipLimit=self._clip, tileGridSize=(tiles, tiles))

    def apply_inplace(self, img: np.ndarray, roi_xywh: Tuple[int, int, int, int], adaptive: bool = ADAPTIVE_TILES) -> None:
        x, y, w, h = roi_xywh
        if w <= 0 or h <= 0:
            return
        H, W = img.shape[:2]
        if x >= W or y >= H:
            return
        w = min(w, W - x)
        h = min(h, H - y)
        if w <= 1 or h <= 1:
            return

        if adaptive:
            tiles = int(max(MIN_TILE, min(MAX_TILE, round(min(w, h) / TILE_PER_PX))))
            self._ensure_tiles(max(MIN_TILE, tiles))

        roi = img[y:y + h, x:x + w]
        if self._roi_shape != roi.shape:
            self._ycrcb = np.empty_like(roi)  # (h,w,3) uint8
            self._roi_shape = roi.shape

        cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb, dst=self._ycrcb)
        y_ch, cr, cb = cv2.split(self._ycrcb)
        y_eq = self.clahe.apply(y_ch)
        cv2.merge((y_eq, cr, cb), dst=self._ycrcb)
        cv2.cvtColor(self._ycrcb, cv2.COLOR_YCrCb2BGR, dst=roi)

def load_tracking(tracking_json_path: str) -> Dict[str, dict]:
    if not os.path.exists(tracking_json_path):
        print(f"[警告] 找不到 TRACKING_JSON：{tracking_json_path}")
        return {}
    try:
        with open(tracking_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        print("[警告] TRACKING_JSON 不是 dict 格式，已忽略。")
        return {}
    except Exception as e:
        print(f"[警告] 讀取 TRACKING_JSON 失敗：{e}")
        return {}

def export_video_roi_clahe_from_json(
    video_path: str,
    tracking_json_path: str,
    effect_name: str = "CLAHE_JSON_ROI",
) -> None:
    tracking_data = load_tracking(tracking_json_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("[錯誤] 無法開啟影片！"); return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    out_path = os.path.join(OUTPUT_DIR, f"{effect_name}.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps, (W, H))
    if not writer.isOpened():
        print("[錯誤] 無法建立輸出檔案！"); cap.release(); return

    roi_clahe = RoiClaheApplier()
    pbar = tqdm(total=total if total > 0 else None, desc=f"{effect_name}", unit="f")

    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            rec = tracking_data.get(str(frame_idx), {})
            persons_raw = rec.get("person", []) or []

            # 轉換 + 分數門檻
            persons_xyxy = []
            for item in persons_raw:
                if not (isinstance(item, list) and len(item) >= 3):
                    continue
                (x1y1, x2y2, sc) = item[:3]
                if not (isinstance(x1y1, (list, tuple)) and isinstance(x2y2, (list, tuple)) and len(x1y1) >= 2 and len(x2y2) >= 2):
                    continue
                sc = float(sc)
                if sc < PERSON_SCORE_THR:
                    continue
                x1, y1 = float(x1y1[0]), float(x1y1[1])
                x2, y2 = float(x2y2[0]), float(x2y2[1])
                persons_xyxy.append((x1, y1, x2, y2, sc))

            rois: List[Tuple[int,int,int,int]] = []
            candidates: List[Tuple[int,int,int,int,float]] = []
            for (x1, y1, x2, y2, sc) in persons_xyxy:
                roi = torso_roi_from_bbox((x1, y1, x2, y2), W, H)
                if roi is not None:
                    x, y, w, h = roi
                    candidates.append((x, y, w, h, sc))

            candidates.sort(key=lambda r: r[2]*r[3], reverse=True)

            selected: List[Tuple[int,int,int,int]] = []
            for (x, y, w, h, sc) in candidates:
                cur = (x, y, w, h)
                if any(iou_xywh(cur, prev) > OVERLAP_SKIP_IOU for prev in selected):
                    continue
                selected.append(cur)

            for roi in selected:
                roi_clahe.apply_inplace(frame, roi, adaptive=ADAPTIVE_TILES)

            writer.write(frame)
            frame_idx += 1
            pbar.update(1)
    finally:
        pbar.close()
        writer.release()
        cap.release()

    print(f"{effect_name} 輸出完成：{out_path}")

# ========= 主程式 =========
if __name__ == "__main__":
    export_video_roi_clahe_from_json(
        video_path=VIDEO_PATH,
        tracking_json_path=TRACKING_JSON,
        effect_name="CLAHE_JSON_ROI",
    )
