# 5人足球精華自動剪輯(Docker 佈署指南)

## 目錄
1. [系統架構](#系統架構)  
2. [需求與前置作業](#需求與前置作業)  
3. [啟動服務](#啟動服務)  
4. [更新、重啟與除錯](#更新、重啟與除錯)


## 系統架構
vite 轉 靜態檔 Nginx(/fronted/Dockerfile.prod)
```
/app
  /frontend      # React 網站(Vite Dev / 改成靜態 build)
  /api           # FastAPI 後端(登入驗證、S3 預簽、串流代理、任務 API)
  /worker        # 背景工作(RQ Worker;自動剪輯/FFmpeg 示範)
  /infra
    docker-compose.yml
    nginx/
      nginx.conf
      conf.d/*.conf
      ssl/       #tls cert
    minio/       # 物件儲存(S3)
      create-buckets.sh
    .env 
```
---

## 需求與前置作業:
- 需要Docker

三個子網域(可改):
- fiveclip.fcuai.tw -> nginx:443
- fiveclip-api.fcuai.tw -> nginx:443
- fiveclip-s3.fcuai.tw -> nginx:443

轉發到：
- frontend 容器 :80
- api 容器 :8000
- minio 容器 :9000
```
/fivecut/infra/nginx/conf.d/frontend.conf(代理到 http://frontend:80)
/fivecut/infra/nginx/conf.d/api.conf(代理到 http://api:8000)
/fivecut/infra/nginx/conf.d/minio.conf(代理到 http://minio:9000)
```

**Clone 並設定環境變數**
```bash
git clone https://github.com/LUKEYAU/Five_HighLight_WS.git fivecut
cd fivecut
cd infra
cp .env.example .env
```

放tls憑證至fiveut/infra/nginx/ssl  
- fiveclip.fcuai.tw.crt / fiveclip.fcuai.tw.key
- fiveclip-api.fcuai.tw.crt / fiveclip-api.fcuai.tw.key
- fiveclip-s3.fcuai.tw.crt / fiveclip-s3.fcuai.tw.key

如檔名不同對應修改  
- /fivecut/infra/nginx/conf.d/frontend.conf
- /fivecut/infra/nginx/conf.d/api.conf
- /fivecut/infra/nginx/conf.d/minio.conf
Nginx reload:
```bash
cd infra
docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
```

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
https://fiveclip.fcuai.tw/
https://fiveclip-api.fcuai.tw/healthz
https://fiveclip-s3.fcuai.tw/(封閉,只可用於物件儲存)
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