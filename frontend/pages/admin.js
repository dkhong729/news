import { useEffect, useState } from 'react';
import AppShell from '../components/AppShell';
import { useAuth } from '../lib/useAuth';

function parseCsv(text) {
  return String(text || '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
}

function SimpleTable({ rows, columns }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => <th key={c.key}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {(rows || []).length ? (
            rows.map((row, idx) => (
              <tr key={row.id || `${idx}-${row.url || row.title || ''}`}>
                {columns.map((c) => (
                  <td key={c.key}>
                    {c.render ? c.render(row) : (row[c.key] ?? '-')}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={columns.length} className="muted">無資料</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

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
  const [audit, setAudit] = useState(null);
  const [cleanupResult, setCleanupResult] = useState(null);
  const [govResources, setGovResources] = useState([]);
  const [govResourceCount, setGovResourceCount] = useState(0);
  const [govRunResult, setGovRunResult] = useState(null);
  const [govYearsBack, setGovYearsBack] = useState(5);
  const [govCategoriesText, setGovCategoriesText] = useState('gov_award,gov_subsidy,incubator_space,exhibitor_list,exhibit_schedule');
  const [govIncludeSearch, setGovIncludeSearch] = useState(true);
  const [loadingOps, setLoadingOps] = useState({ cleanup: false, govRun: false });

  const onLogin = () => {
    window.location.href = `${base}/auth/google/start?role=tech`;
  };

  const load = async () => {
    if (!user || !isAllowlisted) return;
    setError('');
    try {
      const currentYear = new Date().getFullYear();
      const [meRes, subRes, emailRes, auditRes, govRes] = await Promise.all([
        fetch(`${base}/auth/me`, { headers: authHeaders }),
        fetch(`${base}/admin/subscribers?limit=300`, { headers: authHeaders }),
        fetch(`${base}/admin/email/status`, { headers: authHeaders }),
        fetch(`${base}/admin/maintenance/audit?limit=8`, { headers: authHeaders }),
        fetch(`${base}/admin/gov-resources?limit=120&year_from=${currentYear - 4}`, { headers: authHeaders }),
      ]);

      const meData = await meRes.json().catch(() => ({}));
      const subData = await subRes.json().catch(() => ({}));
      const emailData = await emailRes.json().catch(() => ({}));
      const auditData = await auditRes.json().catch(() => ({}));
      const govData = await govRes.json().catch(() => ({}));

      if (!meRes.ok) throw new Error(meData?.detail || '無法讀取登入資訊');
      if (!subRes.ok) throw new Error(subData?.detail || '無法讀取訂閱者');
      if (!emailRes.ok) throw new Error(emailData?.detail || '無法讀取郵件設定狀態');
      if (!auditRes.ok) throw new Error(auditData?.detail || '無法讀取清洗稽核報表');
      if (!govRes.ok) throw new Error(govData?.detail || '無法讀取政府資源資料倉');

      setMe(meData);
      setSubscribers(subData.items || []);
      setEmailStatus(emailData || null);
      setAudit(auditData.audit || null);
      setGovResources(govData.items || []);
      setGovResourceCount(govData.count || 0);
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
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || '更新失敗');
      await load();
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
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || '在地化失敗');
      setError(`在地化完成：insights=${data.insights_localized}, events=${data.events_localized}`);
      await load();
    } catch (err) {
      setError(err.message || '在地化失敗');
    }
  };

  const previewNewsletter = async () => {
    try {
      if (!subscribers.length) return;
      const targetId = subscribers[0].user_id;
      const res = await fetch(`${base}/admin/newsletter/preview?user_id=${targetId}&role=tech`, { headers: authHeaders });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || '預覽失敗');
      setPreviewHtml(data.html || '');
    } catch (err) {
      setError(err.message || '預覽失敗');
    }
  };

  const runCleanup = async () => {
    setLoadingOps((s) => ({ ...s, cleanup: true }));
    setError('');
    try {
      const res = await fetch(`${base}/admin/maintenance/cleanup`, {
        method: 'POST',
        headers: authHeaders,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || '資料清洗失敗');
      setCleanupResult(data.cleanup || null);
      setAudit(data.audit || null);
      await load();
    } catch (err) {
      setError(err.message || '資料清洗失敗');
    } finally {
      setLoadingOps((s) => ({ ...s, cleanup: false }));
    }
  };

  const runGovResourceScout = async () => {
    setLoadingOps((s) => ({ ...s, govRun: true }));
    setError('');
    try {
      const res = await fetch(`${base}/admin/gov-resources/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({
          years_back: Math.max(1, Math.min(10, Number(govYearsBack) || 5)),
          categories: parseCsv(govCategoriesText),
          include_search: !!govIncludeSearch,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || '政府資源整理失敗');
      setGovRunResult(data);
      await load();
    } catch (err) {
      setError(err.message || '政府資源整理失敗');
    } finally {
      setLoadingOps((s) => ({ ...s, govRun: false }));
    }
  };

  return (
    <AppShell
      title="後台管理"
      subtitle="管理訂閱者、郵件投遞、資料清洗與政府/展會名單資料倉。"
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
            <button className="btn ghost" onClick={runCleanup} disabled={loadingOps.cleanup}>
              {loadingOps.cleanup ? '清洗中...' : '執行資料清洗'}
            </button>
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

      {audit && isAllowlisted && (
        <section className="panel card">
          <h3>內容清洗稽核報表</h3>
          <div className="metaLine">
            <span className="tag">活動標題異常 {audit.event_title_issues || 0}</span>
            <span className="tag ghostTag">活動過長標題 {audit.event_title_too_long || 0}</span>
            <span className="tag ghostTag">活動亂碼標題 {audit.event_title_mojibake || 0}</span>
            <span className="tag">新知標題異常 {audit.insight_title_issues || 0}</span>
            <span className="tag ghostTag">新知過長標題 {audit.insight_title_too_long || 0}</span>
            <span className="tag ghostTag">新知亂碼標題 {audit.insight_title_mojibake || 0}</span>
            <span className="tag">列表頁活動數 {audit.listing_event_count || 0}</span>
          </div>

          {cleanupResult && (
            <p className="muted">
              上次清洗：列表頁刪除 {cleanupResult.events_deleted_listing_pages || 0}，低品質活動刪除 {cleanupResult.events_deleted_low_quality || 0}，
              低品質新知刪除 {cleanupResult.insights_deleted_low_quality || 0}，孤兒 raw_items 刪除 {cleanupResult.raw_items_deleted_orphan || 0}
            </p>
          )}

          <h4 style={{ marginTop: 16, marginBottom: 8 }}>列表頁活動樣本</h4>
          <SimpleTable
            rows={audit.listing_event_samples || []}
            columns={[
              { key: 'id', label: 'ID' },
              { key: 'title', label: '標題', render: (r) => <span title={r.title}>{r.title || '-'}</span> },
              { key: 'url', label: 'URL', render: (r) => r.url ? <a href={r.url} target="_blank" rel="noreferrer">開啟</a> : '-' },
              { key: 'score', label: '分數' },
            ]}
          />

          <h4 style={{ marginTop: 16, marginBottom: 8 }}>異常活動標題樣本</h4>
          <SimpleTable
            rows={audit.event_samples || []}
            columns={[
              { key: 'id', label: 'ID' },
              { key: 'title', label: '標題', render: (r) => <span title={r.title}>{r.title || '-'}</span> },
              { key: 'url', label: 'URL', render: (r) => r.url ? <a href={r.url} target="_blank" rel="noreferrer">開啟</a> : '-' },
              { key: 'score', label: '分數' },
            ]}
          />

          <h4 style={{ marginTop: 16, marginBottom: 8 }}>異常新知標題樣本</h4>
          <SimpleTable
            rows={audit.insight_samples || []}
            columns={[
              { key: 'id', label: 'ID' },
              { key: 'title', label: '標題', render: (r) => <span title={r.title}>{r.title || '-'}</span> },
              { key: 'url', label: 'URL', render: (r) => r.url ? <a href={r.url} target="_blank" rel="noreferrer">開啟</a> : '-' },
              { key: 'final_score', label: '分數' },
            ]}
          />
        </section>
      )}

      {isAllowlisted && (
        <section className="panel card">
          <h3>政府獎項 / 補助 / 展會名單資料倉</h3>
          <p className="muted">用途：整理過去 5 年政府資源名單與展會參展商/展期資料，提供 DD 功能一（海量搜）直接使用。</p>

          <div className="controls">
            <div>
              <label className="fieldLabel"><span>回溯年數</span></label>
              <input type="number" min={1} max={10} value={govYearsBack} onChange={(e) => setGovYearsBack(e.target.value)} />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <label className="fieldLabel"><span>分類（逗號分隔）</span></label>
              <input value={govCategoriesText} onChange={(e) => setGovCategoriesText(e.target.value)} />
              <p className="muted">可用：gov_award, gov_subsidy, incubator_space, exhibitor_list, exhibit_schedule</p>
            </div>
            <div className="radioRow">
              <input id="gov-search" type="checkbox" checked={govIncludeSearch} onChange={(e) => setGovIncludeSearch(e.target.checked)} />
              <label htmlFor="gov-search">啟用搜尋補抓（DuckDuckGo）</label>
            </div>
          </div>

          <div className="btnRow">
            <button className="btn" onClick={runGovResourceScout} disabled={loadingOps.govRun}>
              {loadingOps.govRun ? '整理中...' : '執行 Gov Resource Scout'}
            </button>
            <button className="btn ghost" onClick={load}>重新載入列表</button>
          </div>

          {govRunResult && (
            <div className="progressHistory" style={{ marginTop: 10 }}>
              <div className="metaLine">
                <span className="tag">years_back {govRunResult.years_back}</span>
                <span className="tag ghostTag">year_floor {govRunResult.year_floor}</span>
                <span className="tag">inserted_attempts {govRunResult.inserted_attempts || 0}</span>
              </div>
              <p className="muted">分類統計：{Object.entries(govRunResult.sample_counts || {}).map(([k, v]) => `${k}:${v}`).join(' / ') || '無'}</p>
              <pre className="monoBox" style={{ maxHeight: 220, overflow: 'auto' }}>
                {(govRunResult.trace || []).slice(0, 30).map((t) => JSON.stringify(t)).join('\n')}
              </pre>
            </div>
          )}

          <p className="muted" style={{ marginTop: 10 }}>資料筆數（總計）：{govResourceCount}</p>
          <SimpleTable
            rows={govResources}
            columns={[
              { key: 'id', label: 'ID' },
              { key: 'record_type', label: '類型' },
              { key: 'source_category', label: '來源分類' },
              { key: 'year', label: '年度' },
              { key: 'program_name', label: '方案/展會', render: (r) => <span title={r.program_name || r.event_name}>{r.program_name || r.event_name || '-'}</span> },
              { key: 'company_name', label: '公司/團隊', render: (r) => <span title={r.company_name || r.organization_name}>{r.company_name || r.organization_name || '-'}</span> },
              { key: 'award_name', label: '獎項/補助', render: (r) => r.award_name || r.subsidy_name || '-' },
              { key: 'booth_no', label: '攤位' },
              { key: 'url', label: '連結', render: (r) => r.url ? <a href={r.url} target="_blank" rel="noreferrer">開啟</a> : '-' },
            ]}
          />
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
