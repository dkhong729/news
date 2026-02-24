# 郵件投遞基礎設定

## DNS 必做
1. SPF：允許你的寄信服務（SendGrid/SES）
2. DKIM：在 DNS 加上服務商提供的 CNAME/TXT
3. DMARC：建議先 `p=none` 觀察，再升級 `p=quarantine/reject`

## SendGrid Sender / Domain 驗證（避免 403 Sender Identity）
1. 進入 SendGrid 後台：`Settings -> Sender Authentication`
2. 二選一（建議用網域驗證）：
   - 單一寄件者驗證：`Verify a Single Sender`
   - 網域驗證：`Authenticate Your Domain`
3. 若用網域驗證：
   - 在 DNS 新增 SendGrid 提供的 CNAME（通常是 `s1._domainkey`, `s2._domainkey` 等）
   - 回 SendGrid 按 `Verify`
4. 確認 `backend/.env`：
   - `EMAIL_FROM` 必須是已驗證寄件者或該驗證網域底下地址（例如 `digest@yourdomain.com`）
   - `EMAIL_REPLY_TO` 建議填可收信地址
5. 完成後再測：
   - `POST /subscribe_email`（`send_now=true`）
   - 不再出現 `from address does not match a verified Sender Identity` 即成功

範例：
- SPF (`TXT @`): `v=spf1 include:sendgrid.net ~all`
- DMARC (`TXT _dmarc`): `v=DMARC1; p=none; rua=mailto:dmarc@yourdomain.com; fo=1`

## Webhook
- SendGrid Event Webhook: `POST https://<api-domain>/webhooks/sendgrid`
- 請加自訂標頭：`x-webhook-secret: <SENDGRID_WEBHOOK_SECRET>`
- 事件建議勾選：`bounce`, `dropped`, `spamreport`, `blocked`

## 退訂
- 系統已自動加入：
  - `List-Unsubscribe` header
  - `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
  - 郵件內文退訂連結 `/unsubscribe?token=...`

## 環境變數
- `EMAIL_PROVIDER`, `EMAIL_API_KEY`, `EMAIL_FROM`, `EMAIL_REPLY_TO`
- `PUBLIC_API_BASE_URL`
- `SENDGRID_WEBHOOK_SECRET`
- `EMAIL_UNSUBSCRIBE_MAILTO`（可選）
