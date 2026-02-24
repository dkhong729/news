from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .http_client import fetch_url
from .llm_client import LLMClient


def _timeout() -> float:
    return float(os.getenv("DD_DEEP_RESEARCH_HTTP_TIMEOUT", "10"))


def _max_workers() -> int:
    return max(2, min(8, int(os.getenv("DD_DEEP_RESEARCH_MAX_WORKERS", "4"))))


def _urls_per_task() -> int:
    return max(6, min(30, int(os.getenv("DD_DEEP_RESEARCH_URLS_PER_TASK", "12"))))


def _max_pages_per_task() -> int:
    return max(4, min(18, int(os.getenv("DD_DEEP_RESEARCH_MAX_PAGES_PER_TASK", "8"))))


def _search_rounds() -> int:
    return max(1, min(3, int(os.getenv("DD_DEEP_RESEARCH_SEARCH_ROUNDS", "2"))))


def _search_provider() -> str:
    return os.getenv("DD_DEEP_RESEARCH_SEARCH_PROVIDER", "auto").strip().lower()


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().replace("www.", "")
    except Exception:
        return ""


def _normalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except Exception:
        return value
    if not parsed.scheme or not parsed.netloc:
        return value
    query = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        key = k.lower()
        if key.startswith("utm_") or key in {"fbclid", "gclid", "ref", "source", "trk"}:
            continue
        query.append((k, v))
    parsed = parsed._replace(query=urlencode(query, doseq=True), fragment="")
    return parsed.geturl()


def _json_from_text(text: str) -> Optional[Dict[str, Any]]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def _clean_text(text: str, max_chars: int = 5000) -> str:
    soup = BeautifulSoup(text or "", "html.parser")
    for bad in soup(["script", "style", "noscript", "svg", "canvas"]):
        bad.decompose()

    candidates: List[str] = []
    for selector in ["main", "article", "[role='main']", ".content", "#content", ".container"]:
        for node in soup.select(selector):
            t = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if len(t) >= 120:
                candidates.append(t)
    if not candidates:
        t = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    else:
        t = max(candidates, key=len)
    return t[:max_chars]


def _page_title(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    node = soup.find("title")
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()[:220]


def _browser_headers() -> Dict[str, str]:
    return {
        "User-Agent": os.getenv(
            "DD_HTTP_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }


def _fetch_html(url: str) -> str:
    resp = fetch_url(
        url,
        headers=_browser_headers(),
        timeout=_timeout(),
        source_key=f"dd-research:{_domain(url)}",
        cache_ttl_hours=12,
    )
    if not resp.ok:
        return ""
    return resp.text or ""


def _search_tavily(query: str, limit: int = 8) -> List[str]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": limit,
                "search_depth": "advanced",
                "include_answer": False,
            },
            timeout=_timeout(),
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        out: List[str] = []
        for item in data.get("results", []):
            url = _normalize_url(str(item.get("url") or ""))
            if url.startswith("http://") or url.startswith("https://"):
                out.append(url)
                if len(out) >= limit:
                    break
        return out
    except Exception:
        return []


def _search_duckduckgo(query: str, limit: int = 8) -> List[str]:
    search_url = "https://duckduckgo.com/html/?" + urlencode({"q": query})
    html = _fetch_html(search_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        link = href
        if "duckduckgo.com/l/?" in href and "uddg=" in href:
            try:
                qp = dict(parse_qsl(urlparse(href).query))
                link = unquote(qp.get("uddg", ""))
            except Exception:
                link = href
        link = _normalize_url(link)
        if not (link.startswith("http://") or link.startswith("https://")):
            continue
        dom = _domain(link)
        if not dom or dom.endswith("duckduckgo.com"):
            continue
        if link in seen:
            continue
        seen.add(link)
        out.append(link)
        if len(out) >= limit:
            break
    return out


def _search_urls(query: str, limit: int = 8) -> List[str]:
    provider = _search_provider()
    if provider == "tavily":
        urls = _search_tavily(query, limit=limit)
        return urls or _search_duckduckgo(query, limit=limit)
    if provider == "duckduckgo":
        return _search_duckduckgo(query, limit=limit)
    urls = _search_tavily(query, limit=limit)
    return urls or _search_duckduckgo(query, limit=limit)


def _extract_links(current_url: str, html: str, same_domain_only: bool = True, max_links: int = 80) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_domain = _domain(current_url)
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full = _normalize_url(urljoin(current_url, href))
        if not (full.startswith("http://") or full.startswith("https://")):
            continue
        if same_domain_only and _domain(full) != base_domain:
            continue
        low = full.lower()
        if any(x in low for x in [".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf", ".zip", ".mp4"]):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
        if len(out) >= max_links:
            break
    return out


def _internal_seed_pages(company_url: str) -> List[str]:
    url = _normalize_url(company_url)
    if not url:
        return []
    p = urlparse(url)
    root = f"{p.scheme}://{p.netloc}/"
    hints = [
        "",
        "about",
        "about-us",
        "team",
        "company",
        "careers",
        "jobs",
        "blog",
        "news",
        "press",
        "changelog",
        "pricing",
        "customers",
        "case-studies",
        "docs",
        "security",
        "terms",
        "privacy",
    ]
    out = []
    seen = set()
    for h in hints:
        u = root if h == "" else urljoin(root, h)
        u = _normalize_url(u)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _safe_prompt_json(llm: Optional[LLMClient], system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
    if not llm:
        return None
    try:
        data = llm._post(
            {
                "model": llm.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            }
        )
        content = str(data["choices"][0]["message"]["content"])
        return _json_from_text(content)
    except Exception:
        return None


def _call_langchain_llm_json(system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
    """
    可選：使用 LangChain 封裝（若環境已安裝且開啟）。
    不是完整 LangGraph open-deep-research clone，但可作為寫作/壓縮層。
    """
    if os.getenv("DD_DEEP_RESEARCH_USE_LANGCHAIN", "0") != "1":
        return None
    if not os.getenv("DEEPSEEK_API_KEY"):
        return None
    try:
        from langchain_openai import ChatOpenAI  # type: ignore
        from langchain_core.messages import SystemMessage, HumanMessage  # type: ignore
    except Exception:
        return None

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    try:
        llm = ChatOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            model=model,
            base_url=f"{base_url}/v1",
            temperature=0.2,
        )
        resp = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        return _json_from_text(str(getattr(resp, "content", "") or ""))
    except Exception:
        return None


@dataclass
class TaskSpec:
    task_id: str
    name: str
    objective: str
    keywords: List[str]
    queries: List[str]


def _build_scope_brief(
    company_name: str,
    company_url: str,
    thesis: str,
    preferred_sectors: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    return {
        "company_name": company_name,
        "company_url": company_url,
        "objective": "針對創投投資決策完成可追溯來源的公司深度盡職調查（DD）報告。",
        "focus_dimensions": [
            "商業與營運調查（市場、競爭、產品定位、KPI）",
            "財務與稅務調查（融資、股權、財務揭露與資金效率）",
            "法律與合約調查（IP、訴訟、合規、重要條款）",
            "團隊能力調查（創辦人背景、組織分工、招聘訊號）",
            "產品與技術調查（技術路線、成熟度、護城河、部署）",
        ],
        "vc_thesis": thesis or "",
        "preferred_sectors": [str(x) for x in (preferred_sectors or []) if str(x).strip()][:8],
        "output_requirement": "僅整理與投資 DD 直接相關資訊，引用來源 URL，明確標記資料缺口與待驗證假設。",
    }


def _build_tasks(company_name: str, company_url: str) -> List[TaskSpec]:
    dom = _domain(company_url)
    site_q = [f"site:{dom} {company_name}"] if dom else [company_name]
    return [
        TaskSpec(
            task_id="business",
            name="商業與營運調查",
            objective="確認市場規模、競爭對手、產品定位、客戶案例、收費模式與營運訊號",
            keywords=["市場", "競爭", "客戶", "案例", "pricing", "revenue", "KPI", "GTM", "產品"],
            queries=site_q
            + [
                f"\"{company_name}\" 市場 競爭",
                f"\"{company_name}\" pricing OR 價格 OR 收費",
                f"\"{company_name}\" customer OR case study OR 客戶案例",
                f"\"{company_name}\" revenue OR ARR OR 營收",
            ],
        ),
        TaskSpec(
            task_id="financial",
            name="財務與稅務調查",
            objective="搜尋融資、股權、估值、財務揭露、稅務或債務等公開訊號",
            keywords=["融資", "funding", "valuation", "investor", "股東", "cap table", "財務", "稅"],
            queries=site_q
            + [
                f"\"{company_name}\" 融資",
                f"\"{company_name}\" funding",
                f"\"{company_name}\" investor",
                f"\"{company_name}\" valuation",
                f"\"{company_name}\" 股東 OR 董事 OR 增資",
            ],
        ),
        TaskSpec(
            task_id="legal",
            name="法律與合約調查",
            objective="檢視訴訟、法規合規、條款、隱私政策、專利與商標訊號",
            keywords=["訴訟", "lawsuit", "compliance", "terms", "privacy", "專利", "商標", "license"],
            queries=site_q
            + [
                f"\"{company_name}\" lawsuit OR litigation",
                f"\"{company_name}\" terms of service",
                f"\"{company_name}\" privacy policy",
                f"\"{company_name}\" patent OR 專利",
                f"\"{company_name}\" trademark OR 商標",
            ],
        ),
        TaskSpec(
            task_id="team",
            name="團隊能力調查",
            objective="確認創辦人背景、團隊頁面、招聘訊號、技術與商業職缺配置",
            keywords=["founder", "team", "leadership", "linkedin", "careers", "jobs", "招聘", "徵才"],
            queries=site_q
            + [
                f"\"{company_name}\" founder",
                f"\"{company_name}\" team",
                f"\"{company_name}\" linkedin",
                f"\"{company_name}\" careers OR jobs",
                f"\"{company_name}\" hiring",
            ],
        ),
        TaskSpec(
            task_id="technology",
            name="產品與技術調查",
            objective="確認技術路線、產品文件、部署、架構、變更日誌與工程實作訊號",
            keywords=["docs", "API", "architecture", "deploy", "roadmap", "changelog", "github", "技術", "架構"],
            queries=site_q
            + [
                f"\"{company_name}\" docs OR documentation",
                f"\"{company_name}\" API",
                f"\"{company_name}\" architecture",
                f"\"{company_name}\" github",
                f"\"{company_name}\" changelog OR roadmap",
            ],
        ),
    ]


def _score_evidence(task: TaskSpec, company_name: str, url: str, title: str, text: str) -> float:
    blob = f"{url} {title} {text}".lower()
    score = 0.0
    if company_name and company_name.lower() in blob:
        score += 2.0
    for kw in task.keywords:
        if kw.lower() in blob:
            score += 0.8 if len(kw) <= 4 else 1.0
    dom = _domain(url)
    if dom.endswith("github.com") or dom.endswith("linkedin.com"):
        score += 0.8
    if dom.endswith("crunchbase.com") or dom.endswith("pitchbook.com"):
        score += 1.0
    if dom == _domain(url):
        score += 0.0
    return round(score, 3)


def _fetch_page(url: str) -> Optional[Dict[str, Any]]:
    html = _fetch_html(url)
    if not html:
        return None
    title = _page_title(html) or url
    text = _clean_text(html, max_chars=7000)
    if len(text) < 120:
        return None
    return {
        "url": url,
        "domain": _domain(url),
        "title": title,
        "text": text,
        "excerpt": text[:480],
        "internal_links": _extract_links(url, html, same_domain_only=True, max_links=50),
        "external_links": _extract_links(url, html, same_domain_only=False, max_links=50),
    }


def _expand_queries_with_llm(task: TaskSpec, company_name: str, company_url: str, seed_evidence: List[Dict[str, Any]]) -> List[str]:
    llm = LLMClient() if os.getenv("DEEPSEEK_API_KEY") else None
    if not llm:
        return []
    evidence_preview = "\n".join([f"- {e.get('title')} | {e.get('url')}" for e in seed_evidence[:6]])
    system = (
        "你是深度研究查詢規劃助手。請根據公司名稱與目前證據，輸出 JSON："
        "{ \"queries\": [..] }。只輸出 4~8 個高價值搜尋查詢，聚焦投資 DD。"
    )
    user = (
        f"公司：{company_name}\n官網：{company_url}\n任務：{task.name}\n目標：{task.objective}\n"
        f"現有證據：\n{evidence_preview}"
    )
    parsed = _call_langchain_llm_json(system, user) or _safe_prompt_json(llm, system, user)
    queries = parsed.get("queries") if isinstance(parsed, dict) else None
    if not isinstance(queries, list):
        return []
    out = []
    for q in queries:
        s = str(q).strip()
        if s and len(s) <= 160:
            out.append(s)
    return out[:8]


def _summarize_subtask(task: TaskSpec, evidences: List[Dict[str, Any]]) -> Dict[str, Any]:
    llm = LLMClient() if os.getenv("DEEPSEEK_API_KEY") else None
    evidence_text = "\n\n".join(
        [
            f"[{i+1}] {e.get('title')}\nURL: {e.get('url')}\n摘要: {e.get('excerpt')}"
            for i, e in enumerate(evidences[:8])
        ]
    )
    system = (
        "你是創投 DD 子代理。請根據證據輸出繁體中文 JSON，欄位：summary, key_findings, gaps, citations。"
        "key_findings/gaps/citations 皆為陣列。不得杜撰。citations 可直接回傳 URL 或物件。"
    )
    user = f"任務：{task.name}\n目標：{task.objective}\n證據：\n{evidence_text}"
    parsed = _call_langchain_llm_json(system, user) or _safe_prompt_json(llm, system, user)
    if isinstance(parsed, dict):
        return parsed
    return {
        "summary": f"已整理 {len(evidences)} 份證據，待進一步訪談確認。",
        "key_findings": [str(e.get("title") or e.get("url")) for e in evidences[:5]],
        "gaps": (["證據不足，請補充更多公開資料與內部文件。"] if not evidences else []),
        "citations": [{"title": e.get("title"), "url": e.get("url"), "domain": e.get("domain")} for e in evidences[:8]],
    }


def _run_sub_agent(task: TaskSpec, company_name: str, company_url: str, seed_urls: List[str]) -> Dict[str, Any]:
    started = time.monotonic()
    max_urls = _urls_per_task()
    max_pages = _max_pages_per_task()

    queue: List[str] = []
    seen_urls = set()

    def enqueue(url: str) -> None:
        u = _normalize_url(url)
        if not u or u in seen_urls:
            return
        if not (u.startswith("http://") or u.startswith("https://")):
            return
        seen_urls.add(u)
        queue.append(u)

    for u in _internal_seed_pages(company_url):
        enqueue(u)
    for u in seed_urls[:20]:
        enqueue(u)

    query_plan = list(task.queries)
    seed_evidence: List[Dict[str, Any]] = []

    # 多輪搜尋：第 1 輪用預設查詢；第 2 輪可由 LLM 擴展
    for round_idx in range(_search_rounds()):
        if round_idx > 0:
            query_plan.extend(_expand_queries_with_llm(task, company_name, company_url, seed_evidence))
        for q in query_plan:
            for u in _search_urls(q, limit=max_urls):
                enqueue(u)
                if len(queue) >= max_urls * 4:
                    break
            if len(queue) >= max_urls * 4:
                break

    fetched: List[Dict[str, Any]] = []
    i = 0
    while i < len(queue) and len(fetched) < max_pages * 2:
        url = queue[i]
        i += 1
        page = _fetch_page(url)
        if not page:
            continue
        score = _score_evidence(task, company_name, page["url"], page["title"], page["text"])
        page["task_score"] = score
        fetched.append(page)
        if len(seed_evidence) < 8:
            seed_evidence.append(page)
        # 若是官網，擴展部分內頁與外鏈（docs/blog/careers/news）
        for link in page.get("internal_links", [])[:12]:
            low = link.lower()
            if any(k in low for k in ["about", "team", "career", "job", "blog", "news", "press", "docs", "pricing", "customer", "case", "security", "terms", "privacy", "changelog"]):
                enqueue(link)
        for link in page.get("external_links", [])[:8]:
            low = link.lower()
            if any(k in low for k in ["github.com", "linkedin.com", "crunchbase.com", "pitchbook.com", "producthunt.com", "ycombinator.com", "techcrunch.com", "medium.com"]):
                enqueue(link)

    fetched.sort(key=lambda x: (float(x.get("task_score") or 0), len(str(x.get("text") or ""))), reverse=True)
    picked = fetched[:max_pages]

    sub_summary = _summarize_subtask(task, picked)
    citations = sub_summary.get("citations")
    if not isinstance(citations, list):
        citations = []
    if not citations:
        citations = [{"title": p.get("title"), "url": p.get("url"), "domain": p.get("domain"), "score": p.get("task_score")} for p in picked[:10]]

    return {
        "task_id": task.task_id,
        "name": task.name,
        "objective": task.objective,
        "summary": str(sub_summary.get("summary") or ""),
        "key_findings": [str(x) for x in (sub_summary.get("key_findings") or []) if x][:10],
        "gaps": [str(x) for x in (sub_summary.get("gaps") or []) if x][:10],
        "citations": citations[:15],
        "evidence_count": len(picked),
        "elapsed_sec": round(time.monotonic() - started, 2),
        "searched_urls": len(queue),
    }


def _final_write(scope: Dict[str, Any], sub_reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    llm = LLMClient() if os.getenv("DEEPSEEK_API_KEY") else None
    citations: List[Dict[str, Any]] = []
    for sub in sub_reports:
        for c in (sub.get("citations") or [])[:6]:
            if isinstance(c, dict):
                citations.append({**c, "task_id": sub.get("task_id"), "task_name": sub.get("name")})
            else:
                citations.append({"title": str(c), "url": "", "task_id": sub.get("task_id"), "task_name": sub.get("name")})

    system = (
        "你是創投 DD 總整代理。請整合子代理研究成果，輸出繁體中文 JSON，欄位必須包含："
        "executive_summary, business_dd, financial_dd, legal_dd, team_dd, tech_dd, key_risks, dd_checklist_pending, citations。"
        "其中 key_risks/dd_checklist_pending/citations 必須為陣列。不得杜撰，資料不足要明確標示。"
    )
    user = (
        f"研究簡報：{json.dumps(scope, ensure_ascii=False)}\n"
        f"子代理結果：{json.dumps(sub_reports, ensure_ascii=False)}\n"
        f"引用候選：{json.dumps(citations[:30], ensure_ascii=False)}"
    )
    parsed = _call_langchain_llm_json(system, user) or _safe_prompt_json(llm, system, user)
    if isinstance(parsed, dict):
        if not isinstance(parsed.get("citations"), list):
            parsed["citations"] = citations[:20]
        return parsed

    by_id = {str(x.get("task_id")): x for x in sub_reports}
    return {
        "executive_summary": "已完成多代理深度研究，以下為基於公開來源的初步 DD 結論；仍需訪談與文件驗證。",
        "business_dd": str(by_id.get("business", {}).get("summary") or ""),
        "financial_dd": str(by_id.get("financial", {}).get("summary") or ""),
        "legal_dd": str(by_id.get("legal", {}).get("summary") or ""),
        "team_dd": str(by_id.get("team", {}).get("summary") or ""),
        "tech_dd": str(by_id.get("technology", {}).get("summary") or ""),
        "key_risks": [
            "公開資料與實際營運可能存在落差，需透過管理層訪談與文件交叉驗證。",
            "若缺乏財務、法務與客戶合約證據，投資判斷風險較高。",
        ],
        "dd_checklist_pending": [
            "索取近 12 個月財務摘要、現金流、Burn Rate 與 Runway",
            "索取主要客戶、合作夥伴、供應商合約（含限制條款）",
            "索取核心技術 / IP 歸屬與授權文件",
        ],
        "citations": citations[:20],
    }


def run_company_deep_research(
    company_name: str,
    company_url: str,
    thesis: str = "",
    preferred_sectors: Optional[List[str]] = None,
    seed_evidence_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    started = time.monotonic()
    company_name = (company_name or "").strip() or _domain(company_url).split(".")[0]
    company_url = (company_url or "").strip()
    seed_urls = [str(x).strip() for x in (seed_evidence_urls or []) if str(x).strip()]

    scope = _build_scope_brief(company_name, company_url, thesis, preferred_sectors=preferred_sectors)
    tasks = _build_tasks(company_name, company_url)
    trace: List[Dict[str, Any]] = [
        {"stage": "scope", "status": "done", "tasks_planned": len(tasks), "brief_len": len(json.dumps(scope, ensure_ascii=False))}
    ]

    sub_reports: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(_max_workers(), len(tasks))) as ex:
        futs = {ex.submit(_run_sub_agent, task, company_name, company_url, seed_urls): task for task in tasks}
        for fut in as_completed(futs):
            task = futs[fut]
            try:
                sub = fut.result()
            except Exception as exc:
                sub = {
                    "task_id": task.task_id,
                    "name": task.name,
                    "objective": task.objective,
                    "summary": f"子代理執行失敗：{exc}",
                    "key_findings": [],
                    "gaps": ["子代理失敗，請稍後重試或改用更明確的公司名稱 / URL。"],
                    "citations": [],
                    "evidence_count": 0,
                    "elapsed_sec": 0,
                }
            sub_reports.append(sub)
    sub_reports.sort(key=lambda x: str(x.get("task_id") or ""))
    trace.append(
        {
            "stage": "research",
            "status": "done",
            "tasks": len(sub_reports),
            "total_evidence": sum(int(x.get("evidence_count") or 0) for x in sub_reports),
            "total_searched_urls": sum(int(x.get("searched_urls") or 0) for x in sub_reports),
        }
    )

    final = _final_write(scope, sub_reports)
    trace.append({"stage": "write", "status": "done", "citation_count": len(final.get("citations", []))})

    return {
        "scope": scope,
        "sub_reports": sub_reports,
        "final": final,
        "trace": trace,
        "elapsed_sec": round(time.monotonic() - started, 2),
    }

