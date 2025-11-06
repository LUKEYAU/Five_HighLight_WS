# worker/jobs.py
import os, uuid, tempfile, shutil, signal, time, threading, queue, textwrap, subprocess
from pathlib import Path
from typing import Optional
import json
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from rq import get_current_job

# 環境變數(可用.env 覆蓋)
S3_ENDPOINT     = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_REGION       = os.getenv("S3_REGION", "us-east-1")

DETECT_PY_PATH  = os.getenv("DETECT_PY_PATH", "/app/yolo_dt/detect.py")
YOLO_WEIGHTS    = os.getenv("YOLO_WEIGHTS",   "/models/yolo_dt/ob_game.pt")
YOLO_IMGSZ      = int(os.getenv("YOLO_IMGSZ", "1280"))
YOLO_CONF       = float(os.getenv("YOLO_CONF","0.06"))
ENABLE_DETECT   = os.getenv("ENABLE_DETECT", "1") == "1"

CLAHE_PY_PATH   = os.getenv("CLAHE_PY_PATH", "/app/clahe.py")
ENABLE_CLAHE    = os.getenv("ENABLE_CLAHE", "1") == "1"

FIRMROOT_DIR    = os.getenv("FIRMROOT_DIR", "/app/firmRoot")
FFMPEG_BIN      = os.getenv("FFMPEG_BIN", "ffmpeg")   # worker 映像需可呼叫

REAL_ESRGAN_DIR = os.getenv("REAL_ESRGAN_DIR", "/app/Real-ESRGAN")
RE_SR_MODEL     = os.getenv("RE_SR_MODEL", "RealESRGAN_x4plus")
RE_SR_OUTSCALE  = float(os.getenv("RE_SR_OUTSCALE", "2"))
RE_SR_TILES     = int(os.getenv("RE_SR_TILES", "0"))
RE_SR_HALF      = os.getenv("RE_SR_HALF", "1") == "1"    

# Job 工具
def _job():
    return get_current_job()

def _log(msg: str):
    j = _job()
    if j:
        meta = j.meta or {}
        logs = meta.get("logs", [])
        logs.append(msg)
        meta["logs"] = logs[-200:]
        j.meta = meta
        j.save_meta()
    print(msg, flush=True)

def _set_meta(**kwargs):
    j = _job()
    if j:
        meta = j.meta or {}
        meta.update(kwargs)
        j.meta = meta
        j.save_meta()

def _should_abort() -> bool:
    j = _job()
    if not j:
        return False
    m = j.meta or {}
    return bool(m.get("abort") or m.get("cancel_requested") or m.get("canceled"))

def _mark_canceled():
    j = _job()
    if not j:
        return
    m = j.meta or {}
    if not m.get("error"):
        m["error"] = "canceled by user"
    m["canceled"] = True
    j.meta = m
    j.save_meta()

def _abort_checkpoint():
    if _should_abort():
        _mark_canceled()
        raise RuntimeError("canceled by user")

def _run_realesrgan_video(input_mp4: Path, workdir: Path, *,
                          model: str, outscale: float, tiles: int = 0, half: bool = True,
                          target_fps: Optional[int] = None) -> Optional[Path]:

    script = Path(REAL_ESRGAN_DIR) / "inference_realesrgan_video.py"
    if not script.exists():
        _log(f"[sr] Real-ESRGAN script not found: {script}")
        return None

    sr_dir = workdir / "sr"
    sr_dir.mkdir(parents=True, exist_ok=True)
    tmp_out = sr_dir / "sr_raw.mp4"
    final_out = sr_dir / "sr_out.mp4"

    cmd = [
        "python", str(script),
        "-n", model,
        "-i", str(input_mp4),
        "-o", str(tmp_out),
        "--outscale", str(outscale),
    ]
    # tilesize：Real-ESRGAN 的參數叫 --tile，0 表示整張
    if tiles and tiles > 0:
        cmd += ["--tile", str(tiles)]
    if half:
        cmd += ["--fp16"]

    _log(f"[sr] run: {' '.join(cmd)}")
    rc = _run_cancellable(cmd, cwd=str(REAL_ESRGAN_DIR), log_prefix="[sr] ")
    if rc != 0:
        if _should_abort():
            _log("[sr] canceled by user")
        else:
            _log(f"[sr] failed with code {rc}")
        return None

    if target_fps:
        _abort_checkpoint()
        ff = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
              "-i", str(tmp_out),
              "-r", str(target_fps),
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
              "-c:a", "copy",
              str(final_out)]
        _log(f"[sr] ffmpeg set fps: {' '.join(ff)}")
        rc2 = _run_cancellable(ff, cwd=str(sr_dir), log_prefix="[sr/ffmpeg] ")
        if rc2 != 0:
            _log("[sr] ffmpeg fps adjust failed; use raw SR output")
            final_out = tmp_out
    else:
        final_out = tmp_out

    return final_out if final_out.exists() else None

#  S3 工具
def _s3(access_key: str, secret_key: str, region: str):
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

def _ensure_bucket(s3, bucket: str):
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = (e.response or {}).get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            s3.create_bucket(Bucket=bucket)
            _log(f"[init] created bucket {bucket}")
        else:
            _log(f"[init] head_bucket failed: {e}")
            raise

def _upload(s3, bucket: str, key: str, local: Path, content_type: Optional[str] = None):
    args = {"ContentType": content_type} if content_type else {}
    _log(f"[upload] {local} → s3://{bucket}/{key}")
    try:
        s3.upload_file(str(local), bucket, key, ExtraArgs=args)
    except ClientError as e:
        _log(f"[upload:error] {e.response.get('Error', {})}")
        raise

def _guess_ct(p: Path) -> str:
    suf = p.suffix.lower()
    if suf in (".mp4", ".m4v", ".mov", ".avi", ".mkv"): return "video/mp4"
    if suf == ".json": return "application/json"
    if suf in (".txt", ".log", ".csv"): return "text/plain"
    return "application/octet-stream"

def _pick_first(p: Path, pattern: str) -> Optional[Path]:
    arr = sorted(p.glob(pattern))
    return arr[0] if arr else None

# 取消子行程
def _run_cancellable(cmd: list[str], cwd: Optional[str] = None, log_prefix: str = "",
                     soft_kill_timeout: float = 8.0, poll_interval: float = 0.5) -> int:
    preexec = os.setsid if hasattr(os, "setsid") else None  # Linux: 建立新 process group
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        preexec_fn=preexec,
    )
    j = _job()
    if j:
        m = j.meta or {}
        m["child_pid"] = proc.pid
        j.meta = m
        j.save_meta()

    q: "queue.Queue[str]" = queue.Queue()

    def _reader():
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                q.put(line.rstrip("\n"))
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    last_flush = time.time()
    buf: list[str] = []

    def _flush():
        nonlocal buf, last_flush
        if not buf:
            return
        j2 = _job()
        if j2:
            meta = j2.meta or {}
            logs = meta.get("logs", [])
            for ln in buf:
                logs.append(f"{log_prefix}{ln}" if log_prefix else ln)
            meta["logs"] = logs[-200:]
            j2.meta = meta
            j2.save_meta()
        buf = []
        last_flush = time.time()

    try:
        while True:
            # drain output
            try:
                while True:
                    ln = q.get_nowait()
                    buf.append(ln)
            except queue.Empty:
                pass

            if time.time() - last_flush > 0.5:
                _flush()

            rc = proc.poll()
            if rc is not None:
                _flush()
                return rc

            if _should_abort():
                _flush()
                try:
                    if preexec is not None:
                        os.killpg(proc.pid, signal.SIGTERM)
                    else:
                        proc.terminate()
                except Exception:
                    pass

                t_end = time.time() + soft_kill_timeout
                while time.time() < t_end:
                    rc2 = proc.poll()
                    if rc2 is not None:
                        _mark_canceled()
                        _flush()
                        return rc2
                    time.sleep(poll_interval)

                try:
                    if preexec is not None:
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                except Exception:
                    pass

                _mark_canceled()
                _flush()
                return -9

            time.sleep(poll_interval)
    finally:
        try:
            _flush()
        except Exception:
            pass

def _ffprobe_has_audio(path: Path) -> bool:
    try:
        rc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "json", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False
        )
        j = json.loads(rc.stdout or "{}")
        streams = j.get("streams") or []
        return len(streams) > 0
    except Exception:
        return False

def _fixup_mp4(input_path: Path, output_path: Path) -> bool:
    """把任何 mp4 轉成 h264+yuv420p / aac+faststart；可取消"""
    has_audio = _ffprobe_has_audio(input_path)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(output_path)]
    _log(f"[fix] run: {' '.join(cmd)}")
    rc = _run_cancellable(cmd, cwd=None, log_prefix="[fix] ")
    return rc == 0

def _ensure_cv2_friendly(input_path: Path, workdir: Path) -> Path:
    """若 OpenCV 打不開，先轉一份 H.264+yuv420p 的 mp4 再回傳那份。"""
    import cv2, subprocess
    cap = cv2.VideoCapture(str(input_path))
    if cap.isOpened():
        cap.release()
        return input_path
    cap.release()

    out_fix = workdir / "input_cv2.mp4"
    cmd = [
        "ffmpeg","-y","-hide_banner","-loglevel","error",
        "-i", str(input_path),
        "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
        "-movflags","+faststart",
        "-c:a","aac","-b:a","128k",
        str(out_fix),
    ]
    _log(f"[pre-fix] run: {' '.join(cmd)}")
    rc = subprocess.run(cmd).returncode
    if rc != 0 or not out_fix.exists():
        raise RuntimeError("pre-fix ffmpeg failed")
    _log("[pre-fix] produced cv2-friendly mp4")
    return out_fix

# YOLO 偵測
def _run_detect(input_mp4: Path, workdir: Path, options: dict) -> tuple[Optional[Path], Optional[Path]]:
    if not (ENABLE_DETECT and options.get("detect", True)):
        _log("[detect] skipped (disabled)")
        return (None, None)

    det_py = Path(DETECT_PY_PATH)
    if not det_py.exists():
        _log(f"[detect] skipped: detect.py not found at {det_py}")
        return (None, None)
    if not Path(YOLO_WEIGHTS).exists():
        _log(f"[detect] skipped: weights not found at {YOLO_WEIGHTS}")
        return (None, None)

    out_root = workdir / "runs" / "detect"
    run_name = "fivecut"
    cmd = [
        "python", str(det_py),
        "--weights", str(YOLO_WEIGHTS),
        "--img-size", str(YOLO_IMGSZ),
        "--source", str(input_mp4),
        "--conf-thres", str(YOLO_CONF),
        "--project", str(out_root),   # 修正：輸出在 workdir/runs/detect/
        "--name", run_name,
        "--exist-ok",
        "--save-json",
        "--save-txt",
    ]
    if options.get("augment"): cmd.append("--augment")
    if options.get("nosave"):  cmd.append("--nosave")

    _log(f"[detect] run: {' '.join(cmd)} (cwd={det_py.parent})")
    rc = _run_cancellable(cmd, cwd=str(det_py.parent), log_prefix="[detect] ")
    if rc != 0:
        if _should_abort():
            _log("[detect] canceled by user")
        else:
            _log(f"[detect] failed with code {rc}")
        return (None, None)

    run_path = out_root / run_name
    det_json = _pick_first(run_path, "*.json") or _pick_first(run_path, "*.JSON")
    det_mp4  = _pick_first(run_path, "*.mp4")
    if not det_json:
        _log(f"[detect] no json produced under {run_path}")
    else:
        _log(f"[detect] json = {det_json}")
    if not det_mp4:
        _log(f"[detect] no annotated mp4 produced under {run_path}")
    else:
        _log(f"[detect] mp4  = {det_mp4}")
    return (det_mp4, det_json)

#  CLAHE
def _run_clahe(input_mp4: Path, tracking_json: Path, workdir: Path, effect_name: str = "WB_CLAHE_JSON_ROI") -> Optional[Path]:
    if not ENABLE_CLAHE:
        _log("[clahe] skipped (disabled)")
        return None
    if not Path(CLAHE_PY_PATH).exists():
        _log(f"[clahe] skipped: clahe.py not found at {CLAHE_PY_PATH}")
        return None
    try:
        _abort_checkpoint()
        import importlib.util
        spec = importlib.util.spec_from_file_location("clahe_mod", CLAHE_PY_PATH)
        if spec is None or spec.loader is None:
            _log("[clahe] cannot import clahe.py")
            return None
        clahe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(clahe)  # type: ignore

        out_dir = workdir / "tools"
        out_dir.mkdir(parents=True, exist_ok=True)
        setattr(clahe, "OUTPUT_DIR", str(out_dir))

        _log(f"[clahe] export_video_roi_clahe_from_json -> {effect_name}")
        clahe.export_video_roi_clahe_from_json(
            video_path=str(input_mp4),
            tracking_json_path=str(tracking_json),
            effect_name=effect_name,
        )
        out_mp4 = out_dir / f"{effect_name}.mp4"
        _abort_checkpoint()
        return out_mp4 if out_mp4.exists() else None
    except Exception as e:
        if _should_abort():
            _log("[clahe] canceled by user")
        else:
            _log(f"[clahe] exception: {e}")
        return None

# firmRoot
def _write_firmroot_config(dst_config: Path, *,
                           raw_video: Path,
                           proc_video: Path,
                           tracking_json: Path,
                           out_video: Path,
                           highlights_dir: Path,
                           logs_dir: Path,
                           ffmpeg_path: str = FFMPEG_BIN,
                           model_path: Optional[str] = None):
    raw_s   = raw_video.as_posix()
    proc_s  = proc_video.as_posix()
    json_s  = tracking_json.as_posix()
    out_s   = out_video.as_posix()
    high_s  = highlights_dir.as_posix()
    logs_s  = logs_dir.as_posix()
    ffm_s   = ffmpeg_path
    model_s = (model_path or "").replace("\\", "/") 

    code = f"""
import os, cv2, numpy as np
from datetime import datetime

RAW_VIDEO_PATH  = {json.dumps(raw_s)}
PROC_VIDEO_PATH = {json.dumps(proc_s)}
TRACKING_JSON   = {json.dumps(json_s)}
OUTPUT_VIDEO    = {json.dumps(out_s)}
HIGHLIGHT_DIR   = {json.dumps(high_s)}
LOG_DIR         = {json.dumps(logs_s)}
FFMPEG_PATH     = {json.dumps(ffm_s)}
MODEL_PATH      = {json.dumps(model_s)}

os.makedirs(HIGHLIGHT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

PERSON_THRESHOLD = 0.3
BALL_THRESHOLD   = 0.45
CONFIRMATION_FRAMES = 5
MIN_CONFIRM_COUNT   = 3
MERGE_WINDOW = 15
CONTACT_MIN_SEC = 0.25
GOAL_MIN_SEC    = 0.25

TEST_START_FRAME = 0
TEST_MAX_FRAMES  = None

from datetime import datetime
JERSEY_CSV = os.path.join(LOG_DIR, datetime.now().strftime("jersey_log_%Y%m%d_%H%M%S.csv"))
JERSEY_STATS_TXT = os.path.join(LOG_DIR, "jersey_stats.txt")

def _bgr_to_lab1(bgr):
    arr = np.uint8([[bgr]])
    lab = cv2.cvtColor(arr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return lab[0,0,:]
def color_distance_lab(bgr1, bgr2):
    def _is_black(bgr): return bgr[0] < 50 and bgr[1] < 50 and bgr[2] < 50
    def _is_white(bgr): return bgr[0] > 220 and bgr[1] > 220 and bgr[2] > 220
    if (_is_black(bgr1) and _is_black(bgr2)) or (_is_white(bgr1) and _is_white(bgr2)): return 0.0
    lab1 = _bgr_to_lab1(bgr1); lab2 = _bgr_to_lab1(bgr2)
    return float(np.linalg.norm(lab1 - lab2))
"""
    dst_config.write_text(textwrap.dedent(code), encoding="utf-8")

def _run_firmroot_pipeline(src_video: Path, tracking_json: Path, workdir: Path,
                           model_path: Optional[str] = None,  proc_video_override: Optional[Path] = None):
    fr_src = Path(FIRMROOT_DIR)
    if not fr_src.exists():
        _log(f"[firmRoot] not found at {fr_src}")
        return (None, None, None)

    fr_dir = workdir / "firmRoot"
    try:
        shutil.copytree(fr_src, fr_dir, dirs_exist_ok=True)
    except Exception as e:
        _log(f"[firmRoot] copy failed: {e}")
        return (None, None, None)

    out_root    = workdir / "firmRoot_out"
    out_video   = out_root / "lam_output.mp4"
    highlights  = out_root / "highlights"
    logs_dir    = out_root / "logs"
    out_root.mkdir(parents=True, exist_ok=True)

    safe_src   = _ensure_cv2_friendly(src_video, workdir)
    proc_video = proc_video_override or safe_src
    _write_firmroot_config(
        fr_dir / "config.py",
        raw_video=src_video,
        proc_video=proc_video,
        tracking_json=tracking_json,
        out_video=out_video,
        highlights_dir=highlights,
        logs_dir=logs_dir,
        ffmpeg_path=FFMPEG_BIN,
        model_path=model_path,
    )

    _abort_checkpoint()
    _log("[firmRoot] run app.py")
    rc = _run_cancellable(["python", "-u", "app.py"], cwd=str(fr_dir), log_prefix="[firmRoot] ")
    if rc != 0:
        if _should_abort():
            _log("[firmRoot] canceled by user")
        else:
            _log(f"[firmRoot] app.py exit {rc}")
        return (None, None, None)
    try:
        tree = "\n".join(str(p) for p in (workdir/"firmRoot_out").rglob("*"))[:4000]
        _log("[firmRoot] out tree:\n" + tree)
    except Exception:
        pass
    ok_video = out_video if out_video.exists() else None
    ok_high  = highlights if highlights.exists() else None
    ok_logs  = logs_dir if logs_dir.exists() else None
    _abort_checkpoint()
    return (ok_video, ok_high, ok_logs)

# 任務入口
def run_auto_edit(
    s3_endpoint: str,
    s3_region: str,
    access_key: str,
    secret_key: str,
    bucket_videos: str,
    bucket_exports: str,
    source_key: str,
    user_sub: str,
    options: dict,
):

    s3 = _s3(access_key, secret_key, s3_region)
    _ensure_bucket(s3, bucket_videos)
    _ensure_bucket(s3, bucket_exports)

    j = _job()
    job_id = j.get_id() if j else uuid.uuid4().hex
    base_prefix = f"users/{user_sub}/exports/{job_id}"

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        src = tdir / "input.mp4"

        _log(f"[download] s3://{bucket_videos}/{source_key}")
        s3.download_file(bucket_videos, source_key, str(src))

        _abort_checkpoint()

        # 1) YOLO 偵測
        det_mp4, det_json = _run_detect(src, tdir, options or {})
        json_key = None
        det_key  = None
        if det_json:
            json_key = f"{base_prefix}/detect.json"
            _upload(s3, bucket_exports, json_key, det_json, content_type="application/json")
            _set_meta(jsonKey=json_key)
        if det_mp4:
            det_key = f"{base_prefix}/detect_annotated.mp4"
            _upload(s3, bucket_exports, det_key, det_mp4, content_type="video/mp4")
            _set_meta(detectMp4Key=det_key)

        _abort_checkpoint()
        
        analysis_video = src
        # 2) CLAHE（需要 JSON）
        final_local: Optional[Path] = None
        if det_json:
            clahe_mp4 = _run_clahe(src, det_json, tdir, effect_name="WB_CLAHE_JSON_ROI")
            if clahe_mp4 and clahe_mp4.exists():
                final_local = clahe_mp4
                analysis_video = clahe_mp4
                _log("[pipeline] use CLAHE result as candidate final")

        _abort_checkpoint()

        # 3) firmRoot（需要 JSON；優先當作最終輸出）
        if det_json:
            fr_out, fr_high_dir, fr_logs_dir = _run_firmroot_pipeline(src, det_json, tdir, model_path="/models/firmRoot/best.pt", proc_video_override=analysis_video)
            if fr_out and fr_out.exists():
                final_local = fr_out
                _log("[pipeline] use firmRoot OUTPUT_VIDEO as final output")

                fr_prefix = f"{base_prefix}/firmRoot"
                if fr_high_dir and fr_high_dir.exists():
                    by_jersey_dir = fr_high_dir / "by_jersey"
                    if by_jersey_dir.exists():
                        for team_dir in by_jersey_dir.iterdir():
                            if not team_dir.is_dir():
                                continue
                            jersey_team = team_dir.name  # e.g., "12_RED" or "unknown_WHITE"
                            jersey = jersey_team.split("_", 1)[0]
                            try:
                                if jersey.lower() != "unknown" and int(jersey) > 50:
                                    continue
                            except Exception:
                                continue

                            merged_mp4 = team_dir / f"{jersey_team}.mp4"
                            if not merged_mp4.exists():
                                continue

                            upload_src = merged_mp4
                            if bool(options.get("superResolution", False)):
                                sr_scale = float(options.get("superResolutionScale", RE_SR_OUTSCALE))
                                _abort_checkpoint()
                                _log(f"[pipeline] SR (highlights) x{sr_scale} → {jersey_team}.mp4")
                                sr_out = _run_realesrgan_video(
                                    merged_mp4, workdir=tdir,
                                    model=RE_SR_MODEL, outscale=sr_scale, tiles=RE_SR_TILES, half=RE_SR_HALF,
                                    target_fps=None  # 精華片段不改 fps；需要的話可設 60
                                )
                                if sr_out and sr_out.exists():
                                    upload_src = sr_out
                                    _log("[pipeline] SR ok; use SR output for upload")
                                else:
                                    _log("[pipeline] SR skipped/failed; upload original merged clip")

                            rel = (team_dir / f"{jersey_team}.mp4").relative_to(fr_high_dir).as_posix()
                            _upload(s3, bucket_exports, f"{fr_prefix}/highlights/{rel}", upload_src, content_type="video/mp4")
                    else:
                        _log("[firmRoot] by_jersey folder not found; skip highlights upload")

                if fr_logs_dir and fr_logs_dir.exists():
                    for p in fr_logs_dir.rglob("*"):
                        if p.is_file():
                            rel = p.relative_to(fr_logs_dir).as_posix()
                            _upload(s3, bucket_exports, f"{fr_prefix}/logs/{rel}", p, content_type=_guess_ct(p))

        _abort_checkpoint()

        # 4) fallback：沒有任何衍生品 → 用原檔
        if final_local is None and det_mp4:
            _log("[pipeline] no firmRoot/CLAHE, use detect annotated mp4 as final")
            final_local = det_mp4
        if final_local is None:
            _log("[pipeline] no derived outputs; using source as final")
            final_local = src
        
        
        _abort_checkpoint()
        fixed = tdir / "final_fixed.mp4"
        if _fixup_mp4(final_local, fixed):
            _log("[fix] finalized with H.264/AAC + faststart")
            final_local = fixed
        else:
            _log("[fix] ffmpeg finalize failed; uploading original result")

        out_key = f"{base_prefix}/output.mp4"
        _upload(s3, bucket_exports, out_key, final_local, content_type="video/mp4")

        _set_meta(outputKey=out_key)
        return {"ok": True, "outputKey": out_key, "jsonKey": json_key, "detectMp4Key": det_key}

