import os, uuid, re
from typing import Optional, Dict, Any
from datetime import timezone

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import FastAPI, Request, HTTPException, Depends, Header, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import Optional
# Google ID Token 驗證
from google.oauth2 import id_token as g_id_token
from google.auth.transport import requests as g_requests

APP_ENV = os.getenv("APP_ENV", "dev")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")                 # 容器內部
S3_PUBLIC_ENDPOINT = os.getenv("S3_PUBLIC_ENDPOINT", "http://localhost:9000")  # 瀏覽器
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
BUCKET_VIDEOS = os.getenv("S3_BUCKET_VIDEOS", "videos")
BUCKET_EXPORTS = os.getenv("S3_BUCKET_EXPORTS", "exports")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://127.0.0.1:5173"],
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
s3_signer = boto3.client(
    "s3",
    endpoint_url=S3_PUBLIC_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)

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
    """
    驗證順序：
    1) Authorization: Bearer <id_token>
    2) X-ID-Token: <id_token>
    3) ?token=<id_token>               ← 用於避免 GET 的預檢（CORS）
    """
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

def ensure_own_key(user: AuthUser, key: str):
    prefix = f"users/{user.sub}/"
    if not key.startswith(prefix):
        raise HTTPException(status_code=403, detail="forbidden key")

# ---------- Endpoints ----------
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
    key = payload["key"]; upload_id = payload["uploadId"]; part_no = int(payload["partNumber"])
    ensure_own_key(user, key)
    url = s3_signer.generate_presigned_url(
        ClientMethod="upload_part",
        Params={"Bucket": BUCKET_VIDEOS, "Key": key, "UploadId": upload_id, "PartNumber": part_no},
        ExpiresIn=3600, HttpMethod="PUT",
    )
    return {"url": url}

@app.post("/uploads/multipart/complete")
def complete_multipart(payload: Dict[str, Any], user: AuthUser = Depends(get_current_user)):
    key = payload["key"]; upload_id = payload["uploadId"]
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

@app.get("/uploads/recent")
def uploads_recent(limit: int = 20, user: AuthUser = Depends(get_current_user)):
    ensure_bucket_exists(BUCKET_VIDEOS)
    prefix = f"users/{user.sub}/uploads/"
    try:
        resp = s3_internal.list_objects_v2(Bucket=BUCKET_VIDEOS, Prefix=prefix)
        contents = resp.get("Contents", []) or []
        contents.sort(key=lambda o: o.get("LastModified") or 0, reverse=True)
        items = []
        for o in contents[: max(1, min(limit, 200))]:
            lm = o.get("LastModified")
            iso = lm.astimezone(timezone.utc).isoformat() if hasattr(lm, "astimezone") else None
            items.append({"key": o["Key"], "size": int(o.get("Size", 0)), "lastModified": iso})
        return {"items": items}
    except Exception as e:
        print(f"[error] uploads_recent: {e}")
        raise HTTPException(status_code=500, detail=f"list failed: {e}")

# Range 串流：支援 GET + HEAD，回應頭補 Access-Control-Allow-Origin
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")

@app.api_route("/videos/stream/{key:path}", methods=["GET", "HEAD"])
def stream_video(key: str, request: Request):
    try:
        head = s3_internal.head_object(Bucket=BUCKET_VIDEOS, Key=key)
        total = int(head["ContentLength"])
        content_type = head.get("ContentType") or "application/octet-stream"
    except Exception:
        raise HTTPException(status_code=404, detail="object not found")

    range_header: Optional[str] = request.headers.get("range") or request.headers.get("Range")

    # HEAD：只回 header
    if request.method == "HEAD":
        if range_header:
            m = _RANGE.match(range_header or "")
            if not m:
                raise HTTPException(status_code=416, detail="Invalid Range header")
            start_s, end_s = m.groups()
            if start_s == "" and end_s == "":
                raise HTTPException(status_code=416, detail="Invalid Range values")
            if start_s != "":
                start = int(start_s)
                end = int(end_s) if end_s != "" else min(start + 8 * 1024 * 1024 - 1, total - 1)
            else:
                tail = int(end_s)
                start = max(total - tail, 0)
                end = total - 1
            if start >= total:
                raise HTTPException(status_code=416, detail="Range Not Satisfiable")

            chunk_len = end - start + 1
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(chunk_len),
                "Content-Type": content_type,
                "Access-Control-Allow-Origin": "*",
            }
            return Response(status_code=206, headers=headers)
        else:
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(total),
                "Content-Type": content_type,
                "Access-Control-Allow-Origin": "*",
            }
            return Response(status_code=200, headers=headers)

    # GET：實際串流
    if range_header:
        m = _RANGE.match(range_header)
        if not m:
            raise HTTPException(status_code=416, detail="Invalid Range header")
        start_s, end_s = m.groups()
        if start_s == "" and end_s == "":
            raise HTTPException(status_code=416, detail="Invalid Range values")
        if start_s != "":
            start = int(start_s)
            end = int(end_s) if end_s != "" else min(start + 8 * 1024 * 1024 - 1, total - 1)
        else:
            tail = int(end_s)
            start = max(total - tail, 0)
            end = total - 1
        if start >= total:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")

        obj = s3_internal.get_object(Bucket=BUCKET_VIDEOS, Key=key, Range=f"bytes={start}-{end}")
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Length": str(end - start + 1),
            "Content-Type": content_type,
            "Access-Control-Allow-Origin": "*",
        }
        return StreamingResponse(obj["Body"], status_code=206, headers=headers, media_type=content_type)

    obj = s3_internal.get_object(Bucket=BUCKET_VIDEOS, Key=key)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(total),
        "Content-Type": content_type,
        "Access-Control-Allow-Origin": "*",
    }
    return StreamingResponse(obj["Body"], headers=headers, media_type=content_type)
