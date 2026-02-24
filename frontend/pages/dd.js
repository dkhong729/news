import { useEffect, useMemo, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import { useAuth } from '../lib/useAuth';

function parseList(text) {
  return (text || '').split(',').map((x) => x.trim()).filter(Boolean);
}

function HelpTip({ text }) {
  return (
    <span className="helpTip" title={text} aria-label={text}>?
    </span>
  );
}

function FieldLabel({ label, help }) {
  return (
    <label className="fieldLabel">
      <span>{label}</span>
      {help ? <HelpTip text={help} /> : null}
    </label>
  );
}

function Modal({ open, title, onClose, children }) {
  if (!open) return null;
  return (
    <div className="modalBackdrop" onClick={onClose}>
      <div className="modalPanel" onClick={(e) => e.stopPropagation()}>
        <div className="modalHead">
          <h3>{title}</h3>
          <button className="btn ghost mini" onClick={onClose}>關閉</button>
        </div>
        <div className="modalBody">{children}</div>
      </div>
    </div>
  );
}

function ExpandableText({ text, max = 220 }) {
  const [open, setOpen] = useState(false);
  const value = (text || '').trim();
  if (!value) return <p>無資料</p>;
  if (value.length <= max) return <p>{value}</p>;
  return (
    <div>
      <p>{open ? value : `${value.slice(0, max)}...`}</p>
      <button className="btn ghost mini" onClick={() => setOpen((v) => !v)}>
        {open ? '收合' : '展開更多'}
      </button>
    </div>
  );
}

export default function DDPage() {
  const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
  const { user, logout, authHeaders } = useAuth();

  const [mode, setMode] = useState('company');
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [logs, setLogs] = useState([]);
  const [progressPct, setProgressPct] = useState(0);
  const [progressHint, setProgressHint] = useState('');
  const progressTimerRef = useRef(null);

  const [showCompanyScoutModal, setShowCompanyScoutModal] = useState(false);
  const [showCompanyDirectModal, setShowCompanyDirectModal] = useState(false);
  const [showAcademicModal, setShowAcademicModal] = useState(false);

  const [vcFirmName, setVcFirmName] = useState('');
  const [vcThesis, setVcThesis] = useState('');
  const [vcStages, setVcStages] = useState('pre-seed,seed,series-a,series-b');
  const [vcSectors, setVcSectors] = useState('AI Agent,Enterprise AI,Developer Tools');
  const [vcDiscoverySources, setVcDiscoverySources] = useState(
    'https://appworks.tw/,https://garageplus.asia/,https://www.tta.tw/,https://meet.bnext.com.tw/,https://smartcity.org.tw/,https://www.energytaiwan.com.tw/,https://www.twtc.com.tw/zh-tw/exhibitionSchedule,https://www.tainex.com.tw/service/exhibitionschedule'
  );
  const [vcExtraUrls, setVcExtraUrls] = useState('');

  const [vcDirectCompanyName, setVcDirectCompanyName] = useState('');
  const [vcDirectCompanyUrl, setVcDirectCompanyUrl] = useState('');

  const [vcCandidates, setVcCandidates] = useState([]);
  const [companyReports, setCompanyReports] = useState([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState(null);
  const [selectedReportId, setSelectedReportId] = useState(null);

  const [gradResumeText, setGradResumeText] = useState('');
  const [gradInterests, setGradInterests] = useState('LLM,Agent,RAG');
  const [gradDegree, setGradDegree] = useState('master');
  const [gradDirectSchool, setGradDirectSchool] = useState('');
  const [gradDirectLabUrl, setGradDirectLabUrl] = useState('');
  const [gradDirectProfessor, setGradDirectProfessor] = useState('');
  const [gradCandidates, setGradCandidates] = useState([]);
  const [gradReports, setGradReports] = useState([]);
  const [selectedGradReportId, setSelectedGradReportId] = useState(null);

  const [chatQuestion, setChatQuestion] = useState('');
  const [chatAnswer, setChatAnswer] = useState('');
  const [companyReport, setCompanyReport] = useState(null);
  const [academicReport, setAcademicReport] = useState(null);

  const loginRole = useMemo(() => (mode === 'company' ? 'vc' : 'tech'), [mode]);

  const pushLog = (line) => setLogs((prev) => [...prev, line]);

  const startProgressTicker = () => {
    if (progressTimerRef.current) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
    let tick = 0;
    setProgressPct(2);
    setProgressHint('初始化爬蟲任務...');
    progressTimerRef.current = setInterval(() => {
      tick += 1;
      setProgressPct((prev) => Math.min(92, prev + (prev < 50 ? 4 : 2)));
      if (tick <= 4) setProgressHint('正在擴展官網路由與 sitemap...');
      else if (tick <= 10) setProgressHint('正在抓取內頁內容與關鍵欄位...');
      else setProgressHint('正在彙整公開資料並生成 DD 報告...');
    }, 1000);
  };

  const stopProgressTicker = (hint) => {
    if (progressTimerRef.current) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
    setProgressPct(100);
    setProgressHint(hint || '完成');
    setTimeout(() => setProgressPct(0), 1200);
  };

  const onLogin = () => {
    window.location.href = `${base}/auth/google/start?role=${loginRole}`;
  };

  const requireLogin = () => {
    if (!user) {
      setError('請先登入後再使用 DD 功能。');
      return false;
    }
    return true;
  };

  const parseApiError = (res, data, fallback) => {
    if (res.status === 403 && String(data?.detail || '').includes('vc_scout_run')) {
      return '你的帳號目前缺少「公司 DD」權限（vc_scout_run）。請重新登入一次，或請管理員檢查角色權限。';
    }
    return data?.detail || fallback;
  };

  const loadPersisted = async () => {
    if (!user) return;
    setError('');
    try {
      const [cRes, rRes, gRes] = await Promise.all([
        fetch(`${base}/vc/scout/candidates?user_id=${user.userId}&limit=80`, { headers: authHeaders }),
        fetch(`${base}/vc/dd/reports?user_id=${user.userId}&limit=40`, { headers: authHeaders }),
        fetch(`${base}/grad/dd/reports?user_id=${user.userId}&limit=30`, { headers: authHeaders }),
      ]);

      const cData = await cRes.json().catch(() => ({}));
      const rData = await rRes.json().catch(() => ({}));
      const gData = await gRes.json().catch(() => ({}));

      if (cRes.ok) {
        const items = cData?.items || [];
        setVcCandidates(items);
        if (items.length && !selectedCandidateId) {
          setSelectedCandidateId(items[0].id);
        }
      }
      if (rRes.ok) {
        const rows = rData?.reports || [];
        setCompanyReports(rows);
        if (rows.length) {
          setSelectedReportId(rows[0].id);
          setCompanyReport(rows[0].report_json || null);
          if (rows[0].candidate_id) setSelectedCandidateId(rows[0].candidate_id);
        }
      }
      if (gRes.ok) {
        setGradCandidates(gData?.candidates || []);
        const rows = gData?.reports || [];
        setGradReports(rows);
        if (rows.length) {
          setSelectedGradReportId(rows[0].id);
          setAcademicReport(rows[0].report_json || null);
        }
      }
    } catch (err) {
      setError(err.message || '載入歷史報告失敗');
    }
  };

  useEffect(() => {
    loadPersisted();
  }, [user?.userId]);

  useEffect(() => {
    return () => {
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
      }
    };
  }, []);

  const runCompanyScout = async () => {
    if (!requireLogin()) return;
    setRunning(true);
    startProgressTicker();
    setError('');
    setStatus('執行公司 Scout 中...');
    setLogs([]);

    try {
      pushLog('1/3 建立或更新 VC Profile');
      const profileRes = await fetch(`${base}/vc/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({
          user_id: user.userId,
          firm_name: vcFirmName || 'My VC Firm',
          thesis: vcThesis,
          preferred_stages: parseList(vcStages),
          preferred_sectors: parseList(vcSectors),
          preferred_geo: 'taiwan',
        }),
      });
      const profileData = await profileRes.json();
      if (!profileRes.ok) throw new Error(parseApiError(profileRes, profileData, '建立 VC Profile 失敗'));

      pushLog('2/3 執行 VC Scout（台灣新創候選）');
      const scoutRes = await fetch(`${base}/vc/scout/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({
          user_id: user.userId,
          target_count: 50,
          source_urls: parseList(vcDiscoverySources),
        }),
      });
      const scoutData = await scoutRes.json();
      if (!scoutRes.ok) throw new Error(parseApiError(scoutRes, scoutData, 'VC Scout 失敗'));

      pushLog('3/3 更新候選清單');
      setVcCandidates(scoutData?.candidates || []);
      if (scoutData?.candidates?.length) setSelectedCandidateId(scoutData.candidates[0].id);

      (scoutData?.trace || []).slice(0, 12).forEach((t) => {
        pushLog(`${t.source}：掃描 ${t.scanned}，納入 ${t.accepted}`);
      });

      setStatus(`完成：產生 ${scoutData?.generated || 0} 個候選團隊（來源網站 ${scoutData?.used_sources?.length || 0} 個）`);
      stopProgressTicker('VC Scout 已完成');
      setShowCompanyScoutModal(false);
      await loadPersisted();
    } catch (err) {
      setError(err.message || '公司 Scout 失敗');
    } finally {
      setRunning(false);
      stopProgressTicker('流程結束');
    }
  };

  const runCompanyDD = async () => {
    if (!requireLogin()) return;
    if (!selectedCandidateId) {
      setError('請先選擇一間候選公司。');
      return;
    }

    setRunning(true);
    startProgressTicker();
    setError('');
    setStatus('產生公司 DD 報告中...');
    setLogs([]);

    try {
      pushLog('1/2 蒐集公司公開資訊與交叉來源');
      const res = await fetch(`${base}/vc/dd/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({
          user_id: user.userId,
          candidate_id: selectedCandidateId,
          extra_urls: parseList(vcExtraUrls),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(parseApiError(res, data, '公司 DD 報告產生失敗'));

      pushLog('2/2 生成報告與風險摘要');
      setCompanyReport(data?.report_json || null);

      const trace = data?.trace || {};
      pushLog(`證據頁數：${trace.evidence_pages || 0}`);
      if (Array.isArray(trace.source_domains) && trace.source_domains.length) {
        pushLog(`證據來源：${trace.source_domains.join(', ')}`);
      }
      if (trace?.status_summary) {
        pushLog(`抓取狀態：${Object.entries(trace.status_summary).map(([k, v]) => `${k}:${v}`).join(' / ')}`);
      }
      if (Array.isArray(trace?.deep_research_trace) && trace.deep_research_trace.length) {
        trace.deep_research_trace.forEach((s) => {
          pushLog(`DeepResearch｜${s.stage || '-'}｜${s.status || '-'}${s.tasks ? `｜tasks:${s.tasks}` : ''}`);
        });
      }
      (trace?.crawl_steps || []).slice(0, 8).forEach((s) => {
        pushLog(`${s.status || 'unknown'}｜${s.url || '-'}`);
      });
      setStatus('公司 DD 報告已完成');
      stopProgressTicker('公司 DD 已完成');
      await loadPersisted();
    } catch (err) {
      setError(err.message || '公司 DD 失敗');
    } finally {
      setRunning(false);
      stopProgressTicker('流程結束');
    }
  };

  const runCompanyDirectReport = async () => {
    if (!requireLogin()) return;
    if (!vcDirectCompanyUrl.trim()) {
      setError('功能 2 請提供公司官網網址，系統會針對該網站與公開資料做完整 DD。');
      return;
    }

    setRunning(true);
    startProgressTicker();
    setError('');
    setStatus('建立直接 DD 報告中...');
    setLogs([]);

    try {
      pushLog('1/1 針對指定公司執行深度 DD');
      const res = await fetch(`${base}/dd/company/report/direct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({
          user_id: user.userId,
          company_name: vcDirectCompanyName || null,
          company_url: vcDirectCompanyUrl || null,
          extra_urls: parseList(vcExtraUrls),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(parseApiError(res, data, '直接 DD 失敗'));
      setCompanyReport(data?.report_json || null);
      const trace = data?.trace || {};
      if (trace?.status_summary) {
        pushLog(`抓取狀態：${Object.entries(trace.status_summary).map(([k, v]) => `${k}:${v}`).join(' / ')}`);
      }
      if (Array.isArray(trace?.deep_research_trace) && trace.deep_research_trace.length) {
        trace.deep_research_trace.forEach((s) => {
          pushLog(`DeepResearch｜${s.stage || '-'}｜${s.status || '-'}${s.tasks ? `｜tasks:${s.tasks}` : ''}`);
        });
      }
      (trace?.crawl_steps || []).slice(0, 8).forEach((s) => {
        pushLog(`${s.status || 'unknown'}｜${s.url || '-'}`);
      });
      setStatus('直接 DD 報告已完成');
      stopProgressTicker('直接 DD 已完成');
      setShowCompanyDirectModal(false);
      await loadPersisted();
    } catch (err) {
      setError(err.message || '直接 DD 失敗');
    } finally {
      setRunning(false);
      stopProgressTicker('流程結束');
    }
  };

  const runAcademicDirectReport = async () => {
    if (!requireLogin()) return;
    if (!gradDirectSchool.trim() && !gradDirectLabUrl.trim() && !gradDirectProfessor.trim()) {
      setError('學術 DD 至少需要：學校、實驗室網址、教授姓名其中一項。');
      return;
    }

    setRunning(true);
    startProgressTicker();
    setError('');
    setStatus('產生學術 DD 報告中...');
    setLogs([]);

    try {
      pushLog('1/1 掃描學校/實驗室/教授公開資訊');
      const res = await fetch(`${base}/dd/academic/report/direct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({
          user_id: user.userId,
          resume_text: gradResumeText || 'N/A',
          target_school: gradDirectSchool || null,
          lab_url: gradDirectLabUrl || null,
          professor_name: gradDirectProfessor || null,
          interests: parseList(gradInterests),
          degree_target: gradDegree,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || '學術 DD 失敗');

      setGradCandidates(data?.candidates || []);
      setAcademicReport(data?.report_json || null);
      setStatus(`學術 DD 完成：候選實驗室 ${data?.candidates?.length || 0} 筆`);
      stopProgressTicker('學術 DD 已完成');
      setShowAcademicModal(false);
      await loadPersisted();
    } catch (err) {
      setError(err.message || '學術 DD 失敗');
    } finally {
      setRunning(false);
      stopProgressTicker('流程結束');
    }
  };

  const askDD = async () => {
    if (!requireLogin()) return;
    if (!chatQuestion.trim()) return;

    setError('');
    setStatus('整理回答中...');
    try {
      const payload = {
        mode,
        user_id: user.userId,
        message: chatQuestion,
      };
      if (mode === 'company' && selectedCandidateId) {
        payload.candidate_id = selectedCandidateId;
      }

      const res = await fetch(`${base}/dd/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || 'DD 問答失敗');
      setChatAnswer(data?.answer || '');
      setStatus('回答完成');
    } catch (err) {
      setError(err.message || 'DD 問答失敗');
    }
  };

  const downloadPdf = async () => {
    if (!requireLogin()) return;

    setError('');
    setStatus('PDF 產生中...');
    try {
      const payload = { mode, user_id: user.userId };
      if (mode === 'company' && selectedCandidateId) {
        payload.candidate_id = selectedCandidateId;
      }

      const res = await fetch(`${base}/dd/report/pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.detail || 'PDF 下載失敗');
      }

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `dd-report-${mode}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
      setStatus('PDF 已下載');
    } catch (err) {
      setError(err.message || 'PDF 下載失敗');
    }
  };

  const selectCompanyReport = (reportId) => {
    setSelectedReportId(reportId);
    const hit = companyReports.find((x) => x.id === reportId);
    if (!hit) return;
    setCompanyReport(hit.report_json || null);
    if (hit.candidate_id) setSelectedCandidateId(hit.candidate_id);
  };

  const selectGradReport = (reportId) => {
    setSelectedGradReportId(reportId);
    const hit = gradReports.find((x) => x.id === reportId);
    if (!hit) return;
    setAcademicReport(hit.report_json || null);
  };

  const renderCompanyReportPreview = () => {
    if (!companyReport) return <p className="muted">尚未產生公司 DD 報告。</p>;
    const snapshot = companyReport.company_snapshot || {};
    const sectionRows = [
      ['商業與營運調查', companyReport.commercial_dd || companyReport.market_competition || ''],
      ['產品與技術調查', companyReport.technology_dd || companyReport.product_tech || ''],
      ['團隊能力調查', companyReport.management_dd || companyReport.team_traction || ''],
      ['財務與稅務調查', companyReport.financial_dd || ''],
      ['法律與合約調查', companyReport.legal_esg_dd || ''],
    ].filter((x) => (x[1] || '').trim().length > 0);

    const citations = (companyReport.research_citations || []).slice(0, 12);

    return (
      <div className="reportPreview">
        <h4>{companyReport.title || '公司 DD 報告'}</h4>
        <p className="muted">{companyReport.executive_summary || '無摘要'}</p>

        <div className="previewGrid">
          <div><strong>公司：</strong>{snapshot.name || '-'}</div>
          <div><strong>階段：</strong>{snapshot.stage || '-'}</div>
          <div><strong>領域：</strong>{snapshot.sector || '-'}</div>
          <div>
            <strong>來源：</strong>
            {snapshot.source ? <a href={snapshot.source} target="_blank" rel="noreferrer">{snapshot.source}</a> : '-'}
          </div>
        </div>

        {sectionRows.map(([label, text]) => (
          <div key={label}>
            <h5>{label}</h5>
            <ExpandableText text={text} />
          </div>
        ))}

        <h5>風險</h5>
        <ul className="plainList">
          {(companyReport.risks || []).map((x, i) => <li key={`risk-${i}`}>{x}</li>)}
        </ul>

        {!!(companyReport.relation_hypotheses || []).length && (
          <>
            <h5>關聯假設</h5>
            <ul className="plainList">
              {(companyReport.relation_hypotheses || []).map((x, i) => <li key={`rel-${i}`}>{x}</li>)}
            </ul>
          </>
        )}

        {!!(companyReport.dd_checklist_pending || []).length && (
          <>
            <h5>待補文件清單</h5>
            <ul className="plainList">
              {(companyReport.dd_checklist_pending || []).map((x, i) => <li key={`todo-${i}`}>{x}</li>)}
            </ul>
          </>
        )}

        <h5>建議追問</h5>
        <ul className="plainList">
          {(companyReport.key_questions || []).map((x, i) => <li key={`q-${i}`}>{x}</li>)}
        </ul>

        {!!citations.length && (
          <>
            <h5>深度研究引用</h5>
            <ul className="plainList">
              {citations.map((c, i) => (
                <li key={`ct-${i}`}>
                  <a href={c.url} target="_blank" rel="noreferrer">{c.title || c.url}</a>
                  {c.task_name ? `（${c.task_name}）` : ''}
                </li>
              ))}
            </ul>
          </>
        )}

        <h5>爬蟲證據</h5>
        {companyReport?.crawl_warning ? <p className="errorText">{companyReport.crawl_warning}</p> : null}
        <p className="muted">
          頁數：{companyReport?.crawl_trace?.accepted_pages || (companyReport?.evidence_pages || []).length || 0}
          {' '}｜耗時：{companyReport?.crawl_trace?.elapsed_sec || '-'} 秒
          {' '}｜啟用搜尋：{companyReport?.crawl_trace?.used_web_search ? '是' : '否'}
        </p>
        {companyReport?.evidence_metrics ? (
          <p className="muted">
            外部來源：{companyReport.evidence_metrics.external_pages || 0}
            {' '}｜工商來源：{companyReport.evidence_metrics.registry_pages || 0}
          </p>
        ) : null}
        {companyReport?.crawl_trace?.status_summary ? (
          <p className="muted">
            狀態：{Object.entries(companyReport.crawl_trace.status_summary).map(([k, v]) => `${k}:${v}`).join(' / ')}
          </p>
        ) : null}
        <ul className="plainList">
          {(companyReport.evidence_pages || []).slice(0, 10).map((e, i) => (
            <li key={`ev-${i}`}>
              <a href={e.url} target="_blank" rel="noreferrer">{e.title || e.url}</a>
              {e.key_facts && Object.keys(e.key_facts).length > 0 ? `（${Object.entries(e.key_facts).map(([k, v]) => `${k}:${v}`).join(' / ')}）` : ''}
            </li>
          ))}
        </ul>
      </div>
    );
  };

  const renderAcademicReportPreview = () => {
    if (!academicReport) return <p className="muted">尚未產生學術 DD 報告。</p>;
    return (
      <div className="reportPreview">
        <h4>學術 DD 報告</h4>
        <p className="muted">{academicReport.summary || '無摘要'}</p>
        <h5>建議實驗室</h5>
        <ul className="plainList">
          {(academicReport.recommended_labs || []).slice(0, 12).map((lab, i) => (
            <li key={`lab-${i}`}>
              {lab.school} / {lab.lab_name}（分數 {lab.score}）
            </li>
          ))}
        </ul>
        <h5>下一步</h5>
        <ul className="plainList">
          {(academicReport.next_actions || []).map((x, i) => <li key={`next-${i}`}>{x}</li>)}
        </ul>
      </div>
    );
  };

  return (
    <AppShell
      title="DD 工作台"
      subtitle="公司 DD 與學術 DD 分離執行，結果自動儲存到資料庫，可追溯、可問答、可匯出 PDF。"
      user={user}
      onLogin={onLogin}
      onLogout={logout}
    >
      <section className="panel card">
        <FieldLabel
          label="DD 模式"
          help="公司 DD：針對新創團隊盡調。學術 DD：針對學校/實驗室/教授的申請評估。"
        />
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="company">公司 DD</option>
          <option value="academic">學術 DD</option>
        </select>

        <div className="btnRow">
          {mode === 'company' ? (
            <>
              <button className="btn" onClick={() => setShowCompanyScoutModal(true)}>功能 1：VC Scout 找團隊</button>
              <button className="btn ghost" onClick={() => setShowCompanyDirectModal(true)}>功能 2：直接公司 DD</button>
              <button className="btn ghost" onClick={runCompanyDD}>針對目前候選產生 DD</button>
            </>
          ) : (
            <>
              <button className="btn" onClick={() => setShowAcademicModal(true)}>執行學術 DD（功能 2）</button>
            </>
          )}
        </div>

        {running && <div className="progressBox">執行中，請稍候...</div>}
        {running && (
          <div className="progressMeter">
            <div className="progressFill" style={{ width: `${progressPct}%` }} />
          </div>
        )}
        {running && progressHint ? <p className="muted">{progressHint}</p> : null}
        {!!logs.length && (
          <details className="progressHistory" open>
            <summary>執行進度</summary>
            <ul className="plainList">
              {logs.map((x, i) => <li key={`${x}-${i}`}>{x}</li>)}
            </ul>
          </details>
        )}
        {status && <p className="muted">{status}</p>}
        {error && <p className="errorText">{error}</p>}
      </section>

      {mode === 'company' ? (
        <section className="panel grid2">
          <div className="card">
            <h3>候選公司</h3>
            {!vcCandidates.length && <p className="muted">尚無候選公司，請先執行「功能 1：VC Scout」。</p>}
            {vcCandidates.map((c) => (
              <label key={c.id} className="radioRow">
                <input
                  type="radio"
                  checked={selectedCandidateId === c.id}
                  onChange={() => setSelectedCandidateId(c.id)}
                />
                <span>{c.name}（分數 {c.score}）</span>
              </label>
            ))}

            <hr className="softDivider" />
            <h3>報告檔案庫（公司）</h3>
            {!companyReports.length && <p className="muted">尚無公司 DD 報告。</p>}
            {companyReports.map((r) => (
              <label key={r.id} className="radioRow">
                <input
                  type="radio"
                  checked={selectedReportId === r.id}
                  onChange={() => selectCompanyReport(r.id)}
                />
                <span>{r.candidate_name || r.title}（{String(r.generated_at || '').slice(0, 10)}）</span>
              </label>
            ))}
          </div>

          <div className="card">
            <h3>公司 DD 預覽</h3>
            {renderCompanyReportPreview()}
          </div>
        </section>
      ) : (
        <section className="panel grid2">
          <div className="card">
            <h3>候選實驗室</h3>
            {!gradCandidates.length && <p className="muted">尚無候選實驗室，請先執行學術 DD。</p>}
            {gradCandidates.slice(0, 40).map((c) => (
              <div key={c.id} className="candidateItem">
                <strong>{c.school} / {c.lab_name}</strong>
                <p className="muted">分數 {c.score}{c.professor ? `｜教授：${c.professor}` : ''}</p>
                {c.lab_url && <a href={c.lab_url} target="_blank" rel="noreferrer">實驗室連結 ↗</a>}
              </div>
            ))}
            <hr className="softDivider" />
            <h3>報告檔案庫（學術）</h3>
            {!gradReports.length && <p className="muted">尚無學術 DD 報告。</p>}
            {gradReports.map((r) => (
              <label key={r.id} className="radioRow">
                <input
                  type="radio"
                  checked={selectedGradReportId === r.id}
                  onChange={() => selectGradReport(r.id)}
                />
                <span>{String(r.generated_at || '').slice(0, 16).replace('T', ' ')}</span>
              </label>
            ))}
          </div>

          <div className="card">
            <h3>學術 DD 預覽</h3>
            {renderAcademicReportPreview()}
          </div>
        </section>
      )}

      <section className="panel card">
        <h3>DD 問答與 PDF</h3>
        <p className="muted">問答會優先使用目前模式的最新報告。公司模式會套用你目前選中的候選公司。</p>

        <FieldLabel
          label="問題"
          help="例如：請幫我列出這家公司三個最大風險，並附上下一輪會議追問清單。"
        />
        <textarea
          rows={3}
          value={chatQuestion}
          onChange={(e) => setChatQuestion(e.target.value)}
          placeholder="輸入你要追問的內容..."
        />

        <div className="btnRow">
          <button className="btn" onClick={askDD}>送出問答</button>
          <button className="btn ghost" onClick={downloadPdf}>下載 PDF</button>
        </div>

        {chatAnswer && <pre className="monoBox">{chatAnswer}</pre>}
      </section>

      <Modal open={showCompanyScoutModal} title="功能 1：VC Scout 找候選團隊" onClose={() => setShowCompanyScoutModal(false)}>
        <FieldLabel label="基金 / 團隊名稱" help="例如：Atlas Frontier Capital。會出現在報告與外聯草稿。" />
        <input value={vcFirmName} onChange={(e) => setVcFirmName(e.target.value)} placeholder="例如：Atlas Frontier Capital" />

        <FieldLabel label="投資 Thesis" help="請寫清楚你關注的產業、客群、商業模型。這會直接影響候選排序。" />
        <textarea rows={3} value={vcThesis} onChange={(e) => setVcThesis(e.target.value)} />

        <FieldLabel label="偏好階段（逗號分隔）" help="例如：pre-seed,seed,series-a,series-b" />
        <input value={vcStages} onChange={(e) => setVcStages(e.target.value)} />

        <FieldLabel label="偏好領域（逗號分隔）" help="例如：AI Agent,Enterprise AI,Healthcare AI" />
        <input value={vcSectors} onChange={(e) => setVcSectors(e.target.value)} />

        <FieldLabel label="來源網站（逗號分隔）" help="若空白將使用系統內建台灣加速器/活動來源。" />
        <input value={vcDiscoverySources} onChange={(e) => setVcDiscoverySources(e.target.value)} />

        <div className="btnRow">
          <button className="btn" onClick={runCompanyScout} disabled={running}>開始執行</button>
        </div>
      </Modal>

      <Modal open={showCompanyDirectModal} title="功能 2：直接輸入公司做 DD" onClose={() => setShowCompanyDirectModal(false)}>
        <FieldLabel label="公司名稱" help="可只填名稱，也可搭配網址。" />
        <input value={vcDirectCompanyName} onChange={(e) => setVcDirectCompanyName(e.target.value)} placeholder="例如：Perplexity" />

        <FieldLabel label="公司網址（必填）" help="功能 2 會先深爬這個官網（含上下路由、內頁、sitemap），再補抓外部公開資料。" />
        <input value={vcDirectCompanyUrl} onChange={(e) => setVcDirectCompanyUrl(e.target.value)} placeholder="https://company.com" />

        <FieldLabel label="補充來源網址（逗號分隔）" help="可貼 Crunchbase、新聞稿、官方 Blog 等作為 DD 證據來源。" />
        <input value={vcExtraUrls} onChange={(e) => setVcExtraUrls(e.target.value)} placeholder="https://... , https://..." />

        <div className="btnRow">
          <button className="btn" onClick={runCompanyDirectReport} disabled={running}>開始執行</button>
        </div>
      </Modal>

      <Modal open={showAcademicModal} title="學術 DD（功能 2）" onClose={() => setShowAcademicModal(false)}>
        <FieldLabel label="履歷 / 背景（可貼文字）" help="用於計算與實驗室研究方向的匹配度。" />
        <textarea rows={5} value={gradResumeText} onChange={(e) => setGradResumeText(e.target.value)} />

        <FieldLabel label="研究興趣（逗號分隔）" help="例如：LLM,Agent,RAG,Computer Vision。" />
        <input value={gradInterests} onChange={(e) => setGradInterests(e.target.value)} />

        <FieldLabel label="學位目標" help="可選 master / phd / both。" />
        <select value={gradDegree} onChange={(e) => setGradDegree(e.target.value)}>
          <option value="master">Master</option>
          <option value="phd">PhD</option>
          <option value="both">Both</option>
        </select>

        <FieldLabel label="目標學校" help="建議填英文全名或常用縮寫，例如 MIT、Stanford、Oxford。" />
        <input value={gradDirectSchool} onChange={(e) => setGradDirectSchool(e.target.value)} placeholder="例如：MIT" />

        <FieldLabel label="實驗室網址" help="若已知特定 lab，可直接填這裡。" />
        <input value={gradDirectLabUrl} onChange={(e) => setGradDirectLabUrl(e.target.value)} placeholder="https://..." />

        <FieldLabel label="教授姓名" help="可搭配學校或實驗室網址，系統會嘗試比對公開頁面。" />
        <input value={gradDirectProfessor} onChange={(e) => setGradDirectProfessor(e.target.value)} placeholder="例如：Tommi Jaakkola" />

        <div className="btnRow">
          <button className="btn" onClick={runAcademicDirectReport} disabled={running}>開始執行</button>
        </div>
      </Modal>
    </AppShell>
  );
}
