import os, uuid, subprocess, tempfile, json
import boto3
from botocore.client import Config
from rq import get_current_job

def log(msg: str):
    job = get_current_job()
    if job:
        meta = job.meta or {}
        logs = meta.get("logs", [])
        logs.append(msg)
        meta["logs"] = logs[-200:]  # 最多保留 200 行
        job.meta = meta
        job.save_meta()
    print(msg, flush=True)

def set_meta(**kwargs):
    job = get_current_job()
    if job:
        meta = job.meta or {}
        meta.update(kwargs)
        job.meta = meta
        job.save_meta()

def run_ffmpeg(in_path: str, out_path: str, filters: list[str]):
    vf = ",".join(filters) if filters else "scale=iw:ih"  # no-op
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", in_path,
        "-vf", vf,
        "-preset", "veryfast",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    log(f"ffmpeg: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

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
    """
    下載 source_key → ffmpeg 處理 → 上傳到 exports/users/<sub>/... → 回傳 outputKey
    """
    session = boto3.session.Session()
    s3 = session.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "in.mp4")
        out_path = os.path.join(td, "out.mp4")

        # 1) 下載
        log(f"download s3://{bucket_videos}/{source_key}")
        s3.download_file(bucket_videos, source_key, in_path)

        # 2) 組合過濾器
        filters = []
        if bool(options.get("superResolution")):
            filters.append("scale=iw*2:ih*2:flags=lanczos")
        else:
            filters.append("scale=iw:ih")
        if bool(options.get("fps60")):
            filters.append("minterpolate=fps=60")

        # 3) ffmpeg 處理（示範）
        run_ffmpeg(in_path, out_path, filters)

        # 4) 上傳
        out_key = f"users/{user_sub}/exports/{uuid.uuid4().hex}.mp4"
        log(f"upload s3://{bucket_exports}/{out_key}")
        s3.upload_file(out_path, bucket_exports, out_key, ExtraArgs={"ContentType": "video/mp4"})

        set_meta(outputKey=out_key)
        return {"ok": True, "outputKey": out_key}
