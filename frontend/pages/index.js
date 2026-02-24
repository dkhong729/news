import { useState } from 'react';
import Link from 'next/link';
import AppShell from '../components/AppShell';
import { useAuth } from '../lib/useAuth';

export default function HomePage() {
  const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
  const { user, logout } = useAuth();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('tech');
  const [status, setStatus] = useState('');

  const onLogin = () => {
    window.location.href = `${base}/auth/google/start?role=${role}`;
  };

  const onSubscribe = async () => {
    setStatus('');
    try {
      const res = await fetch(`${base}/subscribe_email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, role, subscribe_daily: true, send_now: true }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || '訂閱失敗');
      }
      if (data.warning) {
        setStatus(data.warning);
      } else if (data.sent) {
        const msgId = data?.send_result?.message_id ? ` message_id=${data.send_result.message_id}` : '';
        setStatus(`訂閱成功，已立即寄送。${msgId}`);
      } else {
        setStatus('訂閱成功，稍後寄送。');
      }
    } catch (err) {
      setStatus(err.message || '訂閱失敗');
    }
  };

  return (
    <AppShell
      title="AI 情報聚合平台"
      subtitle="每 6 小時更新 AI 新知與活動，支援公司/學術 DD、每日電子報與安全登入。"
      user={user}
      onLogin={onLogin}
      onLogout={logout}
    >
      <section className="panel grid2">
        <div className="card">
          <h3>產品能力</h3>
          <ul className="plainList">
            <li>自動抓取 AI 新知 + 活動，排序與摘要。</li>
            <li>公司 DD + 學術 DD 同一介面，支援聊天與 PDF。</li>
            <li>每日 08:00 電子報，並可一鍵退訂。</li>
          </ul>
          <div className="btnRow">
            <Link href="/news" className="btn">前往新知</Link>
            <Link href="/dd" className="btn ghost">前往 DD</Link>
          </div>
        </div>

        <div className="card">
          <h3>訂閱每日電子報</h3>
          <p className="muted">僅支援 Gmail。若寄件失敗，會回傳具體錯誤原因。</p>
          <label>角色偏好</label>
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="tech">技術</option>
            <option value="biz">商業</option>
            <option value="vc">VC</option>
          </select>
          <label>Gmail</label>
          <input placeholder="your@gmail.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button className="btn" onClick={onSubscribe}>立即訂閱</button>
          {status && <p className="muted">{status}</p>}
        </div>
      </section>

      <section className="panel contactBox">
        <h3>聯絡我們</h3>
        <p>有任何問題請聯繫：<a href="mailto:yoshikuni2046@gmail.com">yoshikuni2046@gmail.com</a></p>
      </section>
    </AppShell>
  );
}
