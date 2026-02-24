import { useEffect, useMemo, useState } from 'react';
import AppShell from '../components/AppShell';
import { useAuth } from '../lib/useAuth';

function TitlePreview({ title, max = 88 }) {
  const [open, setOpen] = useState(false);
  const value = (title || '').trim();
  if (!value) return <h3>未命名</h3>;
  const tooLong = value.length > max;
  return (
    <div>
      <h3 className={tooLong && !open ? 'clamp2Title' : ''}>{value}</h3>
      {tooLong ? (
        <button className="btn ghost mini" onClick={() => setOpen((v) => !v)}>
          {open ? '收合標題' : '查看更多標題'}
        </button>
      ) : null}
    </div>
  );
}

export default function NewsPage() {
  const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
  const { user, logout } = useAuth();

  const [role, setRole] = useState('tech');
  const [insightDays, setInsightDays] = useState(14);
  const [eventDays, setEventDays] = useState(90);
  const [category, setCategory] = useState('all');
  const [data, setData] = useState({ insights: [], events: { taiwan: [], global: [] } });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const onLogin = () => {
    window.location.href = `${base}/auth/google/start?role=${role}`;
  };

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${base}/mvp?limit=60&role=${role}&insight_days=${insightDays}&event_days=${eventDays}`);
      const payload = await res.json();
      if (!res.ok) {
        throw new Error(payload?.detail || `API ${res.status}`);
      }
      setData(payload);
    } catch (err) {
      setError(err.message || '載入失敗');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [role, insightDays, eventDays]);

  const merged = useMemo(() => {
    const insightRows = (data.insights || []).map((x) => ({ ...x, kind: x.content_type || 'insight' }));
    const eventRows = [
      ...((data?.events?.taiwan || []).map((x) => ({ ...x, kind: 'event', regionLabel: '台灣' }))),
      ...((data?.events?.global || []).map((x) => ({ ...x, kind: 'event', regionLabel: '全球' }))),
    ];
    const rows = [...insightRows, ...eventRows];

    if (category === 'all') return rows;
    if (category === 'event') return rows.filter((x) => x.kind === 'event');
    return rows.filter((x) => x.kind === category);
  }, [data, category]);

  return (
    <AppShell
      title="新知中心"
      subtitle="可切換：論文 / 貼文 / 活動。角色（商業/VC/技術）改為篩選選項。"
      user={user}
      onLogin={onLogin}
      onLogout={logout}
    >
      <section className="panel card controls">
        <div>
          <label>角色</label>
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="tech">技術</option>
            <option value="biz">商業</option>
            <option value="vc">VC</option>
          </select>
        </div>
        <div>
          <label>新知回溯天數</label>
          <select value={insightDays} onChange={(e) => setInsightDays(Number(e.target.value))}>
            <option value={7}>7 天</option>
            <option value={14}>14 天</option>
            <option value={21}>21 天</option>
            <option value={30}>30 天</option>
          </select>
        </div>
        <div>
          <label>活動未來天數</label>
          <select value={eventDays} onChange={(e) => setEventDays(Number(e.target.value))}>
            <option value={30}>30 天</option>
            <option value={60}>60 天</option>
            <option value={90}>90 天</option>
          </select>
        </div>
        <div>
          <label>分類</label>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="all">全部</option>
            <option value="paper">論文</option>
            <option value="post">貼文</option>
            <option value="web">網站</option>
            <option value="event">活動</option>
          </select>
        </div>
        <button className="btn" onClick={load}>{loading ? '更新中...' : '重新整理'}</button>
      </section>

      {error && <p className="muted">{error}</p>}

      <section className="panel cardGrid">
        {merged.length === 0 && <div className="card">目前沒有資料，請先跑 pipeline。</div>}
        {merged.map((item, idx) => (
          <article key={`${item.id || item.url || idx}`} className="card itemCard">
            <div className="metaLine">
              <span className="tag">{item.kind === 'event' ? '活動' : item.kind || '新知'}</span>
              {item.regionLabel && <span className="tag ghostTag">{item.regionLabel}</span>}
              <span className="score">分數 {item.final_score || item.score || '-'}</span>
            </div>
            <TitlePreview title={item.title} />
            {item.start_at && <p className="muted">時間：{item.start_at}</p>}
            <p className="clamp3">{item.summary || item.description || item.why_it_matters || '暫無摘要'}</p>
            {(item.summary || item.description || '').length > 140 && (
              <details>
                <summary>查看更多</summary>
                <p>{item.summary || item.description}</p>
              </details>
            )}
            <a href={item.url || '#'} target="_blank" rel="noreferrer">原文連結 ↗</a>
          </article>
        ))}
      </section>
    </AppShell>
  );
}
