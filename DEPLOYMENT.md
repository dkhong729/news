# 部署指南（雲端）

## 推薦拓樸
- `frontend`：Vercel
- `backend API + scheduler`：Render/Fly.io/Railway（同專案兩個 process）
- `PostgreSQL`：Neon/Supabase/Postgres Managed

## 後端環境變數
- `DATABASE_URL`
- `APP_JWT_SECRET`
- `ADMIN_BOOTSTRAP_EMAIL`（可選，設定後第一次啟動會自動建立 admin）
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `FRONTEND_CALLBACK_URL`
- `DEEPSEEK_API_KEY`
- `EMAIL_PROVIDER`
- `EMAIL_API_KEY`
- `EMAIL_FROM`
- `PUBLIC_API_BASE_URL`
- `SENDGRID_WEBHOOK_SECRET`
- `REDIS_URL`（建議）
- `SENTRY_DSN`（建議）
- `PIPELINE_ALERT_WEBHOOK`（建議）
- `INGEST_INTERVAL_HOURS=6`
- `DIGEST_HOUR=8`
- `DIGEST_MINUTE=0`

## 後端啟動指令
- Web：`python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --app-dir /app`
- Worker：`python -m backend.scheduler`

## 前端環境變數
- `NEXT_PUBLIC_API_BASE=https://你的-backend-domain`

## 首次部署順序
1. 建立 DB 並設定 `DATABASE_URL`
2. 部署 backend API
3. 執行初始化：`python -c "from backend.db import init_db; init_db()"`
4. 執行一次管線：`python -m backend.pipeline`
5. 部署 frontend
6. 啟動 scheduler worker
7. 設定 SendGrid Event Webhook 指向 `POST /webhooks/sendgrid`，並配置 `x-webhook-secret`
8. 在 DNS 設定 SPF / DKIM / DMARC（初期可用 `p=none`）

## 監控建議
- API health check：`GET /health`
- 每 6 小時應看到新資料寫入 `raw_items`/`normalized_items`/`events`
- 每日 08:00 驗證 `EMAIL_*` 是否成功寄送
