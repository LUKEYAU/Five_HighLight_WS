import os, uuid, re
import boto3
import redis as redislib
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import FastAPI, Request, HTTPException, Depends, Header, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from rq import Queue
from rq.job import Job
from rq.command import send_stop_job_command
from rq.exceptions import NoSuchJobError
from urllib.parse import urlparse

# Google ID Token 驗證
from google.oauth2 import id_token as g_id_token
from google.auth.transport import requests as g_requests

APP_ENV = os.getenv("APP_ENV", "dev")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")                 # 容器內部
#S3_PUBLIC_ENDPOINT = os.getenv("S3_PUBLIC_ENDPOINT", "http://localhost:9000")  # 瀏覽器
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
BUCKET_VIDEOS = os.getenv("S3_BUCKET_VIDEOS", "videos")
BUCKET_EXPORTS = os.getenv("S3_BUCKET_EXPORTS", "exports")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0") 


app = FastAPI()
origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
if origins_env:
    allow_list = [o.strip() for o in origins_env.split(",") if o.strip()]
else:
    allow_list = []  # 同源前綴路由時可留空

if allow_list:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 兩個 S3 client：內部操作 & 專供簽名（使用 path-style）
s3_internal = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)


redis_conn = redislib.from_url(REDIS_URL)
edit_queue = Queue("edits", connection=redis_conn)

def bucket_for_key(key: str) -> str:
    if "/exports/" in key or key.startswith("exports/"):
        return BUCKET_EXPORTS
    return BUCKET_VIDEOS


def ensure_bucket_exists(bucket: str):
    try:
        s3_internal.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = (e.response or {}).get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            s3_internal.create_bucket(Bucket=bucket)
            print(f"[info] created bucket {bucket}")
        else:
            print(f"[error] head_bucket {bucket} failed: {e}")
            raise

# ---------- Auth ----------
class AuthUser(dict):
    @property
    def sub(self) -> str: return self.get("sub")
    @property
    def email(self) -> str: return self.get("email","")
    @property
    def name(self) -> str: return self.get("name","")

def verify_google_id_token(idt: str) -> AuthUser:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="server missing GOOGLE_CLIENT_ID")
    info = g_id_token.verify_oauth2_token(idt, g_requests.Request(), GOOGLE_CLIENT_ID)
    return AuthUser(info)

def get_current_user(
    authorization: str = Header(None),
    x_id_token: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> AuthUser:

    raw = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization.split(" ", 1)[1]
    elif x_id_token:
        raw = x_id_token
    elif token:
        raw = token

    if not raw:
        raise HTTPException(status_code=401, detail="Missing id token")

    try:
        return verify_google_id_token(raw)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google ID token: {e}")

ADMIN_EMAILS = {e.strip().lower() for e in (os.getenv("ADMIN_EMAILS", "")).split(",") if e.strip()}
ADMIN_SUBS   = {s.strip()          for s in (os.getenv("ADMIN_SUBS",   "")).split(",") if s.strip()}

def is_admin(user: "AuthUser") -> bool:
    return (user.email or "").lower() in ADMIN_EMAILS or (user.sub or "") in ADMIN_SUBS

def ensure_own_key(user: AuthUser, key: str):
    if is_admin(user):
        return
    prefix = f"users/{user.sub}/"
    if not key.startswith(prefix):
        raise HTTPException(status_code=403, detail="forbidden key")
    
@app.get("/me")
def me(user: AuthUser = Depends(get_current_user)):
    return {
        "sub": user.sub,
        "email": user.email,
        "name": user.name,
        "isAdmin": is_admin(user),
    }


def get_user_from_req_or_401(request: Request) -> AuthUser:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
        return verify_google_id_token(token)
    token = request.query_params.get("token")
    if token:
        return verify_google_id_token(token)
    raise HTTPException(status_code=401, detail="Missing or invalid token")


# ---------- Endpoints ----------
@app.get("/healthz")
@app.get("/health")
def health(): return {"ok": True}

@app.post("/uploads/multipart/create")
def create_multipart(payload: Dict[str, Any], user: AuthUser = Depends(get_current_user)):
    ensure_bucket_exists(BUCKET_VIDEOS)
    filename = payload.get("filename") or "unnamed.bin"
    content_type = payload.get("contentType") or "application/octet-stream"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    key = f"users/{user.sub}/uploads/{uuid.uuid4().hex}/{safe}"
    try:
        resp = s3_internal.create_multipart_upload(
            Bucket=BUCKET_VIDEOS, Key=key, ContentType=content_type
        )
        return {"uploadId": resp["UploadId"], "key": key}
    except ClientError as e:
        msg = (e.response or {}).get("Error", {}).get("Message", str(e))
        print(f"[error] create_multipart ClientError: {msg}")
        raise HTTPException(status_code=500, detail=f"S3 error: {msg}")
    except Exception as e:
        print(f"[error] create_multipart unexpected: {e}")
        raise HTTPException(status_code=500, detail=f"unexpected: {e}")

@app.post("/uploads/multipart/sign")
def sign_part(payload: Dict[str, Any], user: AuthUser = Depends(get_current_user)):
    key = payload["key"]
    upload_id = payload["uploadId"]
    part_no = int(payload["partNumber"])
    ensure_own_key(user, key)
    try:
        presigned = s3_internal.generate_presigned_url(
            ClientMethod="upload_part",
            Params={"Bucket": BUCKET_VIDEOS, "Key": key, "UploadId": upload_id, "PartNumber": part_no},
            ExpiresIn=3600, HttpMethod="PUT",
        )
        p = urlparse(presigned)
        relative = "/s3" + p.path + ("?" + p.query if p.query else "")
        return {"url": relative}
    except ClientError as e:
        msg = (e.response or {}).get("Error", {}).get("Message", str(e))
        raise HTTPException(status_code=500, detail=f"S3 error: {msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"unexpected: {e}")

@app.post("/uploads/multipart/complete")
def complete_multipart(payload: Dict[str, Any], user: AuthUser = Depends(get_current_user)):
    key = payload["key"]; 
    upload_id = payload["uploadId"]
    ensure_own_key(user, key)
    parts_in = payload.get("parts", [])
    if not parts_in: raise HTTPException(status_code=400, detail="parts required")
    parts = []
    for p in parts_in:
        etag = p["etag"]
        if not etag.startswith('"'): etag = '"' + etag.strip('"') + '"'
        parts.append({"ETag": etag, "PartNumber": int(p["partNumber"])})
    s3_internal.complete_multipart_upload(
        Bucket=BUCKET_VIDEOS, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
    )
    return {"ok": True, "key": key}

@app.delete("/uploads/{key:path}")
def delete_upload(key: str, user: AuthUser = Depends(get_current_user)):
    """刪除自己名下的某個上傳物件。"""
    ensure_bucket_exists(BUCKET_VIDEOS)
    ensure_own_key(user, key)
    try:
        s3_internal.delete_object(Bucket=BUCKET_VIDEOS, Key=key)
        # S3 刪除對不存在的物件也會回 204/200，這裡統一回 204
        return Response(status_code=204)
    except ClientError as e:
        msg = (e.response or {}).get("Error", {}).get("Message", str(e))
        print(f"[error] delete_upload ClientError: {msg}")
        raise HTTPException(status_code=500, detail=f"S3 error: {msg}")
    except Exception as e:
        print(f"[error] delete_upload unexpected: {e}")
        raise HTTPException(status_code=500, detail=f"unexpected: {e}")

@app.get("/admin/uploads/recent")
def uploads_recent_all(
    limit: int = 100,
    ownerSub: Optional[str] = None,             # 可選：只看某個使用者
    continuationToken: Optional[str] = Query(None, alias="ct"),  # 分頁游標
    user: AuthUser = Depends(get_current_user),
):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="admin only")
    
    ensure_bucket_exists(BUCKET_VIDEOS)
    kwargs = {"Bucket": BUCKET_VIDEOS, "MaxKeys": max(1, min(limit, 1000))}
    if ownerSub:
        kwargs["Prefix"] = f"users/{ownerSub}/uploads/"
    if continuationToken:
        kwargs["ContinuationToken"] = continuationToken

    resp = s3_internal.list_objects_v2(**kwargs)
    contents = resp.get("Contents") or []
    epoch = datetime.fromtimestamp(0, tz=timezone.utc)
    contents.sort(key=lambda o: o.get("LastModified") or epoch, reverse=True)
    items = []
    for o in contents:
        lm = o.get("LastModified")
        iso = lm.astimezone(timezone.utc).isoformat() if lm else None
        items.append({
            "key": o["Key"],
            "size": int(o.get("Size", 0)),
            "lastModified": iso,
        })

    return {
        "items": items[: max(1, min(limit, 1000))],
        "isTruncated": bool(resp.get("IsTruncated")),
        "nextCt": resp.get("NextContinuationToken"),
    }

@app.get("/uploads/recent")
def uploads_recent(limit: int = 20, user: AuthUser = Depends(get_current_user)):
    ensure_bucket_exists(BUCKET_VIDEOS)
    prefix = f"users/{user.sub}/uploads/"
    try:
        resp = s3_internal.list_objects_v2(Bucket=BUCKET_VIDEOS, Prefix=prefix)
        contents = resp.get("Contents", []) or []
        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        contents.sort(key=lambda o: o.get("LastModified") or epoch, reverse=True)

        items = []
        for o in contents[: max(1, min(limit, 200))]:
            lm = o.get("LastModified")
            iso = lm.astimezone(timezone.utc).isoformat() if lm else None
            items.append({"key": o["Key"], "size": int(o.get("Size", 0)), "lastModified": iso})
        return {"items": items}
    except Exception as e:
        print(f"[error] uploads_recent: {e}")
        raise HTTPException(status_code=500, detail=f"list failed: {e}")

@app.get("/downloads/presign/{key:path}")
def presign_download(
    key: str,
    expires: int = 600,
    attachment: bool = True,
    user: AuthUser = Depends(get_current_user),
):
    ensure_own_key(user, key)
    bucket = bucket_for_key(key)

    try:
        s3_internal.head_object(Bucket=bucket, Key=key)
    except ClientError:
        raise HTTPException(status_code=404, detail="object not found")

    params = {"Bucket": bucket, "Key": key}
    if attachment:
        filename = os.path.basename(key)
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

    url = s3_internal.generate_presigned_url(
        ClientMethod="get_object",
        Params=params,
        ExpiresIn=max(60, min(expires, 7 * 24 * 3600)),
    )
    p = urlparse(url)
    relative = "/s3" + p.path + ("?" + p.query if p.query else "")
    return {"url": relative}

@app.post("/edits")
def create_edit_job(payload: Dict[str, Any], user: AuthUser = Depends(get_current_user)):
    """
    建立自動剪輯任務。
    payload = { "key": <來源 S3 key>, "options": { "superResolution": bool, "fps60": bool } }
    """
    src_key = payload.get("key") or ""
    ensure_own_key(user, src_key)
    options = payload.get("options") or {}
    job = edit_queue.enqueue(
        "jobs.run_auto_edit",
        kwargs={
            "s3_endpoint": S3_ENDPOINT,
            "s3_region": S3_REGION,
            "access_key": S3_ACCESS_KEY,
            "secret_key": S3_SECRET_KEY,
            "bucket_videos": BUCKET_VIDEOS,
            "bucket_exports": BUCKET_EXPORTS,
            "source_key": src_key,
            "user_sub": user.sub,
            "options": {
                "superResolution": bool(options.get("superResolution", False)),
                "fps60": bool(options.get("fps60", False)),
            },
        },
        job_timeout="7h",
        result_ttl=86400,
        failure_ttl=86400,
    )
    return {"jobId": job.get_id()}

@app.get("/edits/{job_id}")
def get_edit_job(job_id: str, user: AuthUser = Depends(get_current_user)):
    """查詢任務狀態；若完成會回 outputKey。"""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        raise HTTPException(status_code=404, detail="job not found")

    status = job.get_status()
    meta = job.meta or {}

    for k in ("outputKey", "jsonKey", "detectMp4Key"):
        v = meta.get(k)
        if v is not None:
            ensure_own_key(user, v)

    resp = {
        "id": job.get_id(),
        "status": status,
        "outputKey": meta.get("outputKey"),
        "jsonKey": meta.get("jsonKey"),
        "detectMp4Key": meta.get("detectMp4Key"),
        "error": meta.get("error"),
        "logs": (meta.get("logs") or [])[:50],  # 最多 50 行簡單日志
        #"progress": meta.get("progress") or {},
    }
    return resp

@app.post("/edits/{job_id}/cancel")
def cancel_edit_job(job_id: str, user: AuthUser = Depends(get_current_user)):
    """
    取消/請求取消一個編輯任務：
    - 若還在 queued/deferred/scheduled：直接取消（轉入 CanceledJobRegistry 或標記 canceled）
    - 若已 started：在 job.meta 上打上 abort/cancel_requested 旗標，由 worker 盡快中止
    僅允許任務擁有者或 admin 執行。
    """
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        raise HTTPException(status_code=404, detail="job not found")

    # 授權：僅擁有者或 admin
    # 我們把 user_sub 放在 enqueue kwargs 裡（在 create_edit_job 已有傳入）
    user_sub_in_job = (job.kwargs or {}).get("user_sub")
    if not (is_admin(user) or user_sub_in_job == user.sub):
        raise HTTPException(status_code=403, detail="forbidden")

    status = job.get_status()
    # 可直接取消的狀態
    if status in ("queued", "deferred", "scheduled"):
        try:
            job.cancel()  # rq 會把它移到 Canceled registry（依版本）
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"cancel failed: {e}")
        # 更新 meta 讓前端好辨識
        meta = job.meta or {}
        meta["error"] = "canceled by user"
        meta["canceled"] = True
        job.meta = meta
        job.save_meta()
        return {"ok": True, "canceled": True, "already_started": False}

    # 已經開始：送出取消請求（合作式）
    meta = job.meta or {}
    meta["abort"] = True
    meta["cancel_requested"] = True
    job.meta = meta
    job.save_meta()

    # 若你的 RQ 版本支援 soft stop，可嘗試通知（不一定能立即殺掉子進程）
    try:
        send_stop_job_command(redis_conn, job_id)
    except Exception:
        pass

    return {"ok": True, "canceled": False, "already_started": True}

# Range 串流：支援 GET + HEAD，回應頭補 Access-Control-Allow-Origin
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
MAX_RANGE_CHUNK = 8 * 1024 * 1024

@app.api_route("/videos/stream/{key:path}", methods=["GET", "HEAD"])
def stream_video(key: str, request: Request):
    user = get_user_from_req_or_401(request)
    ensure_own_key(user, key)
    bucket = bucket_for_key(key)

    try:
        head = s3_internal.head_object(Bucket=bucket, Key=key)
        total = int(head["ContentLength"])
        content_type = head.get("ContentType") or "application/octet-stream"
    except Exception:
        raise HTTPException(status_code=404, detail="object not found")

    range_header: Optional[str] = request.headers.get("range") or request.headers.get("Range")

    def _headers(base: Dict[str, str]) -> Dict[str, str]:
        h = {
            "Accept-Ranges": "bytes",
            "Content-Type": content_type,
            "Access-Control-Allow-Origin": "*",
        }
        h.update(base)
        return h

    def _parse_range(rh: str):
        m = _RANGE.match(rh or "")
        if not m:
            raise HTTPException(status_code=416, detail="Invalid Range header")
        start_s, end_s = m.groups()
        if start_s == "" and end_s == "":
            raise HTTPException(status_code=416, detail="Invalid Range values")
        if start_s != "":
            start = int(start_s)
            end = int(end_s) if end_s != "" else min(start + MAX_RANGE_CHUNK - 1, total - 1)
        else:
            tail = int(end_s)
            start = max(total - tail, 0)
            end = total - 1
        if start >= total:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")
        return start, min(end, total - 1)

    if request.method == "HEAD":
        if range_header:
            start, end = _parse_range(range_header)
            return Response(status_code=206, headers=_headers({
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(end - start + 1),
            }))
        else:
            return Response(status_code=200, headers=_headers({"Content-Length": str(total)}))

    if range_header:
        start, end = _parse_range(range_header)
        obj = s3_internal.get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")
        return StreamingResponse(
            obj["Body"],
            status_code=206,
            headers=_headers({
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(end - start + 1),
            }),
            media_type=content_type,
        )

    obj = s3_internal.get_object(Bucket=bucket, Key=key)
    return StreamingResponse(obj["Body"], headers=_headers({
        "Content-Length": str(total)}), media_type=content_type)

@app.post("/uploads/multipart/abort")
def abort_multipart(payload: Dict[str, Any], user: AuthUser = Depends(get_current_user)):
    key = payload.get("key") or ""
    upload_id = payload.get("uploadId") or ""
    if not key or not upload_id:
        raise HTTPException(status_code=400, detail="key and uploadId required")
    ensure_own_key(user, key)
    try:
        s3_internal.abort_multipart_upload(Bucket=bucket_for_key(key), Key=key, UploadId=upload_id)
        return {"ok": True}
    except ClientError as e:
        msg = (e.response or {}).get("Error", {}).get("Message", str(e))
        raise HTTPException(status_code=500, detail=f"S3 error: {msg}")

import re
from typing import List, Dict
from urllib.parse import urlparse

def _presign_relative(url: str) -> str:
    # 轉成 /s3/... 相對網址，讓瀏覽器經由 Nginx -> MinIO
    p = urlparse(url)
    return "/s3" + p.path + ("?" + p.query if p.query else "")

_jobid_re = re.compile(r"^users/[^/]+/exports/([^/]+)/")

def _extract_job_id(key: str) -> str | None:
    m = _jobid_re.match(key)
    return m.group(1) if m else None

def _jersey_from_byjersey_path(key: str) -> str | None:
    # .../firmRoot/highlights/by_jersey/<jersey>_<COLOR>/pid_xxx/clip.mp4
    parts = key.split("/")
    try:
        i = parts.index("by_jersey")
        name = parts[i+1]  # e.g., "12_RED" or "unknown_WHITE"
        jersey = name.split("_", 1)[0]
        return jersey
    except Exception:
        return None

def _is_jersey_le_50(j: str | None) -> bool:
    if j is None:   # unknown 保留
        return True
    try:
        return int(j) <= 99
    except:
        return j.lower() == "unknown"

@app.get("/highlights/jobs")
def list_my_highlight_jobs(user: AuthUser = Depends(get_current_user), limit: int = 20):

    ensure_bucket_exists(BUCKET_EXPORTS)
    prefix = f"users/{user.sub}/exports/"
    resp = s3_internal.list_objects_v2(Bucket=BUCKET_EXPORTS, Prefix=prefix)
    contents = resp.get("Contents") or []
    # 只取包含 by_jersey 的 mp4
    items = []
    by_job: Dict[str, Dict[str, Any]] = {}
    for o in contents:
        key = o.get("Key", "")
        if "/firmRoot/highlights/by_jersey/" not in key:
            continue
        if not key.lower().endswith(".mp4"):
            continue
        job_id = _extract_job_id(key)
        if not job_id:
            continue
        d = by_job.setdefault(job_id, {"jobId": job_id, "lastModified": None, "count": 0})
        lm = o.get("LastModified")
        if lm and (d["lastModified"] is None or lm > d["lastModified"]):
            d["lastModified"] = lm
        d["count"] += 1

    # 排序與裁切
    arr = list(by_job.values())
    arr.sort(key=lambda x: x["lastModified"] or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
    out = []
    for e in arr[: max(1, min(limit, 200))]:
        lm_iso = e["lastModified"].astimezone(timezone.utc).isoformat() if e["lastModified"] else None
        out.append({"jobId": e["jobId"], "lastModified": lm_iso, "count": e["count"]})
    return {"items": out}

@app.get("/highlights/by-jersey")
def list_highlights_by_jersey(
    jobId: str = Query(..., alias="jobId"),
    presign: bool = False,
    user: AuthUser = Depends(get_current_user),
):

    ensure_bucket_exists(BUCKET_EXPORTS)
    base = f"users/{user.sub}/exports/{jobId}/firmRoot/highlights/by_jersey/"
    resp = s3_internal.list_objects_v2(Bucket=BUCKET_EXPORTS, Prefix=base)
    contents = resp.get("Contents") or []

    groups: Dict[str, Dict[str, Any]] = {}
    for o in contents:
        key = o.get("Key", "")
        if not key.lower().endswith(".mp4"):
            continue
        jersey_team = key.split("/by_jersey/")[-1].split("/")[0]  # e.g., "12_RED"
        jersey = jersey_team.split("_", 1)[0] if "_" in jersey_team else jersey_team
        color = jersey_team.split("_", 1)[1] if "_" in jersey_team else ""
        if not _is_jersey_le_50(jersey):
            continue
        g = groups.setdefault(jersey_team, {"jerseyTeam": jersey_team, "jersey": jersey, "color": color, "clips": []})
        lm = o.get("LastModified")
        item = {
            "key": key,
            "size": int(o.get("Size", 0)),
            "lastModified": lm.astimezone(timezone.utc).isoformat() if lm else None,
        }
        if presign:
            url = s3_internal.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": BUCKET_EXPORTS, "Key": key},
                ExpiresIn=600,
            )
            item["url"] = _presign_relative(url)
        g["clips"].append(item)

    # 每組依時間排序
    result = []
    for k, g in groups.items():
        g["clips"].sort(key=lambda x: x["lastModified"] or "", reverse=False)
        result.append(g)

    def _jersey_sort(v):
        j = v.get("jersey")
        try:
            return (0, int(j))
        except:
            return (1, 9999 if j == "unknown" else 9998)
    result.sort(key=_jersey_sort)
    return {"groups": result}
