# 產品現況與上線差距（2026-02）

## 已完成功能
- AI 新知/活動資料管線：多來源爬取、去重、分類、評分、摘要、入庫 PostgreSQL
- 6 小時自動更新與 08:00 每日寄送排程（scheduler）
- Google Gmail OAuth 登入、Gmail 訂閱、即時寄送摘要
- 首頁角色化視圖（VC/商業/技術）與時間窗調整
- 管理端 CRUD：活動與新知可查、可改、可刪
- VC Scout：候選團隊生成、shortlist、外聯草稿、meeting 提案
- VC DD：可對候選公司生成 DD 報告（公開訊號整合 + 額外網址）
- 學術 DD：履歷 + 目標學校 -> 實驗室候選 + DD 報告（支援 txt/md/pdf 上傳）
- 安全加固：
  - JWT permissions claims
  - RBAC（User -> Roles -> Permissions）
  - `/admin/*` middleware 權限攔截
  - IP/User Rate Limit + WAF + Redis 黑名單
- 觀測與告警：
  - Sentry（後端）
  - pipeline run 寫入 DB + Slack Webhook 通知
  - SendGrid bounce webhook 自動標記無效信箱
- 爬蟲韌性：
  - 指數退避重試
  - 快取降級
  - 來源健康度紀錄
  - 代理池輪替（`PROXY_POOL_URLS`）
- 郵件投遞：
  - List-Unsubscribe / One-Click
  - 退訂連結與後端退訂端點

## 上線前仍需補齊（P0）
- 資安補強
  - `/admin/*` 已有 RBAC，但仍需補「敏感操作審計日誌」與「API key 輪替流程」
- 後端防護進階
  - 目前已有 app 層 WAF/rate-limit，正式環境仍建議加上 Cloudflare/AWS WAF 與 CDN
- 觀測性進階
  - 目前已有 Sentry 與 pipeline webhook，仍需補 Dashboard（成功率、延遲、錯誤分佈）
- 爬蟲穩定性進階
  - 目前已有退避/快取降級/健康度，仍需逐站調教 selector 與來源分級策略
- 資料品質
  - 日期抽取準確率、活動去重規則、報告引用來源完整性
- 郵件品質
  - SPF/DKIM/DMARC 仍需在你的 DNS 端完成，並持續監控寄送配額告警

## 第二階段建議（P1）
- 多租戶與團隊協作（組織、成員、共享 watchlist）
- VC 自動外聯閉環（回覆追蹤、會議排程整合 Google Calendar）
- 學術 DD 強化（教授論文近況、招生偏好、歷年錄取背景）
- LLM 成本與品質控制（快取、批次推理、版本 A/B）

## 雲端部署建議
- 前端：Vercel
- 後端 API：Render / Railway / Fly.io（容器）
- 排程 Worker：同平台第二個 service，啟動 `python -m backend.scheduler`
- 資料庫：Neon/Supabase Postgres
- Secrets：平台環境變數（勿寫進 repo）

## 最小可上線流程
1. 建立雲端 Postgres，設定 `DATABASE_URL`
2. 部署 backend API，設定所有環境變數
3. 執行 `python -c "from backend.db import init_db; init_db()"`
4. 執行一次 `python -m backend.pipeline` 建立初始資料
5. 部署 frontend（`NEXT_PUBLIC_API_BASE` 指向 backend）
6. 部署 scheduler worker
7. 用監控檢查：`/health`、pipeline 寫入量、08:00 郵件成功率
