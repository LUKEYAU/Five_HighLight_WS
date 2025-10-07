from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
import boto3, os, io

app = FastAPI()

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("S3_ENDPOINT"),
    aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
    region_name=os.getenv("S3_REGION"),
)

BUCKET = os.getenv("S3_BUCKET_VIDEOS")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/uploads/multipart/create")
def create_multipart(payload: dict):
    key = payload["filename"]  # 實務上要加使用者目錄/UUID
    resp = s3.create_multipart_upload(Bucket=BUCKET, Key=key, ContentType=payload.get("contentType","application/octet-stream"))
    return {"uploadId": resp["UploadId"], "key": key}

@app.post("/uploads/multipart/sign")
def sign_part(payload: dict):
    url = s3.generate_presigned_url(
        ClientMethod="upload_part",
        Params={
            "Bucket": BUCKET,
            "Key": payload["key"],
            "UploadId": payload["uploadId"],
            "PartNumber": payload["partNumber"],
        },
        ExpiresIn=3600,
        HttpMethod="PUT",
    )
    return {"url": url}

@app.post("/uploads/multipart/complete")
def complete_multipart(payload: dict):
    parts = [{"ETag": p["etag"], "PartNumber": p["partNumber"]} for p in payload["parts"]]
    s3.complete_multipart_upload(
        Bucket=BUCKET, Key=payload["key"], MultipartUpload={"Parts": parts}
    )
    # TODO: 寫 DB 紀錄
    return {"ok": True, "key": payload["key"]}

@app.get("/videos/{key}/stream")
def stream_video(key: str, request: Request):
    # 簡化：直接 proxy；實務上需權限檢查與 Range 支援
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return StreamingResponse(obj["Body"], media_type=obj.get("ContentType","video/mp4"))
