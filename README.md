# AI Insight Pulse

面向 VC、商業決策者與技術領袖的 AI 情報聚合器。

## 核心能力
- 每 6 小時自動抓取並更新資料庫（PostgreSQL）
- 每輪自動清洗：過期活動、列表頁活動、低品質/亂碼/異常長標題資料
- 時間窗過濾（可調）
  - 論文：預設過去 14 天
  - 貼文：預設過去 7 天
  - 活動：預設未來 90 天
  - 其他網站：預設前後 7 天
- 去重、分類（AI 新知 / AI 活動）、摘要、可解釋打分
- 前端直接讀 DB API（不走本地 JSON）
- Gmail 訂閱：立即寄送 + 每天早上 08:00 自動寄送
- Google Gmail 登入（OAuth）
- JWT + RBAC 權限模型（User -> Roles -> Permissions）
- `/admin/*` 由 middleware + 權限檢查保護
- 安全防禦：IP/User Rate Limit、WAF 規則、Redis 黑名單（24h）
- VC Scout + VC DD 報告（候選團隊、shortlist、外聯草稿、DD 報告）
- VC Scout 支援政府資源/補助/展會名單查詢 pack（可用於海量搜台灣新創）
- 碩博申請 Lab DD（履歷 + 目標學校 -> 實驗室候選與 DD 報告）
- 郵件可投遞性：List-Unsubscribe / 一鍵退訂 / SendGrid Bounce Webhook
- 爬蟲韌性：指數退避、快取降級、來源健康度紀錄、代理池輪替

## 專案結構
- `backend/` FastAPI + Pipeline + Scheduler
- `frontend/` Next.js 頁面（`/` 首頁、`/news` 新知、`/dd` DD、`/admin` 後台）
- `docker-compose.yml` PostgreSQL

## 本機啟動（建議順序）
1. 建立並啟動資料庫
   - `docker compose up -d`
2. 建立 Python 虛擬環境
   - `python -m venv .venv`
   - `./.venv/Scripts/Activate.ps1`
3. 安裝後端套件
   - `pip install -r backend/requirements.txt`
4. 設定環境變數
   - 複製 `backend/.env.example` 為 `backend/.env`
   - 填入 `DATABASE_URL`、`APP_JWT_SECRET`、`GOOGLE_*`、`EMAIL_*`
   - 若要後台管理權限，填 `ADMIN_BOOTSTRAP_EMAIL=你的gmail`
   - 後台白名單用 `ADMIN_ALLOWLIST_EMAILS`（預設只允許 `dkhong0729@gmail.com,yoshikuni2046@gmail.com`）
   - 若要黑名單/節流共享，填 `REDIS_URL`
   - 公司 DD 深度爬蟲可調：`DD_COMPANY_MAX_PAGES`、`DD_COMPANY_MIN_PAGES`、`DD_COMPANY_MIN_RUNTIME_SEC`
   - 啟用 Deep Research Agent：`DD_USE_DEEP_RESEARCH_AGENT=1`
   - 外部搜尋可選 Tavily：填 `TAVILY_API_KEY`，並可設 `DD_DEEP_RESEARCH_SEARCH_PROVIDER=auto|tavily|duckduckgo`
   - 可選 LangChain 寫作/壓縮層：`DD_DEEP_RESEARCH_USE_LANGCHAIN=1`
   - VC Scout 政府資源查詢 pack：`VC_SCOUT_ENABLE_GOV_QUERY_PACK=1`、`VC_SCOUT_GOV_QUERY_CAP=12`
   - 資料清洗門檻：`CLEANUP_MIN_EVENT_SCORE`、`CLEANUP_MIN_INSIGHT_SCORE`、`CLEANUP_MAX_TITLE_LEN`
   - 若本機有奇怪代理導致爬蟲抓不到內容，設 `HTTP_TRUST_ENV_PROXY=0`
   - 若寄信遇到 `ProxyError`，設 `EMAIL_TRUST_ENV_PROXY=0`（必要時再用 `EMAIL_PROXY_URL`）
5. 初始化資料表
   - `python -c "from backend.db import init_db; init_db()"`
6. 手動跑一次管線（驗證資料）
   - `python -m backend.pipeline`
7. 啟動 API
   - `python -m uvicorn backend.app:app --reload --port 8000 --app-dir C:\project\news`
8. 啟動前端
   - `cd frontend`
   - `npm install`
   - `npm run dev`
9. 排程器
   - 預設 `AUTO_START_SCHEDULER=1`，API 啟動後會自動執行（6 小時抓取 + 每日 08:00 寄信，台北時區可由 `DIGEST_TIMEZONE` 調整）。
   - 若你想獨立跑 worker，也可另外執行：`python -m backend.scheduler`

## 常用 API
- `GET /health`
- `POST /pipeline/run`：立即重跑抓取流程
- `GET /mvp?limit=10&role=tech&insight_days=14&event_days=60`：首頁資料（新知 + 台灣活動 + 全球活動）
- `POST /subscribe_email`：Gmail 訂閱
- `GET /auth/google/start`：Google 登入入口
- `GET /auth/me`：查看目前 token 與 permissions
- `GET /admin/events` / `PATCH /admin/events/{id}` / `DELETE /admin/events/{id}`
- `GET /admin/insights` / `PATCH /admin/insights/{id}` / `DELETE /admin/insights/{id}`
- `GET /admin/subscribers` / `PATCH /admin/subscribers/{user_id}`
- `POST /admin/localize`：將舊英文資料轉為繁體中文
- `POST /admin/maintenance/cleanup` / `GET /admin/maintenance/audit`：清理與檢查過期/低品質/亂碼資料
- `GET /admin/email/status`：檢查郵件寄送設定與 Sender 驗證提示
- `POST /vc/profile` / `POST /vc/scout/run` / `POST /vc/scout/shortlist` / `POST /vc/outreach`
- `POST /vc/dd/report` / `GET /vc/dd/reports`
- `POST /dd/company/report/direct`：功能二，**必填公司官網 URL**，系統會先深爬官網再補外部公開資料
- `POST /grad/dd/run` / `POST /grad/dd/run_upload` / `GET /grad/dd/latest` / `GET /grad/dd/reports` / `POST /grad/dd/shortlist`
- `POST /dd/academic/report/direct`：輸入學校 / 教授 / 實驗室網址，直接生成學術 DD 報告
- `POST /dd/chat`：以 DD 報告為知識基礎問答
- `POST /dd/report/pdf`：下載公司/學術 DD PDF
- `GET /unsubscribe?token=...`：一鍵退訂
- `POST /webhooks/sendgrid`：處理 bounce/dropped/spamreport

## 上線建議
- API：Render / Fly.io / Railway（容器化）
- 前端：Vercel
- DB：Neon / Supabase Postgres
- 排程：同一台後端機器跑 `python -m backend.scheduler`（或拆成 Worker）

## 注意事項
- `backend/.env` 不要上傳 GitHub（`.gitignore` 已處理）
- 建議重新產生新的 DeepSeek / Google / SendGrid 金鑰
- `FRONTEND_CALLBACK_URL` 需指到前端網址（例如 `http://localhost:3000`）
- 若 API 顯示無資料，先確認：
  1. DB 是否啟動
  2. `python -m backend.pipeline` 是否成功
  3. 前端 `NEXT_PUBLIC_API_BASE` 是否指到 `http://localhost:8000`
- 郵件 DNS 與 webhook 設定請參考 `EMAIL_SETUP.md`
