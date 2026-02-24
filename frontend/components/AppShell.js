import Link from 'next/link';

export default function AppShell({ title, subtitle, user, onLogin, onLogout, children }) {
  const adminAllow = new Set(['dkhong0729@gmail.com', 'yoshikuni2046@gmail.com']);
  const canSeeAdmin = !!user && adminAllow.has(String(user.email || '').toLowerCase());
  return (
    <div className="appWrap">
      <header className="topBar">
        <div className="brandRow">
          <Link href="/" className="brandLink">
            <img src="/logo.svg" alt="AI Insight Pulse" className="brandLogo" />
            <div className="brandText">
              <strong>AI Insight Pulse</strong>
              <span>高信號 AI 情報</span>
            </div>
          </Link>
          <nav className="mainNav">
            <Link href="/">首頁</Link>
            <Link href="/news">新知</Link>
            <Link href="/dd">DD</Link>
            {canSeeAdmin && <Link href="/admin">後台</Link>}
          </nav>
        </div>
        <div className="authBox">
          {user ? (
            <>
              <div className="userChip">
                <div>{user.displayName || user.email || `使用者 #${user.userId}`}</div>
                <small>角色：{user.role}</small>
              </div>
              <button className="btn ghost" onClick={onLogout}>登出</button>
            </>
          ) : (
            <button className="btn" onClick={onLogin}>使用 Google 登入</button>
          )}
        </div>
      </header>

      <section className="pageHero">
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </section>

      <main>{children}</main>
    </div>
  );
}
