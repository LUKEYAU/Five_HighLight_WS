# 5人足球精華自動剪輯（Docker 佈署指南）

## 目錄
1. [系統架構](#系統架構)  
2. [需求與前置作業](#需求與前置作業)  
3. [啟動服務](#啟動服務)  
4. [存取](#存取)  
5. [換 Port / 用網域與反向代理時要改哪些](#換-port--用網域與反向代理時要改哪些)  
6. [更新、重啟與除錯](#更新、重啟與除錯)


## 系統架構
```
/app
  /frontend      # React 網站（Vite Dev / 可改成靜態 build）
  /api           # FastAPI 後端（登入驗證、S3 預簽、串流代理、任務 API）
  /worker        # 背景工作（RQ Worker;自動剪輯/FFmpeg 示範）
  /infra
    docker-compose.yml
    nginx/
      nginx.conf
      conf.d/*.conf
    minio/       # 物件儲存（S3）
      create-buckets.sh
    .env 
  .env 
```
---

## 需求與前置作業:
- 需要Docker

三個子網域(可改):
- 前端:http://localhost:5173
- API Health:http://localhost:8000/health
- MinIO Console:http://localhost:9001

**Clone 並設定環境變數**
```bash
git clone https://github.com/LUKEYAU/Five_HighLight_WS.git fivecut
cd fivecut
cd infra
cp .env .env.example
```
放tls憑證至fiveut/infra/nginx/ssl
```
GOOGLE_CLIENT_ID=....
```

*如需要通知我們*  
Google OAuth → Authorized JavaScript origins 加入:
https://app.example.com

## 啟動服務
```bash
cd infra
docker compose build --no-cache frontend
docker compose up -d --build
docker compose up -d --build worker --profile worker
```

## 存取(不用看)
- 前端:http://localhost:5173
- API Health:http://localhost:8000/health
- MinIO Console:http://localhost:9001

---
## 換 Port / 用網域與反向代理時要改哪些(不用看)
**A. 只換對外 port(不走網域)**

假設把:  
前端對外改為 :3000  
API 對外改為 :8080  
MinIO(S3)對外改為 :19000(Console 可維持 9001 或自訂)

**步驟:
編輯 infra/docker-compose.yml:**
```
services:
  frontend:
    environment:
      VITE_API_BASE: http://localhost:8080
    ports:
      - "3000:5173"

  api:
    ports:
      - "8080:8000"

  minio:
    ports:
      - "19000:9000"  # S3 API
      - "9001:9001"   # Console
```

同步修改 .env:
```
FRONTEND_ORIGIN=http://localhost:3000
S3_PUBLIC_ENDPOINT=http://localhost:19000
```

重建:
```bash
docker compose up -d --build
```

**要點:**
- .env 的 FRONTEND_ORIGIN 影響 API 的 CORS
- VITE_API_BASE 是前端打 API 的 URL
- S3_PUBLIC_ENDPOINT 是 API 幫你「簽名」時寫進預簽 URL 的主機，一定- 要是瀏覽器能直連的對外位址與 Port

---
**B. 改用網域(反向代理)**
開 80(HTTP) 和 443(HTTPS) 給外部,再反向代理5173、8000、9000/9001(不對外開)

建議配三個子網域(HTTPS):
- app.example.com → 前端
- api.example.com → API
- s3.example.com → MinIO(S3 API 給瀏覽器 PUT 直傳)


infra/docker-compose.yml:把對外 ports 關掉
```yml
services:
  frontend:
    # ports: ["5173:5173"]  # 可移除，或保留給內網測試
    environment:
      VITE_API_BASE: api.example.com
  api:
    # ports: ["8000:8000"]  # 同上
  minio:
    ports:
      - "9000:9000"  # 若反代直接連容器網路，可移除
      - "9001:9001"
```

.env 改成網域:
```bash
FRONTEND_ORIGIN=https://app.example.edu
S3_PUBLIC_ENDPOINT=https://s3.example.edu
```
---
## 更新、重啟與除錯

更新程式:
```bash
cd infra
docker compose build
docker compose up -d
```

查看日誌:
```bash
docker compose logs -f api
docker compose logs -f frontend
docker compose logs -f worker --profile worker
docker compose logs -f minio
```

健康(api)檢查:
```bash
curl -i http://localhost:8000/health
```

檢測串流(Range/HEAD):
```bash
KEY='<某個已上傳的 key>'
curl -I "http://localhost:8000/videos/stream/$KEY"
curl -I -H "Range: bytes=0-1048575" "http://localhost:8000/videos/stream/$KEY"
```