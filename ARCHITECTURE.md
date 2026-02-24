# AI Insight Pulse 系統架構

## 1. 目標
- 從高信號來源彙整 AI 新知與 AI / 新創活動
- 以可解釋打分排序，支援決策者快速判斷
- 以資料庫為單一真實來源，前端不讀本地 JSON

## 2. 資料流程（每 6 小時）
1. 來源選擇
   - 內建來源（約 80%）
   - 使用者新增來源（約 20%，來自 `user_sources`）
2. 爬取
   - 以 `mvp_scraper.py` 抓取標題/連結/日期
3. 時間窗過濾
   - `paper`: 預設過去 14 天
   - `post`: 預設過去 7 天
   - `event`: 預設未來 90 天
   - `web`: 預設前後 7 天
4. 去重
   - `normalize_url + title` 去重
5. 分類
   - 活動 / 新知
   - 台灣活動 / 全球活動
6. 摘要與打分
   - LLM 摘要（可選，DeepSeek）
   - 分數組成：新鮮度、來源權威、訊號強度、多樣性懲罰
7. 寫入 PostgreSQL
   - `raw_items` / `normalized_items` / `scores` / `events`

## 2.1 可調時間窗
- 前端可調 `insight_days`（新知回溯）與 `event_days`（活動未來天數）
- 後端 `POST /pipeline/run` 可帶入：
  - `paper_days`
  - `post_days`
  - `event_days`
  - `web_past_days`
  - `web_future_days`

## 3. 每日寄送（08:00）
- `scheduler.py` 每天 08:00 查詢訂閱者並寄送
- 訂閱者來自 `user_preferences.subscribe_daily = true`
- 首次訂閱可立即寄送一封
- 郵件含 `List-Unsubscribe` / `One-Click`，支援退訂 token
- SendGrid webhook 退信會自動標記 `users.is_email_valid = false`

## 4. 身份驗證與安全
- Google OAuth（僅允許已驗證 Gmail）
- 以 `auth_audit_logs` 實作 IP / Email 節流
- JWT (`HS256`) 簽發 API Token（包含 `permissions` claims）
- RBAC：`users -> user_roles -> roles -> role_permissions -> permissions`
- `/admin/*` 由 middleware 預先攔截，依 `admin_read/admin_write` 判斷
- 後台再加一層 email 白名單（`ADMIN_ALLOWLIST_EMAILS`）
- 全域安全 middleware：IP/User Rate Limit + WAF 規則 + 黑名單
- OAuth `state` 寫入 `oauth_states` 防重放
- Google callback 會導回前端 `FRONTEND_CALLBACK_URL` 並夾帶登入 token

## 4.1 VC Scout MVP
- 使用者建立 VC profile（基金名、thesis、stage、sector）
- 系統直接爬加速器 / Demo Day / 創業社群網站，產生 30-50 候選團隊（不依賴新知/論文資料表）
- 使用者選 10-15 shortlist
- 產生外聯信草稿並可銜接寄送/meeting 提案
- 可針對單一候選公司產生 VC DD 報告（公開訊號整合 + 風險與追問）
- 也支援直接輸入公司名稱或官網 URL 產生 DD 報告
  - 會彙整 DB 中的相關新知/活動（signal overview）
  - 可追加自訂網址補強 DD 證據

## 4.2 學術 DD MVP（碩博找實驗室）
- 使用者上傳履歷文字與目標學校
- 系統抓取公開 Lab / 研究群頁面，產生候選清單
- 依履歷關鍵字與研究興趣打分，輸出 10-15 建議申請對象
- 生成一份可讀的 DD 報告（摘要、建議、下一步）
- 支援 `.txt/.md/.pdf` 履歷上傳 API
- 也支援直接輸入學校 / 教授 / 實驗室網址產生學術 DD 報告

## 5. 主要資料表
- `users`, `user_identities`, `user_preferences`, `subscriptions`
- `user_sources`
- `raw_items`, `normalized_items`, `scores`
- `events`
- `auth_audit_logs`, `oauth_states`
- `vc_profiles`, `vc_candidates`, `vc_dd_reports`
- `grad_dd_profiles`, `grad_lab_candidates`, `grad_dd_reports`

## 6. API 介面
- `GET /mvp`: 前端首頁資料
- `POST /pipeline/run`: 立即重跑 pipeline
- `POST /subscribe_email`: 訂閱 + 立即寄送
- `GET /auth/google/start`, `GET /auth/google/callback`
- `GET/PATCH/DELETE /admin/events/*`
- `GET/PATCH/DELETE /admin/insights/*`
- `GET/PATCH /admin/subscribers*`
- `POST /admin/localize`
- `GET /admin/email/status`
- `POST /vc/dd/report`, `GET /vc/dd/reports`
- `POST /grad/dd/run`, `POST /grad/dd/run_upload`, `GET /grad/dd/latest`, `GET /grad/dd/reports`, `POST /grad/dd/shortlist`
- `POST /dd/chat`, `POST /dd/report/pdf`
- `GET /unsubscribe`, `POST /webhooks/sendgrid`

## 7. 部署建議
- 前端：Vercel
- 後端：Render / Fly.io / Railway
- DB：Neon / Supabase
- 排程：同後端 worker 跑 `python -m backend.scheduler`
- Redis：節流/黑名單共用狀態
- WAF：Cloudflare WAF / AWS WAF（建議正式環境必開）
- 觀測：Sentry + Slack Webhook（pipeline 成功/失敗）
