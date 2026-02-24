import { useEffect, useState } from 'react';
import AppShell from '../components/AppShell';
import { useAuth } from '../lib/useAuth';

export default function AdminPage() {
  const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
  const { user, logout, authHeaders } = useAuth();
  const allowlist = new Set(['dkhong0729@gmail.com', 'yoshikuni2046@gmail.com']);
  const isAllowlisted = !!user && allowlist.has(String(user.email || '').toLowerCase());

  const [subscribers, setSubscribers] = useState([]);
  const [error, setError] = useState('');
  const [me, setMe] = useState(null);
  const [emailStatus, setEmailStatus] = useState(null);
  const [previewHtml, setPreviewHtml] = useState('');

  const onLogin = () => {
    window.location.href = `${base}/auth/google/start?role=tech`;
  };

  const load = async () => {
    if (!user || !isAllowlisted) return;
    setError('');
    try {
      const meRes = await fetch(`${base}/auth/me`, { headers: authHeaders });
      const meData = await meRes.json();
      if (!meRes.ok) throw new Error(meData?.detail || '無法讀取登入資訊');
      setMe(meData);

      const res = await fetch(`${base}/admin/subscribers?limit=300`, { headers: authHeaders });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || '無法讀取訂閱者');
      setSubscribers(data.items || []);

      const emailRes = await fetch(`${base}/admin/email/status`, { headers: authHeaders });
      const emailData = await emailRes.json();
      if (emailRes.ok) {
        setEmailStatus(emailData);
      }
    } catch (err) {
      setError(err.message || '載入失敗');
    }
  };

  useEffect(() => {
    load();
  }, [user, isAllowlisted]);

  const toggleSub = async (item) => {
    try {
      const res = await fetch(`${base}/admin/subscribers/${item.user_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ subscribe_daily: !item.subscribe_daily }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || '更新失敗');
      load();
    } catch (err) {
      setError(err.message || '更新失敗');
    }
  };

  const localize = async () => {
    try {
      const res = await fetch(`${base}/admin/localize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ limit_insights: 300, limit_events: 300 }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || '在地化失敗');
      setError(`在地化完成：insights=${data.insights_localized}, events=${data.events_localized}`);
    } catch (err) {
      setError(err.message || '在地化失敗');
    }
  };

  const previewNewsletter = async () => {
    try {
      if (!subscribers.length) return;
      const targetId = subscribers[0].user_id;
      const res = await fetch(`${base}/admin/newsletter/preview?user_id=${targetId}&role=tech`, { headers: authHeaders });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || '預覽失敗');
      setPreviewHtml(data.html || '');
    } catch (err) {
      setError(err.message || '預覽失敗');
    }
  };

  return (
    <AppShell
      title="後台管理"
      subtitle="管理訂閱者、訂閱狀態與內容在地化。"
      user={user}
      onLogin={onLogin}
      onLogout={logout}
    >
      {!user && <p className="muted">請先登入管理員帳號。</p>}
      {user && !isAllowlisted && <p className="errorText">你不在後台白名單內，無法使用管理功能。</p>}
      {error && <p className="muted">{error}</p>}

      {me && isAllowlisted && (
        <section className="panel card">
          <h3>目前登入資訊</h3>
          <p className="muted">user_id: {me.user_id} / role: {me.role}</p>
          <p className="muted">permissions: {(me.permissions || []).join(', ')}</p>
          <div className="btnRow">
            <button className="btn ghost" onClick={localize}>將舊資料轉為中文</button>
            <button className="btn ghost" onClick={previewNewsletter}>預覽電子報</button>
          </div>
        </section>
      )}

      {emailStatus && isAllowlisted && (
        <section className="panel card">
          <h3>郵件設定狀態</h3>
          <p className="muted">Provider: {emailStatus.provider}</p>
          <p className="muted">From: {emailStatus.from_email || '-'}</p>
          <p className="muted">API Key 已設定：{emailStatus.api_key_configured ? '是' : '否'}</p>
          <p className="muted">{emailStatus.next_step}</p>
          <p className="muted">
            Sender/Domain 驗證說明：
            <a href="https://docs.sendgrid.com/for-developers/sending-email/sender-identity" target="_blank" rel="noreferrer">
              SendGrid Sender Identity
            </a>
          </p>
        </section>
      )}

      {isAllowlisted && (
      <section className="panel card">
        <h3>訂閱者管理</h3>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Email</th>
                <th>Role</th>
                <th>訂閱</th>
                <th>Email 有效</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {subscribers.map((s) => (
                <tr key={s.user_id}>
                  <td>{s.user_id}</td>
                  <td>{s.email}</td>
                  <td>{s.role}</td>
                  <td>{s.subscribe_daily ? '是' : '否'}</td>
                  <td>{s.is_email_valid ? '是' : '否'}</td>
                  <td>
                    <button className="btn mini" onClick={() => toggleSub(s)}>
                      {s.subscribe_daily ? '停用' : '啟用'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      )}

      {previewHtml && isAllowlisted && (
        <section className="panel card">
          <h3>電子報預覽</h3>
          <iframe title="newsletter-preview" srcDoc={previewHtml} style={{ width: '100%', minHeight: 600, border: '1px solid #dbe3ec', borderRadius: 10 }} />
        </section>
      )}
    </AppShell>
  );
}
