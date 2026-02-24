from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .deep_research_agent import run_company_deep_research
from .db import (
    clear_grad_lab_candidates,
    find_public_signals_for_candidate,
    get_grad_dd_profile,
    get_latest_grad_dd_report,
    get_vc_candidate,
    get_vc_profile,
    insert_grad_dd_report,
    list_grad_dd_reports,
    list_grad_lab_candidates,
    list_vc_dd_reports,
    mark_grad_lab_shortlist,
    upsert_grad_dd_profile,
    upsert_grad_lab_candidate,
    upsert_vc_candidate,
    upsert_vc_dd_report,
)
from .http_client import fetch_url
from .llm_client import LLMClient

LAB_KEYWORDS = [
    "lab",
    "laboratory",
    "research group",
    "research",
    "professor",
    "faculty",
    "實驗室",
    "研究室",
    "研究中心",
    "人工智慧",
    "機器學習",
    "深度學習",
]

COMPANY_PAGE_HINTS = [
    "about",
    "team",
    "founder",
    "product",
    "solution",
    "technology",
    "tech",
    "news",
    "blog",
    "press",
    "pricing",
    "customer",
    "case-study",
    "investor",
    "career",
    "portfolio",
    "公司",
    "關於",
    "團隊",
    "產品",
    "技術",
    "新聞",
    "案例",
    "投資",
    "徵才",
    "營業",
    "產品介紹",
    "解決方案",
    "客戶",
    "案例",
    "董監事",
    "負責人",
    "統編",
    "公司資訊",
    "簡介",
    "服務",
]

COMPANY_EXTERNAL_SIGNAL_DOMAINS = {
    "crunchbase.com",
    "linkedin.com",
    "pitchbook.com",
    "medium.com",
    "ycombinator.com",
    "appworks.tw",
    "garageplus.asia",
}

COMPANY_REGISTRY_DOMAINS = {
    "twincn.com",
    "findcompany.com.tw",
    "opencorporates.com",
}

REGISTRY_NOISE_TITLE_HINTS = [
    "搜尋公司列表",
    "所有權人",
    "商標",
    "分類",
    "同地址",
    "相關公司",
]

SOCIAL_OR_NOISE_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "threads.net",
    "threads.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
    "line.me",
    "t.me",
}

SCHOOL_DOMAIN_HINTS = {
    "台大": "https://www.ntu.edu.tw/",
    "臺大": "https://www.ntu.edu.tw/",
    "清大": "https://www.nthu.edu.tw/",
    "交大": "https://www.nycu.edu.tw/",
    "陽明交大": "https://www.nycu.edu.tw/",
    "成大": "https://www.ncku.edu.tw/",
    "政大": "https://www.nccu.edu.tw/",
    "台科": "https://www.ntust.edu.tw/",
    "MIT": "https://www.mit.edu/",
    "Stanford": "https://www.stanford.edu/",
    "CMU": "https://www.cmu.edu/",
    "Berkeley": "https://www.berkeley.edu/",
    "Harvard": "https://www.harvard.edu/",
    "Princeton": "https://www.princeton.edu/",
    "Yale": "https://www.yale.edu/",
    "Columbia": "https://www.columbia.edu/",
    "Cornell": "https://www.cornell.edu/",
    "UCLA": "https://www.ucla.edu/",
    "UC San Diego": "https://www.ucsd.edu/",
    "University of Washington": "https://www.washington.edu/",
    "Georgia Tech": "https://www.gatech.edu/",
    "ETH Zurich": "https://ethz.ch/en.html",
    "EPFL": "https://www.epfl.ch/en/",
    "Oxford": "https://www.ox.ac.uk/",
    "Cambridge": "https://www.cam.ac.uk/",
    "Imperial": "https://www.imperial.ac.uk/",
    "UCL": "https://www.ucl.ac.uk/",
    "TUM": "https://www.tum.de/en/",
    "TU Munich": "https://www.tum.de/en/",
    "KTH": "https://www.kth.se/en",
    "University of Amsterdam": "https://www.uva.nl/en",
    "KU Leuven": "https://www.kuleuven.be/english/kuleuven/",
    "Sorbonne": "https://www.sorbonne-universite.fr/en",
    "PSL": "https://psl.eu/en",
    "Heidelberg": "https://www.uni-heidelberg.de/en",
    "Max Planck": "https://www.mpg.de/en",
    "INRIA": "https://www.inria.fr/en",
}

ACADEMIC_PATH_HINTS = [
    "/research",
    "/research-groups",
    "/labs",
    "/lab",
    "/people",
    "/faculty",
    "/departments/computer-science",
    "/academics",
    "/computer-science",
    "/eecs",
    "/ai",
    "/ml",
]


def _http_timeout() -> float:
    return float(os.getenv("MVP_HTTP_TIMEOUT", "8"))


def _browser_headers() -> Dict[str, str]:
    return {
        "User-Agent": os.getenv(
            "DD_HTTP_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    }


def _parse_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def _fetch_text(url: str, max_chars: int = 12000) -> str:
    headers = _browser_headers()
    resp = fetch_url(url, headers=headers, timeout=_http_timeout(), source_key=f"dd:{_domain(url)}", cache_ttl_hours=24)
    if not resp.ok:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(" ", strip=True)[:max_chars]


def _fetch_html(url: str, source_key: str) -> str:
    headers = _browser_headers()
    resp = fetch_url(url, headers=headers, timeout=_http_timeout(), source_key=source_key, cache_ttl_hours=24)
    if not resp.ok:
        return ""
    return resp.text


def _sanitize_url_for_crawl(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return (url or "").strip()
    if not parsed.scheme or not parsed.netloc:
        return (url or "").strip()

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    keep_items = []
    for k, v in query_items:
        lk = k.lower()
        if lk.startswith("utm_"):
            continue
        if lk in {"fbclid", "gclid", "ref", "source", "trk"}:
            continue
        keep_items.append((k, v))

    clean_query = urlencode(keep_items, doseq=True)
    clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, clean_query, ""))
    return clean


def _parent_urls(url: str, depth: int = 3) -> List[str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return []
    if not parsed.scheme or not parsed.netloc:
        return []

    out: List[str] = []
    clean = _sanitize_url_for_crawl(url)
    if clean:
        out.append(clean)

    if parsed.query:
        no_query = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", ""))
        out.append(no_query)

    parts = [x for x in parsed.path.split("/") if x]
    for i in range(min(depth, len(parts)), 0, -1):
        path = "/" + "/".join(parts[: i - 1]) if i > 1 else "/"
        out.append(urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")))

    uniq: List[str] = []
    seen = set()
    for item in out:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(key)
    return uniq


def _is_registry_domain(domain: str) -> bool:
    d = (domain or "").lower().replace("www.", "")
    return any(d.endswith(x) for x in COMPANY_REGISTRY_DOMAINS)


def _registrable_domain(domain: str) -> str:
    d = (domain or "").lower().replace("www.", "")
    if not d:
        return ""
    parts = [p for p in d.split(".") if p]
    if len(parts) <= 2:
        return d
    # 簡化版 eTLD+1
    if parts[-2] in {"com", "org", "net", "gov", "edu"} and len(parts[-1]) == 2 and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _same_reg_domain(url_a: str, url_b: str) -> bool:
    da = _registrable_domain(_domain(url_a))
    db = _registrable_domain(_domain(url_b))
    return bool(da and db and da == db)


def _build_internal_seed_urls(official_url: str) -> List[str]:
    base = _sanitize_url_for_crawl(official_url)
    try:
        p = urlparse(base)
    except Exception:
        return [base] if base else []
    if not p.scheme or not p.netloc:
        return [base] if base else []

    root = urlunparse((p.scheme, p.netloc, "/", "", "", ""))
    hints = [
        "/about",
        "/about-us",
        "/company",
        "/team",
        "/founders",
        "/products",
        "/product",
        "/solutions",
        "/technology",
        "/tech",
        "/services",
        "/customers",
        "/case-studies",
        "/news",
        "/blog",
        "/press",
        "/investor",
        "/careers",
        "/contact",
    ]
    out = [base, root]
    for h in hints:
        out.append(urlunparse((p.scheme, p.netloc, h, "", "", "")))
    uniq: List[str] = []
    seen = set()
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return uniq


def _extract_internal_links(current_url: str, html: str, max_links: int = 180) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full = _sanitize_url_for_crawl(urljoin(current_url, href))
        if not (full.startswith("http://") or full.startswith("https://")):
            continue
        if not _same_reg_domain(current_url, full):
            continue
        low = full.lower()
        if any(x in low for x in [".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf", ".zip", ".mp4"]):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
        if len(out) >= max_links:
            break
    return out


def _discover_sitemap_urls(official_url: str, max_urls: int = 120) -> List[str]:
    try:
        p = urlparse(official_url)
    except Exception:
        return []
    if not p.scheme or not p.netloc:
        return []

    root = urlunparse((p.scheme, p.netloc, "/", "", "", ""))
    sitemap_urls = [urljoin(root, "sitemap.xml")]
    discovered: List[str] = []
    seen_map = set()

    for sm in sitemap_urls:
        if sm in seen_map:
            continue
        seen_map.add(sm)
        xml = _fetch_html(sm, source_key=f"dd-company:sitemap:{_domain(sm)}")
        if not xml:
            continue

        locs = re.findall(r"<loc>(.*?)</loc>", xml, flags=re.IGNORECASE | re.DOTALL)
        for loc in locs:
            candidate = _sanitize_url_for_crawl(unquote(loc.strip()))
            if not candidate.startswith("http://") and not candidate.startswith("https://"):
                continue
            if not _same_reg_domain(root, candidate):
                continue
            if candidate.endswith(".xml") and "sitemap" in candidate and candidate not in seen_map and len(seen_map) < 6:
                sitemap_urls.append(candidate)
                continue
            discovered.append(candidate)
            if len(discovered) >= max_urls:
                return discovered
    return discovered


def _extract_related_public_urls_from_html(
    html: str,
    company_name: str,
    official_no: str,
    limit: int = 20,
) -> List[str]:
    if not html:
        return []
    company_low = (company_name or "").strip().lower()
    no_low = (official_no or "").strip().lower()
    raw_urls = re.findall(r"https?://[^\"'\s<>]+", html)

    out: List[str] = []
    seen = set()
    for raw in raw_urls:
        url = _sanitize_url_for_crawl(unquote(raw.strip()))
        if not url.startswith("http://") and not url.startswith("https://"):
            continue
        dom = _domain(url)
        if not dom:
            continue
        if any(dom.endswith(x) for x in SOCIAL_OR_NOISE_DOMAINS):
            continue

        low = url.lower()
        is_related = False
        if company_low and company_low in low:
            is_related = True
        if no_low and (f"no={no_low}" in low or f"q={no_low}" in low):
            is_related = True
        if any(marker in dom for marker in ["datagove.com", "twjobs.net", "lawsq.com", "rank.twincn.com", "bid.twincn.com", "org.twincn.com"]):
            is_related = True
        if not is_related:
            continue

        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def _extract_official_site_candidates(base_url: str, html: str, company_name: str) -> List[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    base_domain = _domain(base_url)
    candidates: List[str] = []
    seen = set()
    company_low = (company_name or "").strip().lower()

    fallback_candidates: List[str] = []
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        text = a.get_text(" ", strip=True)
        if not href:
            continue
        full = _sanitize_url_for_crawl(urljoin(base_url, href))
        dom = _domain(full)
        if not dom or dom == base_domain:
            continue
        if any(dom.endswith(x) for x in SOCIAL_OR_NOISE_DOMAINS):
            continue

        low = f"{text} {full}".lower()
        has_marker = ("官網" in low or "website" in low or "官方" in low or "www." in low)
        is_company_related = bool(company_low and company_low in low)

        if full in seen:
            continue
        seen.add(full)
        if has_marker or is_company_related:
            candidates.append(full)
        else:
            fallback_candidates.append(full)
        if len(candidates) >= 12:
            return candidates
        if len(fallback_candidates) >= 20:
            continue
    if candidates:
        return candidates[:12]
    return fallback_candidates[:8]


def _search_company_public_urls(
    company_name: str,
    official_url: Optional[str] = None,
    limit: int = 24,
    search_terms: Optional[List[str]] = None,
) -> List[str]:
    name = (company_name or "").strip()
    if not name:
        return []
    official_domain = _domain(official_url or "")
    official_reg = _registrable_domain(official_domain)

    queries = [
        f'"{name}" 公司 官網',
        f'"{name}" 新創 融資',
        f'"{name}" founder',
        f'"{name}" 產品',
        f'"{name}" 技術',
        f'"{name}" 招聘',
    ]
    for kw in (search_terms or []):
        k = (kw or "").strip()
        if not k:
            continue
        queries.append(f'"{name}" "{k}"')
    if official_domain:
        queries.extend(
            [
                f'"{name}" site:{official_domain}',
                f'"{name}" "{official_domain}"',
            ]
        )

    results: List[str] = []
    seen = set()
    for q in queries:
        try:
            search_url = "https://duckduckgo.com/html/?" + urlencode({"q": q})
            html = _fetch_html(search_url, source_key="dd-company:search")
        except Exception:
            html = ""
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
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
            if not (link.startswith("http://") or link.startswith("https://")):
                continue
            dom = _domain(link)
            if not dom or "duckduckgo.com" in dom:
                continue
            if any(dom.endswith(x) for x in SOCIAL_OR_NOISE_DOMAINS):
                continue
            if "twincn.com" in dom and "item.aspx" not in link:
                continue
            if official_reg and _registrable_domain(dom) == official_reg:
                # 官方網站會由內站深爬處理，這裡保留外部公開資料
                continue
            if link in seen:
                continue
            seen.add(link)
            results.append(_sanitize_url_for_crawl(link))
            if len(results) >= limit:
                return results
    return results


def _extract_candidate_company_links(base_url: str, html: str, company_name: str, limit: int = 80) -> List[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    base_domain = _domain(base_url)
    company_low = (company_name or "").strip().lower()

    links: List[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        title = a.get_text(" ", strip=True)
        if not href:
            continue
        full = _sanitize_url_for_crawl(urljoin(base_url, href))
        dom = _domain(full)
        if not dom:
            continue
        if full in seen:
            continue
        low = f"{title} {full}".lower()

        is_internal = dom == base_domain
        has_hint = any(marker in low for marker in COMPANY_PAGE_HINTS)
        is_external_signal = any(dom.endswith(s) for s in COMPANY_EXTERNAL_SIGNAL_DOMAINS)
        company_match = bool(company_low) and (company_low in low)

        if not is_internal and not is_external_signal and not company_match:
            continue
        if is_internal and (not has_hint and not company_match):
            continue

        seen.add(full)
        links.append(full)
        if len(links) >= limit:
            break
    return links


def _extract_external_signal_links(current_url: str, html: str, company_name: str, limit: int = 36) -> List[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    current_domain = _domain(current_url)
    company_low = (company_name or "").strip().lower()
    trusted_domains = [
        "github.com",
        "linkedin.com",
        "medium.com",
        "substack.com",
        "crunchbase.com",
        "pitchbook.com",
        "36kr.com",
        "techcrunch.com",
        "ycombinator.com",
        "producthunt.com",
        "angel.co",
        "wellfound.com",
    ]
    clue_tokens = [
        "careers",
        "jobs",
        "hiring",
        "press",
        "news",
        "blog",
        "changelog",
        "announcement",
        "investor",
        "about",
        "team",
        "case",
        "quote",
        "客戶",
        "案例",
        "新聞",
        "徵才",
        "團隊",
    ]
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full = _sanitize_url_for_crawl(urljoin(current_url, href))
        if not (full.startswith("http://") or full.startswith("https://")):
            continue
        dom = _domain(full)
        if not dom or dom == current_domain:
            continue
        if any(dom.endswith(x) for x in SOCIAL_OR_NOISE_DOMAINS):
            continue
        text = a.get_text(" ", strip=True)
        low = f"{text} {full}".lower()
        trusted = any(dom.endswith(x) for x in trusted_domains)
        has_clue = any(t in low for t in clue_tokens)
        company_related = bool(company_low and company_low in low)
        if not (trusted or has_clue or company_related):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
        if len(out) >= limit:
            break
    return out


def _extract_page_title(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("title")
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()[:160]


def _extract_registry_facts(text: str) -> Dict[str, str]:
    value = re.sub(r"\s+", " ", text or "").strip()
    if not value:
        return {}

    patterns = {
        "統一編號": r"(?:統一編號|統編)\s*[:：]?\s*([0-9]{8})",
        "代表人": r"(?:代表人|負責人)\s*[:：]?\s*([^\s，,。;；]{2,20})",
        "地址": r"(?:地址|公司所在地)\s*[:：]?\s*([^。；;\n]{6,80})",
        "資本額": r"(?:資本額|實收資本額)\s*[:：]?\s*([^。；;\n]{2,40})",
        "成立日期": r"(?:成立|設立)日期\s*[:：]?\s*([^。；;\n]{4,20})",
    }

    out: Dict[str, str] = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, value, flags=re.IGNORECASE)
        if m:
            out[key] = _compact_text(m.group(1), 60)
    return out


def _extract_registry_people(text: str, limit: int = 8) -> List[str]:
    value = re.sub(r"\s+", " ", text or "").strip()
    if not value:
        return []

    people: List[str] = []
    seen = set()
    patterns = [
        r"(?:代表人|負責人)\s*[:：]?\s*([^\s，,。;；]{2,8})",
        r"(?:董事長|董事)\s*[:：]?\s*([^\s，,。;；]{2,8})",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, value, flags=re.IGNORECASE):
            name = _compact_text(m.group(1), 12)
            if not name or name in seen:
                continue
            seen.add(name)
            people.append(name)
            if len(people) >= limit:
                return people
    return people


def _extract_company_search_terms(
    company_name: str,
    evidence_rows: List[Dict[str, Any]],
    limit: int = 8,
) -> List[str]:
    out: List[str] = []
    seen = set()

    def add(term: str) -> None:
        t = (term or "").strip()
        if not t or t in seen:
            return
        seen.add(t)
        out.append(t)

    add("官網")
    add("產品")
    add("技術")
    add("募資")
    add("新聞")
    add("104")
    add("LinkedIn")

    for row in evidence_rows[:8]:
        if row.get("source_type") != "registry":
            continue
        title = str(row.get("title") or "")
        for person in _extract_registry_people(title):
            add(person)
        facts = row.get("key_facts") if isinstance(row.get("key_facts"), dict) else {}
        for person in _extract_registry_people(" ".join([str(v) for v in facts.values()])):
            add(person)

    if company_name and ("氫" in company_name or "hydrogen" in company_name.lower()):
        add("氫能")
        add("燃料電池")

    return out[:limit]


def _company_relevance_score(
    title: str,
    excerpt: str,
    company_name: str,
    is_registry: bool,
    is_official_site: bool,
    crawl_source: str,
) -> float:
    text = f"{title} {excerpt}".lower()
    company_low = (company_name or "").strip().lower()
    score = 0.0

    if company_low and company_low in text:
        score += 2.4
    if is_official_site:
        score += 2.0
    if not is_registry:
        score += 1.6
    if crawl_source in {"public_search", "registry_official", "registry_related"}:
        score += 0.9

    keywords = [
        "about",
        "team",
        "founder",
        "product",
        "technology",
        "case study",
        "news",
        "press",
        "partner",
        "investor",
        "關於",
        "團隊",
        "產品",
        "技術",
        "客戶",
        "合作",
        "募資",
        "新聞",
    ]
    score += min(2.0, _overlap_score(text, keywords) * 0.18)

    for noise in REGISTRY_NOISE_TITLE_HINTS:
        if noise.lower() in text:
            score -= 0.9

    return round(score, 3)


def _prioritize_company_evidence(
    rows: List[Dict[str, Any]],
    company_name: str,
    max_pages: int,
) -> List[Dict[str, Any]]:
    if not rows:
        return []
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        title = str(row.get("title") or "")
        excerpt = str(row.get("excerpt") or "")
        relevance = _company_relevance_score(
            title=title,
            excerpt=excerpt,
            company_name=company_name,
            is_registry=(row.get("source_type") == "registry"),
            is_official_site=bool(row.get("is_official_site")),
            crawl_source=str(row.get("crawl_source") or ""),
        )
        item = {**row, "relevance_score": relevance}
        enriched.append(item)

    enriched.sort(key=lambda x: (float(x.get("relevance_score") or 0), int(x.get("content_chars") or 0)), reverse=True)

    out: List[Dict[str, Any]] = []
    domain_cap: Dict[str, int] = {}
    for row in enriched:
        domain = str(row.get("domain") or "unknown")
        cap = domain_cap.get(domain, 0)
        if cap >= 4:
            continue
        domain_cap[domain] = cap + 1
        out.append(row)
        if len(out) >= max_pages:
            break
    return out


def _collect_company_evidence(
    primary_url: str,
    extra_urls: Optional[List[str]] = None,
    company_name: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    started = time.monotonic()
    max_pages = max(6, min(24, int(os.getenv("DD_COMPANY_MAX_PAGES", "16"))))
    min_runtime = max(0.0, float(os.getenv("DD_COMPANY_MIN_RUNTIME_SEC", "10")))
    min_target_pages = max(4, min(10, int(os.getenv("DD_COMPANY_MIN_PAGES", "6"))))
    crawl_max_sec = max(
        min_runtime + 3.0,
        float(os.getenv("DD_COMPANY_CRAWL_MAX_SEC", "45")),
    )
    internal_max_depth = max(1, min(4, int(os.getenv("DD_COMPANY_INTERNAL_MAX_DEPTH", "2"))))
    internal_max_links = max(40, min(300, int(os.getenv("DD_COMPANY_INTERNAL_MAX_LINKS", "180"))))
    sitemap_max_urls = max(20, min(300, int(os.getenv("DD_COMPANY_SITEMAP_MAX_URLS", "100"))))
    external_max_urls = max(8, min(80, int(os.getenv("DD_COMPANY_EXTERNAL_MAX_URLS", "24"))))
    max_registry_pages = max(4, min(16, int(os.getenv("DD_COMPANY_MAX_REGISTRY_PAGES", "8"))))
    max_external_pages = max(6, min(20, int(os.getenv("DD_COMPANY_MAX_EXTERNAL_PAGES", "12"))))
    enable_public_search = os.getenv("DD_COMPANY_ENABLE_WEB_SEARCH", "1") == "1"
    always_web_search = os.getenv("DD_COMPANY_ALWAYS_WEB_SEARCH", "1") == "1"

    official_url = _sanitize_url_for_crawl(primary_url)
    company_low = (company_name or "").strip().lower()
    official_is_registry = _is_registry_domain(_domain(official_url))
    try:
        official_q = dict(parse_qsl(urlparse(official_url).query))
        official_no = str(official_q.get("no") or "").strip().lower()
    except Exception:
        official_no = ""
    queue: List[Dict[str, Any]] = []
    queued_urls: set[str] = set()

    def enqueue(url: str, depth: int, source: str) -> None:
        clean = _sanitize_url_for_crawl(url)
        if not clean:
            return
        if not (clean.startswith("http://") or clean.startswith("https://")):
            return
        if clean in queued_urls:
            return
        queued_urls.add(clean)
        queue.append({"url": clean, "depth": depth, "source": source})

    # ???????????????????????
    for seed in _build_internal_seed_urls(official_url):
        enqueue(seed, 0, "official_seed")
    for seed in _parent_urls(official_url):
        enqueue(seed, 0, "official_parent")
    for seed in _discover_sitemap_urls(official_url, max_urls=sitemap_max_urls):
        enqueue(seed, 1, "official_sitemap")

    # ??????????????
    for u in (extra_urls or []):
        value = (u or "").strip()
        if not value:
            continue
        enqueue(value, 0, "extra_url")
        for parent in _parent_urls(value):
            enqueue(parent, 0, "extra_parent")

    evidence_rows: List[Dict[str, Any]] = []
    evidence_texts: List[str] = []
    evidence_text_map: Dict[str, str] = {}
    crawled_domains: set[str] = set()
    visited: set[str] = set()
    seen_titles: set[str] = set()
    seen_signatures: set[str] = set()
    trace_steps: List[Dict[str, Any]] = []

    did_search = False
    internal_pages = 0
    external_pages = 0
    registry_pages = 0

    def enqueue_public_search(seed_terms: Optional[List[str]] = None) -> None:
        nonlocal did_search
        if did_search or (not company_name) or (not enable_public_search):
            return
        did_search = True
        terms = seed_terms or []
        discovered_urls = _search_company_public_urls(
            company_name,
            official_url=official_url,
            limit=external_max_urls,
            search_terms=terms,
        )
        for discovered in discovered_urls:
            enqueue(discovered, 0, "public_search")
        trace_steps.append(
            {
                "status": "enqueue_public_search",
                "count": len(discovered_urls),
                "terms": terms[:6],
            }
        )

    idx = 0
    while len(evidence_rows) < max_pages:
        if (time.monotonic() - started) > crawl_max_sec:
            trace_steps.append({"status": "stop_by_timeout", "elapsed_sec": round(time.monotonic() - started, 2)})
            break

        if idx >= len(queue):
            if (not did_search) and company_name:
                seed_terms = _extract_company_search_terms(company_name, evidence_rows)
                enqueue_public_search(seed_terms)
                if idx >= len(queue):
                    break
            else:
                break

        item = queue[idx]
        idx += 1
        url = str(item.get("url") or "")
        depth = int(item.get("depth") or 0)
        source = str(item.get("source") or "unknown")

        if url in visited:
            continue
        visited.add(url)

        dom = _domain(url)
        html = _fetch_html(url, source_key=f"dd-company:{dom}")
        text = ""
        if html:
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
        else:
            # fallback?HTML ????????????? 0 ??
            text = _fetch_text(url, max_chars=8000)
            text = re.sub(r"\s+", " ", text).strip()

        if len(text) < 80:
            status = "fetch_failed" if (not html and not text) else "content_too_short"
            trace_steps.append({"url": url, "depth": depth, "source": source, "status": status})
            continue

        title = _extract_page_title(html) or url
        excerpt = _compact_text(text, 360)
        low_page = f"{title} {excerpt}".lower()
        if "404" in low_page or "找不到任何頁面" in low_page:
            trace_steps.append({"url": url, "depth": depth, "source": source, "status": "not_found_page"})
            continue
        if _is_registry_domain(dom):
            has_company_name = bool(company_low and company_low in low_page)
            has_same_no = bool(official_no and f"no={official_no}" in url.lower())
            if company_low and not has_company_name and not has_same_no:
                trace_steps.append({"url": url, "depth": depth, "source": source, "status": "registry_irrelevant"})
                continue
        title_key = title.strip().lower()
        excerpt_key = re.sub(r"\s+", " ", excerpt.lower())[:180]
        content_signature = f"{title_key}|{excerpt_key}"
        if content_signature in seen_signatures:
            trace_steps.append({"url": url, "depth": depth, "source": source, "status": "duplicate_title"})
            continue
        if title_key in seen_titles and len(excerpt_key) < 40:
            trace_steps.append({"url": url, "depth": depth, "source": source, "status": "duplicate_title"})
            continue
        seen_titles.add(title_key)
        seen_signatures.add(content_signature)
        registry_facts = _extract_registry_facts(text) if _is_registry_domain(dom) else {}
        is_internal = _same_reg_domain(official_url, url)
        is_registry = _is_registry_domain(dom)

        if is_registry and registry_pages >= max_registry_pages:
            trace_steps.append({"url": url, "depth": depth, "source": source, "status": "registry_cap"})
            continue
        if (not is_internal) and external_pages >= max_external_pages:
            trace_steps.append({"url": url, "depth": depth, "source": source, "status": "external_cap"})
            continue

        if is_internal:
            internal_pages += 1
        else:
            external_pages += 1
        if is_registry:
            registry_pages += 1

        row = {
            "url": url,
            "domain": dom,
            "title": title,
            "excerpt": excerpt,
            "content_chars": len(text),
            "source_type": "registry" if is_registry else "web",
            "crawl_source": source,
            "depth": depth,
            "is_official_site": is_internal,
            "key_facts": registry_facts,
        }
        evidence_rows.append(row)
        evidence_text = f"[{dom}] {title}\n{_compact_text(text, 3600)}"
        evidence_texts.append(evidence_text)
        evidence_text_map[url] = evidence_text
        crawled_domains.add(dom)
        trace_steps.append(
            {
                "url": url,
                "depth": depth,
                "source": source,
                "status": "ok",
                "title": title,
                "chars": len(text),
                "is_official_site": is_internal,
            }
        )

        if html:
            # ?????????????? BFS
            if is_internal and depth < internal_max_depth:
                for next_url in _extract_internal_links(url, html, max_links=internal_max_links):
                    enqueue(next_url, depth + 1, "official_internal")

            # ?????????? team/product/news?
            for next_url in _extract_candidate_company_links(url, html, company_name or "", limit=90):
                enqueue(next_url, depth + 1, "hint_link")

            # ???????????
            for parent in _parent_urls(url):
                enqueue(parent, max(depth - 1, 0), "parent_route")

            # ?????????????????
            if _is_registry_domain(dom):
                for official in _extract_official_site_candidates(url, html, company_name or ""):
                    for expanded in _parent_urls(official):
                        enqueue(expanded, 0, "registry_official")
                for related in _extract_related_public_urls_from_html(
                    html=html,
                    company_name=company_name or "",
                    official_no=official_no,
                    limit=24,
                ):
                    enqueue(related, depth + 1, "registry_related")

            for ext in _extract_external_signal_links(url, html, company_name or "", limit=40):
                enqueue(ext, depth + 1, "external_signal")

        if official_is_registry and (not did_search) and company_name:
            if registry_pages >= 2 or len(visited) >= 4:
                seed_terms = _extract_company_search_terms(company_name, evidence_rows)
                enqueue_public_search(seed_terms)
        elif always_web_search and (not did_search) and company_name:
            if internal_pages >= 3 or (len(visited) >= 6 and external_pages == 0):
                seed_terms = _extract_company_search_terms(company_name, evidence_rows)
                enqueue_public_search(seed_terms)

        # ?????????????????
        if len(evidence_rows) >= min_target_pages and idx >= len(queue):
            break

    elapsed = time.monotonic() - started
    if min_runtime > 0 and elapsed < min_runtime:
        time.sleep(min_runtime - elapsed)
        elapsed = time.monotonic() - started

    evidence_rows = _prioritize_company_evidence(evidence_rows, company_name or "", max_pages=max_pages)
    prioritized_texts: List[str] = []
    for row in evidence_rows:
        text = evidence_text_map.get(str(row.get("url") or ""))
        if text:
            prioritized_texts.append(text)
    if prioritized_texts:
        evidence_texts = prioritized_texts

    trace = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "seed_urls": [x["url"] for x in queue[: min(30, len(queue))] if isinstance(x, dict)],
        "visited": len(visited),
        "accepted_pages": len(evidence_rows),
        "internal_pages": internal_pages,
        "external_pages": external_pages,
        "registry_pages": registry_pages,
        "source_domains": sorted(crawled_domains),
        "elapsed_sec": round(elapsed, 2),
        "used_web_search": did_search,
        "official_url": official_url,
        "steps": trace_steps,
    }
    status_summary: Dict[str, int] = {}
    for step in trace_steps:
        status = str(step.get("status") or "unknown")
        status_summary[status] = status_summary.get(status, 0) + 1
    trace["status_summary"] = status_summary
    return evidence_rows, evidence_texts, trace


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _tokenize(text: str) -> List[str]:
    text = (text or "").replace("，", " ").replace(",", " ")
    out: List[str] = []
    for chunk in text.split():
        token = chunk.strip().lower()
        if len(token) >= 2:
            out.append(token)
    return list(dict.fromkeys(out))


def _text(*parts: str) -> str:
    return " ".join([(p or "") for p in parts]).strip()


def _overlap_score(text: str, keywords: List[str]) -> float:
    lower = (text or "").lower()
    score = 0.0
    for kw in keywords:
        if kw and kw.lower() in lower:
            score += 1.0 if len(kw) < 5 else 1.4
    return score


def _mk_vc_markdown(report_json: Dict[str, Any]) -> str:
    lines: List[str] = [f"# {report_json.get('title', '公司 DD 報告')}"]
    sections = [
        ("投資摘要", "executive_summary"),
        ("公司概覽", "company_snapshot"),
        ("團隊天花板（Management DD）", "management_dd"),
        ("技術護城河（Technology DD）", "technology_dd"),
        ("商業變現與市場驗證（Commercial DD）", "commercial_dd"),
        ("財務健全度（Financial DD）", "financial_dd"),
        ("法務與 ESG 風險（Legal & ESG DD）", "legal_esg_dd"),
        ("產品與技術", "product_tech"),
        ("市場與競爭", "market_competition"),
        ("團隊與成長訊號", "team_traction"),
        ("風險", "risks"),
        ("投資契合度", "investment_fit"),
        ("關聯假設", "relation_hypotheses"),
        ("建議追問", "key_questions"),
        ("待補文件清單", "dd_checklist_pending"),
        ("下一步", "next_actions"),
    ]
    for title, key in sections:
        value = report_json.get(key)
        if value is None:
            continue
        lines.append(f"\n## {title}")
        if isinstance(value, list):
            for item in value:
                lines.append(f"- {item}")
        elif isinstance(value, dict):
            label_map = {
                "name": "公司名稱",
                "source": "來源網址",
                "stage": "階段",
                "sector": "領域",
                "dd_signal_score": "DD 信號分數",
            }
            for dk, dv in value.items():
                label = label_map.get(str(dk), str(dk))
                lines.append(f"- {label}：{dv}")
        else:
            lines.append(str(value))

    signal_overview = report_json.get("public_signal_overview")
    if signal_overview:
        lines.append("\n## 公開訊號總覽")
        lines.append(f"- 相關新知：{signal_overview.get('insight_count', 0)}")
        lines.append(f"- 相關活動：{signal_overview.get('event_count', 0)}")
        lines.append(f"- 平均訊號分數：{signal_overview.get('avg_signal_score', 0)}")
        lines.append(f"- 來源多樣性：{signal_overview.get('source_diversity', 0)}")

    recent_evidence = report_json.get("recent_evidence") or []
    if recent_evidence:
        lines.append("\n## 近期證據")
        for item in recent_evidence[:8]:
            lines.append(f"- {item.get('date') or '日期未知'}｜{item.get('title') or '未命名'}｜{item.get('source') or '來源未知'}")

    metrics = report_json.get("evidence_metrics") or {}
    if metrics:
        lines.append("\n## 證據覆蓋度")
        lines.append(f"- 採納頁數：{metrics.get('accepted_pages', 0)}")
        lines.append(f"- 外部來源頁數：{metrics.get('external_pages', 0)}")
        lines.append(f"- 工商/登記來源頁數：{metrics.get('registry_pages', 0)}")
        domains = metrics.get("source_domains") or []
        if domains:
            lines.append(f"- 來源網域：{', '.join([str(x) for x in domains[:12]])}")

    evidence_pages = report_json.get("evidence_pages") or []
    if evidence_pages:
        lines.append("\n## 網頁證據來源")
        for row in evidence_pages[:10]:
            lines.append(f"- {row.get('domain') or '未知網域'}｜{row.get('title') or row.get('url')}")
            if row.get("url"):
                lines.append(f"  - {row.get('url')}")

    research_citations = report_json.get("research_citations") or []
    if research_citations:
        lines.append("\n## 深度研究引用")
        for row in _normalize_citation_rows(research_citations, limit=12):
            title = row.get("title") or "未命名來源"
            task_name = row.get("task_name") or row.get("task_id") or "來源"
            lines.append(f"- {task_name}｜{title}")
            if row.get("url"):
                lines.append(f"  - {row.get('url')}")

    return "\n".join(lines)


def _compact_text(value: str, max_len: int = 240) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:max_len]


def _build_public_signal_overview(
    candidate: Dict[str, Any], insights: List[Dict[str, Any]], events: List[Dict[str, Any]]
) -> Dict[str, Any]:
    all_scores = [float(x.get("final_score") or 0) for x in insights] + [float(x.get("score") or 0) for x in events]
    avg_signal = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
    sources = set()
    for item in insights:
        source = item.get("source_type")
        if source:
            sources.add(str(source))
    for item in events:
        source = item.get("source_type") or item.get("source_domain")
        if source:
            sources.add(str(source))

    timeline: List[Dict[str, Any]] = []
    for item in insights[:12]:
        dt = item.get("published_at")
        timeline.append(
            {
                "date": dt.isoformat() if dt else "",
                "title": item.get("title"),
                "source": item.get("source_type"),
                "url": item.get("url"),
                "signal_score": float(item.get("final_score") or 0),
            }
        )
    for item in events[:8]:
        dt = item.get("start_at")
        timeline.append(
            {
                "date": dt.isoformat() if dt else "",
                "title": item.get("title"),
                "source": item.get("source_type") or item.get("source_domain"),
                "url": item.get("url"),
                "signal_score": float(item.get("score") or 0),
            }
        )
    timeline.sort(key=lambda x: x.get("date") or "", reverse=True)

    return {
        "candidate": candidate.get("name"),
        "insight_count": len(insights),
        "event_count": len(events),
        "avg_signal_score": avg_signal,
        "source_diversity": len(sources),
        "recent_evidence": timeline[:10],
    }


def _vc_fallback_report(
    profile: Dict[str, Any],
    candidate: Dict[str, Any],
    evidences: List[str],
    public_signal_overview: Dict[str, Any],
) -> Dict[str, Any]:
    rationale = candidate.get("rationale") or "公開資訊與投資偏好有一定匹配"
    evidence_preview = [x[:180] for x in evidences[:5] if x]
    evidence_count = len([x for x in evidences if x.strip()])
    source_diversity = int(public_signal_overview.get("source_diversity") or 0)
    evidence_digest = "；".join([_compact_text(x, 90) for x in evidence_preview[:3]]) if evidence_preview else ""
    return {
        "title": f"{candidate.get('name', '候選團隊')} 公司 DD 報告",
        "executive_summary": (
            f"已依公開來源整理 {evidence_count} 份網頁證據與 {source_diversity} 個來源訊號。"
            f"該團隊與 {profile.get('firm_name', '基金')} thesis 具初步相關，建議進一步訪談驗證。"
        ),
        "company_snapshot": {
            "name": candidate.get("name"),
            "source": candidate.get("source_url"),
            "stage": candidate.get("stage"),
            "sector": candidate.get("sector"),
            "dd_signal_score": candidate.get("score"),
        },
        "product_tech": (
            f"公開頁面重點：{evidence_digest}。"
            if evidence_digest
            else "依爬取到的公開頁面，可初步判斷其產品定位與技術方向。"
        ),
        "market_competition": (
            f"目前可用公開證據 {evidence_count} 份，仍不足以完成完整市場模型；"
            "建議補齊 TAM/SAM/SOM、核心 KPI、客戶名單與競品替代率。"
        ),
        "team_traction": rationale,
        "management_dd": rationale,
        "technology_dd": (
            f"公開頁面重點：{evidence_digest}。"
            if evidence_digest
            else "可見資料仍不足，需補齊技術路線、IP 與實際部署資訊。"
        ),
        "commercial_dd": (
            f"目前可用公開證據 {evidence_count} 份；建議補齊 GTM、客戶與轉換率資料。"
        ),
        "financial_dd": "缺乏可公開驗證財務資料，需索取月營收、Burn Rate、Runway 與募資規劃。",
        "legal_esg_dd": "需檢查關聯交易、授權合約、法遵與 ESG 指標定義。",
        "risks": [
            "公開資料可能不完整或過時",
            "團隊商業化進度未知",
            "客戶驗證與續約資料不足",
            "目前為網路公開資料推估，尚未取得內部財務與客戶數據",
        ],
        "investment_fit": f"與 thesis 關鍵字匹配：{', '.join((profile.get('preferred_sectors') or [])[:3])}",
        "relation_hypotheses": [],
        "key_questions": [
            "目前營收與成長率？",
            "核心技術是否可防禦？",
            "下一輪募資時程與用途？",
        ],
        "next_actions": [
            "安排 30 分鐘 founder call",
            "索取 pitch deck 與財務摘要",
            "進行客戶/產業側訪談",
        ],
        "public_signal_overview": {
            "insight_count": public_signal_overview.get("insight_count", 0),
            "event_count": public_signal_overview.get("event_count", 0),
            "avg_signal_score": public_signal_overview.get("avg_signal_score", 0),
            "source_diversity": public_signal_overview.get("source_diversity", 0),
        },
        "recent_evidence": public_signal_overview.get("recent_evidence", []),
        "evidence_preview": evidence_preview,
    }


def _pick_first(data: Dict[str, Any], keys: List[str], default: Any = "") -> Any:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def _normalize_vc_report(
    report_json: Dict[str, Any],
    profile: Dict[str, Any],
    candidate: Dict[str, Any],
    evidence_pages: List[Dict[str, Any]],
    signal_overview: Dict[str, Any],
    crawl_trace: Dict[str, Any],
) -> Dict[str, Any]:
    data = dict(report_json or {})

    title = str(
        _pick_first(
            data,
            ["title", "報告標題", "report_title"],
            f"{candidate.get('name', '候選團隊')} 公司 DD 報告",
        )
    )
    exec_summary = str(
        _pick_first(
            data,
            ["executive_summary", "投資摘要", "summary", "整體結論"],
            "",
        )
    )
    if not exec_summary:
        accepted = int(crawl_trace.get("accepted_pages") or len(evidence_pages))
        exec_summary = (
            f"已整理 {accepted} 份公開網頁證據與 {signal_overview.get('source_diversity', 0)} 種來源。"
            f"目前結論為初步 DD，建議安排訪談確認商業與技術關鍵假設。"
        )

    snapshot_raw = data.get("company_snapshot")
    snapshot = snapshot_raw if isinstance(snapshot_raw, dict) else {}
    registry_facts: Dict[str, str] = {}
    for row in evidence_pages:
        facts = row.get("key_facts")
        if isinstance(facts, dict) and facts:
            registry_facts = {str(k): str(v) for k, v in facts.items() if v}
            break

    normalized_snapshot = {
        "name": snapshot.get("name") or snapshot.get("公司名稱") or candidate.get("name") or "-",
        "source": snapshot.get("source") or snapshot.get("來源") or candidate.get("source_url") or "-",
        "stage": snapshot.get("stage") or snapshot.get("階段") or candidate.get("stage") or "unknown",
        "sector": snapshot.get("sector") or snapshot.get("領域") or candidate.get("sector") or "AI",
        "dd_signal_score": snapshot.get("dd_signal_score") or snapshot.get("score") or candidate.get("score") or 0,
    }
    for k, v in registry_facts.items():
        normalized_snapshot[k] = normalized_snapshot.get(k) or v

    related_hypothesis: List[str] = []
    if registry_facts.get("地址"):
        related_hypothesis.append(f"公司登記地址：{registry_facts.get('地址')}，建議檢查同址關聯公司與關聯交易。")
    if registry_facts.get("代表人"):
        related_hypothesis.append(f"代表人：{registry_facts.get('代表人')}，建議穿透其歷史任職與關聯企業網絡。")
    if registry_facts.get("統一編號"):
        related_hypothesis.append(f"統編：{registry_facts.get('統一編號')}，可用於政府標案/裁判書/商標資料交叉查核。")

    evidence_external = int(crawl_trace.get("external_pages") or 0)
    evidence_registry = int(crawl_trace.get("registry_pages") or 0)
    evidence_total = int(crawl_trace.get("accepted_pages") or len(evidence_pages))
    source_domains = crawl_trace.get("source_domains") or []

    management_dd = str(
        _pick_first(
            data,
            ["management_dd", "team_traction", "團隊天花板", "團隊與成長訊號"],
            (
                "目前公開資料對核心團隊背景揭露有限。建議優先驗證創辦人與關鍵主管在相關產業的連續創業、"
                "交付大型專案與募資經驗。"
            ),
        )
    )
    technology_dd = str(
        _pick_first(
            data,
            ["technology_dd", "product_tech", "技術護城河", "產品與技術"],
            (
                "建議明確定位公司處於產業鏈哪一節點（產/儲/運/用），並補齊 IP、技術架構、"
                "資料來源合法性與 PoC 指標。"
            ),
        )
    )
    commercial_dd = str(
        _pick_first(
            data,
            ["commercial_dd", "market_competition", "商業變現與市場驗證", "市場與競爭"],
            (
                "需補充目標客戶、銷售循環、Pipeline、POC 轉正率與競品替代率，"
                "並說明為何客戶選擇此團隊而非成熟供應商。"
            ),
        )
    )
    financial_dd = str(
        _pick_first(
            data,
            ["financial_dd", "財務健全度"],
            (
                "目前財務揭露不足，建議索取近 12 個月損益、現金流、Burn Rate、Runway、"
                "及下一輪募資用途。"
            ),
        )
    )
    legal_esg_dd = str(
        _pick_first(
            data,
            ["legal_esg_dd", "法務與ESG風險", "legal_and_esg"],
            (
                "建議檢查技術授權條款、合規要求、關聯交易與 ESG 指標定義（如減碳量、治理機制）。"
            ),
        )
    )

    risks = data.get("risks")
    if not isinstance(risks, list):
        risks = [
            "公開資料可能不完整或過時",
            "團隊與技術可驗證資訊不足",
            "市場與商業模式缺乏足夠佐證",
        ]
    key_questions = data.get("key_questions")
    if not isinstance(key_questions, list):
        key_questions = [
            "核心產品與技術路線是什麼？目前成熟度與量產計畫為何？",
            "現有客戶/合作夥伴與營收結構為何？",
            "下一輪募資金額、用途與里程碑是什麼？",
        ]
    next_actions = data.get("next_actions")
    if not isinstance(next_actions, list):
        next_actions = [
            "安排 30-45 分鐘 founder 訪談，逐項驗證團隊與技術主張",
            "索取 pitch deck、財務摘要、客戶名單與合作合約樣本",
            "對關聯公司、關聯地址與核心人員做股權與法務穿透",
        ]

    relation_hypotheses = data.get("relation_hypotheses")
    if not isinstance(relation_hypotheses, list):
        relation_hypotheses = related_hypothesis

    normalized = {
        **data,
        "title": title,
        "executive_summary": exec_summary,
        "company_snapshot": normalized_snapshot,
        "management_dd": management_dd,
        "technology_dd": technology_dd,
        "commercial_dd": commercial_dd,
        "financial_dd": financial_dd,
        "legal_esg_dd": legal_esg_dd,
        "product_tech": data.get("product_tech") or technology_dd,
        "market_competition": data.get("market_competition") or commercial_dd,
        "team_traction": data.get("team_traction") or management_dd,
        "investment_fit": data.get("investment_fit")
        or f"與 {profile.get('firm_name', '基金')} thesis 關鍵字具初步匹配，建議進一步訪談確認。",
        "risks": risks[:10],
        "key_questions": key_questions[:12],
        "next_actions": next_actions[:10],
        "relation_hypotheses": relation_hypotheses[:10],
        "evidence_metrics": {
            "accepted_pages": evidence_total,
            "external_pages": evidence_external,
            "registry_pages": evidence_registry,
            "source_domains": source_domains,
        },
    }
    return normalized


def _normalize_citation_rows(value: Any, limit: int = 20) -> List[Dict[str, Any]]:
    if value is None:
        return []
    rows = value if isinstance(value, list) else [value]
    out: List[Dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(
                {
                    "title": str(row.get("title") or row.get("name") or row.get("url") or "未命名來源"),
                    "url": str(row.get("url") or ""),
                    "task_name": str(row.get("task_name") or row.get("task_id") or "來源"),
                    "task_id": str(row.get("task_id") or ""),
                    "domain": str(row.get("domain") or ""),
                    "score": row.get("score"),
                }
            )
            if len(out) >= limit:
                break
            continue

        text = str(row or "").strip()
        if not text:
            continue
        m = re.search(r"https?://\S+", text)
        url = m.group(0) if m else ""
        title = text.replace(url, "").strip(" -|") if url else text
        out.append(
            {
                "title": title or url or "未命名來源",
                "url": url,
                "task_name": "來源",
                "task_id": "",
                "domain": _domain(url) if url else "",
                "score": None,
            }
        )
        if len(out) >= limit:
            break
    return out


def _merge_deep_research_result(report_json: Dict[str, Any], deep_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(deep_result, dict):
        return report_json
    final = deep_result.get("final")
    if not isinstance(final, dict):
        return report_json

    merged = dict(report_json or {})

    if final.get("executive_summary"):
        merged["executive_summary"] = str(final.get("executive_summary"))
    if final.get("team_dd"):
        merged["management_dd"] = str(final.get("team_dd"))
    if final.get("tech_dd"):
        merged["technology_dd"] = str(final.get("tech_dd"))
    if final.get("business_dd"):
        merged["commercial_dd"] = str(final.get("business_dd"))
        merged["market_competition"] = str(final.get("business_dd"))
    if final.get("financial_dd"):
        merged["financial_dd"] = str(final.get("financial_dd"))
    if final.get("legal_dd"):
        merged["legal_esg_dd"] = str(final.get("legal_dd"))

    key_risks = final.get("key_risks")
    if isinstance(key_risks, list) and key_risks:
        current = merged.get("risks") if isinstance(merged.get("risks"), list) else []
        merged["risks"] = (current + [str(x) for x in key_risks if x])[:12]

    checklist = final.get("dd_checklist_pending")
    if isinstance(checklist, list) and checklist:
        merged["dd_checklist_pending"] = [str(x) for x in checklist if x][:12]

    citations = final.get("citations")
    normalized_citations = _normalize_citation_rows(citations, limit=20)
    if normalized_citations:
        merged["research_citations"] = normalized_citations

    merged["deep_research_trace"] = deep_result.get("trace", [])
    merged["deep_research_elapsed_sec"] = deep_result.get("elapsed_sec", 0)
    return merged


def generate_vc_dd_report(user_id: int, candidate_id: int, extra_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    profile = get_vc_profile(user_id)
    if not profile:
        raise ValueError("尚未建立 VC profile")

    candidate = get_vc_candidate(candidate_id)
    if not candidate:
        raise ValueError("找不到候選公司")
    if int(candidate.get("profile_id")) != int(profile.get("id")):
        raise ValueError("候選公司不屬於此使用者的 VC profile")

    urls: List[str] = []
    if candidate.get("source_url"):
        source = str(candidate["source_url"]).strip()
        if source.startswith("http://") or source.startswith("https://"):
            urls.append(source)
    for u in (extra_urls or []):
        value = (u or "").strip()
        if value and value not in urls and (value.startswith("http://") or value.startswith("https://")):
            urls.append(value)
    if not urls and str(candidate.get("name") or "").strip():
        urls.extend(
            _search_company_public_urls(
                str(candidate.get("name")),
                official_url=str(candidate.get("source_url") or ""),
                limit=8,
            )[:3]
        )
    urls = urls[:10]

    related = find_public_signals_for_candidate(
        candidate_name=str(candidate.get("name") or ""),
        source_url=candidate.get("source_url"),
        lookback_days=180,
        insight_limit=80,
        event_limit=40,
    )
    related_insights = related.get("insights", [])
    related_events = related.get("events", [])
    signal_overview = _build_public_signal_overview(candidate, related_insights, related_events)

    evidence_pages: List[Dict[str, Any]] = []
    evidence_texts: List[str] = []
    crawl_trace: Dict[str, Any] = {"steps": [], "seed_urls": urls, "accepted_pages": 0}
    if urls:
        evidence_pages, evidence_texts, crawl_trace = _collect_company_evidence(
            urls[0],
            urls[1:],
            company_name=str(candidate.get("name") or ""),
        )
    elif extra_urls:
        # 容錯：沒有主要網址時，仍嘗試 extra_urls 第一個
        evidence_pages, evidence_texts, crawl_trace = _collect_company_evidence(
            extra_urls[0],
            extra_urls[1:],
            company_name=str(candidate.get("name") or ""),
        )

    deep_research_enabled = os.getenv("DD_USE_DEEP_RESEARCH_AGENT", "1") == "1"
    deep_research_result: Optional[Dict[str, Any]] = None
    if deep_research_enabled and urls:
        try:
            deep_research_result = run_company_deep_research(
                company_name=str(candidate.get("name") or ""),
                company_url=str(urls[0]),
                thesis=str(profile.get("thesis") or ""),
                preferred_sectors=[str(x) for x in (profile.get("preferred_sectors") or []) if x],
                seed_evidence_urls=[str(x.get("url")) for x in evidence_pages if x.get("url")],
            )
        except Exception as exc:
            deep_research_result = {"error": str(exc), "trace": [{"stage": "deep_research", "status": "failed"}]}

    report_json: Optional[Dict[str, Any]] = None
    llm_enabled = bool(os.getenv("DEEPSEEK_API_KEY"))
    if llm_enabled and evidence_texts:
        llm = LLMClient()
        prompt = (
            "你是資深創投 DD 分析師。請根據下列公開資訊，產生繁體中文 JSON。"
            "欄位必須包含：title, executive_summary, company_snapshot, "
            "management_dd, technology_dd, commercial_dd, financial_dd, legal_esg_dd, "
            "product_tech, market_competition, team_traction, risks, investment_fit, relation_hypotheses, "
            "key_questions, next_actions, public_signal_overview, recent_evidence。"
            "company_snapshot 應為物件，risks/key_questions/next_actions 應為陣列。"
            "relation_hypotheses 應為陣列，列出可驗證的關聯假設（人、地址、股權、合作網路）。"
            "public_signal_overview 請包含 insight_count/event_count/avg_signal_score/source_diversity。"
            "recent_evidence 請輸出陣列，每筆包含 date/title/source/url/signal_score。"
            "請明確指出資料缺口，避免杜撰。若證據不足，要在 risks 與 next_actions 說清楚。"
            "如果證據主要來自工商登記，請明確標註「僅工商資料，不足以形成投資結論」。"
        )
        related_insight_text = "\n".join(
            [
                f"- {x.get('title')} | {x.get('source_type')} | score={x.get('final_score')} | url={x.get('url')}"
                for x in related_insights[:15]
            ]
        )
        related_event_text = "\n".join(
            [
                f"- {x.get('title')} | {x.get('source_type') or x.get('source_domain')} | score={x.get('score')} | url={x.get('url')}"
                for x in related_events[:10]
            ]
        )
        user_content = (
            f"VC thesis: {profile.get('thesis', '')}\n"
            f"firm: {profile.get('firm_name', '')}\n"
            f"candidate: {candidate.get('name', '')}\n"
            f"candidate_rationale: {candidate.get('rationale', '')}\n"
            f"source_urls: {urls}\n"
            f"public_signal_overview: {json.dumps(signal_overview, ensure_ascii=False)}\n"
            f"crawl_trace: {json.dumps(crawl_trace, ensure_ascii=False)}\n"
            f"deep_research: {json.dumps(deep_research_result or {}, ensure_ascii=False)}\n"
            f"evidence_pages: {json.dumps(evidence_pages[:10], ensure_ascii=False)}\n"
            f"related_insights:\n{related_insight_text}\n"
            f"related_events:\n{related_event_text}\n"
            f"web_evidences:\n\n" + "\n\n".join(evidence_texts[:3])
        )
        try:
            data = llm._post(
                {
                    "model": llm.model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.2,
                }
            )
            content = data["choices"][0]["message"]["content"]
            report_json = _parse_json_from_text(content)
        except Exception:
            report_json = None

    if not report_json:
        report_json = _vc_fallback_report(profile, candidate, evidence_texts, signal_overview)

    report_json = _normalize_vc_report(
        report_json=report_json,
        profile=profile,
        candidate=candidate,
        evidence_pages=evidence_pages,
        signal_overview=signal_overview,
        crawl_trace=crawl_trace,
    )
    report_json = _merge_deep_research_result(report_json, deep_research_result)

    report_json["public_signal_overview"] = {
        "insight_count": signal_overview.get("insight_count", 0),
        "event_count": signal_overview.get("event_count", 0),
        "avg_signal_score": signal_overview.get("avg_signal_score", 0),
        "source_diversity": signal_overview.get("source_diversity", 0),
    }
    report_json["recent_evidence"] = signal_overview.get("recent_evidence", [])
    report_json["evidence_urls"] = urls
    report_json["evidence_pages"] = evidence_pages[:12]
    report_json["crawl_trace"] = {
        "seed_urls": crawl_trace.get("seed_urls", []),
        "accepted_pages": crawl_trace.get("accepted_pages", 0),
        "source_domains": crawl_trace.get("source_domains", []),
        "elapsed_sec": crawl_trace.get("elapsed_sec", 0),
        "used_web_search": crawl_trace.get("used_web_search", False),
        "status_summary": crawl_trace.get("status_summary", {}),
    }
    if deep_research_result:
        report_json["deep_research_trace"] = deep_research_result.get("trace", [])
        report_json["deep_research_elapsed_sec"] = deep_research_result.get("elapsed_sec", 0)
    if int(crawl_trace.get("accepted_pages") or 0) == 0:
        report_json["crawl_warning"] = (
            "未抓到可用網頁證據。請檢查：1) 公司官網可公開訪問 2) 本機是否設了代理 3) 目標站是否阻擋機器流量。"
        )
    elif int(crawl_trace.get("external_pages") or 0) == 0:
        report_json["crawl_warning"] = (
            "目前缺少跨站外部來源（新聞/招聘/第三方資料庫），建議補充並交叉驗證，避免只看單一官網或單一來源。"
        )
    report_json["generated_for"] = {
        "user_id": user_id,
        "profile_id": profile.get("id"),
        "candidate_id": candidate_id,
    }

    markdown = _mk_vc_markdown(report_json)
    confidence = min(
        0.96,
        0.28
        + 0.06 * min(len(evidence_texts), 8)
        + 0.05 * min(signal_overview.get("source_diversity", 0), 5)
        + (0.08 if llm_enabled else 0.0),
    )

    row = upsert_vc_dd_report(
        profile_id=int(profile["id"]),
        candidate_id=candidate_id,
        title=report_json.get("title", f"{candidate.get('name', '候選公司')} DD 報告"),
        report_json=report_json,
        markdown=markdown,
        confidence=confidence,
    )

    return {
        "report": row,
        "report_json": report_json,
        "markdown": markdown,
        "related_signal_stats": {
            "insights": len(related_insights),
            "events": len(related_events),
        },
        "trace": {
            "evidence_pages": len(evidence_pages),
            "source_domains": crawl_trace.get("source_domains", []),
            "elapsed_sec": crawl_trace.get("elapsed_sec", 0),
            "used_web_search": crawl_trace.get("used_web_search", False),
            "external_pages": crawl_trace.get("external_pages", 0),
            "registry_pages": crawl_trace.get("registry_pages", 0),
            "status_summary": crawl_trace.get("status_summary", {}),
            "crawl_steps": crawl_trace.get("steps", []),
            "deep_research_elapsed_sec": (deep_research_result or {}).get("elapsed_sec", 0) if isinstance(deep_research_result, dict) else 0,
            "deep_research_trace": (deep_research_result or {}).get("trace", []) if isinstance(deep_research_result, dict) else [],
        },
    }


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip()).strip("-").lower()
    return s or "manual-target"


def _name_from_url(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        host = ""
    host = host.replace("www.", "")
    return host.split(".")[0] if host else "target-company"


def generate_vc_dd_report_direct(
    user_id: int,
    company_name: Optional[str] = None,
    company_url: Optional[str] = None,
    extra_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    profile = get_vc_profile(user_id)
    if not profile:
        raise ValueError("尚未建立 VC profile")

    company_name = (company_name or "").strip()
    company_url = (company_url or "").strip()
    if not company_url:
        raise ValueError("功能二請提供公司官網 URL（系統會以此網站為主做深度 DD）")

    if not company_name:
        company_name = _name_from_url(company_url)

    source_url = company_url or f"https://manual-input.local/{_slugify(company_name)}"
    summary_seed = f"手動指定公司 DD：{company_name}"
    if company_url:
        text = _fetch_text(company_url, max_chars=2200)
        if text:
            summary_seed = _compact_text(text, 360)

    candidate_id = upsert_vc_candidate(
        int(profile["id"]),
        {
            "name": company_name[:120],
            "summary": summary_seed,
            "source_url": source_url,
            "source_type": "manual_input",
            "stage": "unknown",
            "sector": ",".join((profile.get("preferred_sectors") or [])[:2]) or "AI",
            "score": 7.2,
            "rationale": "使用者手動指定公司，進入 DD 深度分析流程。",
            "contact_email": None,
            "raw_meta": {
                "manual": True,
                "company_name": company_name,
                "company_url": company_url,
                "direct_mode": "website_required",
            },
        },
    )

    return generate_vc_dd_report(user_id=user_id, candidate_id=candidate_id, extra_urls=extra_urls)


def _school_to_base_url(school: str) -> str:
    school = (school or "").strip()
    if not school:
        return ""
    if school.startswith("http://") or school.startswith("https://"):
        return school
    for key, value in SCHOOL_DOMAIN_HINTS.items():
        if key.lower() in school.lower():
            return value
    slug = re.sub(r"[^a-z0-9]+", "", school.lower())
    if not slug:
        return ""
    return f"https://{slug}.edu/"


def _discover_lab_links(base_url: str, limit: int = 40) -> List[Dict[str, str]]:
    headers = {"User-Agent": "ai-insight-pulse/0.1"}
    seed_pages = [base_url]
    for path in ACADEMIC_PATH_HINTS:
        seed_pages.append(urljoin(base_url, path))

    links: List[Dict[str, str]] = []
    seen_url: set[str] = set()
    seen_page: set[str] = set()

    for page in seed_pages:
        if page in seen_page:
            continue
        seen_page.add(page)
        resp = fetch_url(page, headers=headers, timeout=_http_timeout(), source_key=f"lab:{_domain(page)}", cache_ttl_hours=24)
        if not resp.ok:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a"):
            text = a.get_text(" ", strip=True)
            href = a.get("href")
            if not text or not href:
                continue
            low = f"{text} {href}".lower()
            if not any(k in low for k in LAB_KEYWORDS):
                continue
            url = urljoin(page, href)
            if url in seen_url:
                continue
            seen_url.add(url)
            links.append({"name": text[:160], "url": url})
            if len(links) >= limit:
                return links
    return links


def _extract_professor_name(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"(?:Prof\.?|Professor)\s+([A-Z][A-Za-z\-\s]{2,60})",
        r"([A-Za-z\u4e00-\u9fff]{2,20}教授)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return _compact_text(m.group(1), 80)
    return None


def _extract_research_focus(text: str, interests: List[str]) -> List[str]:
    focus_terms = [
        "ai",
        "machine learning",
        "deep learning",
        "llm",
        "nlp",
        "computer vision",
        "robotics",
        "data mining",
        "reinforcement learning",
        "醫療",
        "語言模型",
        "推薦系統",
        "金融科技",
        "multimodal",
    ]
    focus_terms.extend([x.lower() for x in interests if x])
    lower = (text or "").lower()
    hits: List[str] = []
    for term in focus_terms:
        if term and term in lower:
            hits.append(term)
    return list(dict.fromkeys(hits))[:8]


def _score_lab_candidate(
    lab_name: str,
    evidence_text: str,
    keywords: List[str],
    interests: List[str],
) -> Dict[str, Any]:
    combined = f"{lab_name} {evidence_text}"
    keyword_hits = _overlap_score(combined, keywords)
    interest_hits = _extract_research_focus(combined, interests)
    professor = _extract_professor_name(combined)

    pub_hint = 0.0
    lower = combined.lower()
    if "publication" in lower or "paper" in lower or "論文" in lower:
        pub_hint += 0.8
    if "project" in lower or "專案" in lower:
        pub_hint += 0.4

    score = 4.0 + min(4.5, keyword_hits * 0.35) + min(1.5, len(interest_hits) * 0.25) + pub_hint
    score = round(min(10.0, score), 2)

    rationale_parts = []
    if interest_hits:
        rationale_parts.append(f"研究方向命中：{', '.join(interest_hits[:4])}")
    if keyword_hits > 0:
        rationale_parts.append(f"履歷關鍵字命中 {round(keyword_hits, 1)}")
    if professor:
        rationale_parts.append(f"已抓到指導教授資訊：{professor}")
    if not rationale_parts:
        rationale_parts.append("具備 AI / 研究關鍵詞，但需人工驗證細節")

    return {
        "score": score,
        "professor": professor,
        "interest_hits": interest_hits,
        "keyword_hits": keyword_hits,
        "rationale": "；".join(rationale_parts),
    }


def _mk_grad_markdown(report_json: Dict[str, Any]) -> str:
    lines = ["# 實驗室 DD 報告", "", "## 總結", report_json.get("summary", "")]
    lines.append("\n## 建議申請實驗室")
    for lab in report_json.get("recommended_labs", []):
        lines.append(f"- {lab.get('school')} / {lab.get('lab_name')}（分數 {lab.get('score')}）")
        if lab.get("rationale"):
            lines.append(f"  - {lab.get('rationale')}")
        if lab.get("lab_url"):
            lines.append(f"  - {lab.get('lab_url')}")
    lines.append("\n## 下一步建議")
    for action in report_json.get("next_actions", []):
        lines.append(f"- {action}")
    return "\n".join(lines)


def run_grad_lab_dd(
    user_id: int,
    resume_text: str,
    target_schools: List[str],
    interests: Optional[List[str]] = None,
    degree_target: str = "master",
    target_count: int = 20,
) -> Dict[str, Any]:
    interests = interests or []
    profile = upsert_grad_dd_profile(
        user_id=user_id,
        resume_text=resume_text,
        target_schools=target_schools,
        interests=interests,
        degree_target=degree_target,
    )

    profile_id = int(profile["id"])
    clear_grad_lab_candidates(profile_id)

    keywords = _tokenize(resume_text)[:80]
    for tag in interests:
        keywords.extend(_tokenize(tag))
    keywords = list(dict.fromkeys(keywords))[:120]

    discovered: List[Dict[str, Any]] = []
    for school in target_schools:
        base_url = _school_to_base_url(school)
        if not base_url:
            continue
        links = _discover_lab_links(base_url, limit=35)
        if len(links) < 8:
            try:
                resp = fetch_url(
                    base_url,
                    headers={"User-Agent": "ai-insight-pulse/0.1"},
                    timeout=_http_timeout(),
                    source_key=f"lab:deep:{_domain(base_url)}",
                    cache_ttl_hours=24,
                )
                if resp.ok:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    deep_links: List[Dict[str, str]] = []
                    for a in soup.find_all("a"):
                        text = a.get_text(" ", strip=True)
                        href = a.get("href")
                        if not text or not href:
                            continue
                        low = f"{text} {href}".lower()
                        if any(marker in low for marker in ["department", "computer", "cs", "ee", "research", "college"]):
                            next_url = urljoin(base_url, href)
                            deep_links.extend(_discover_lab_links(next_url, limit=20))
                        if len(deep_links) >= 40:
                            break
                    links.extend(deep_links)
            except Exception:
                pass

        dedup_links = []
        seen_urls = set()
        for link in links:
            key = (link.get("url") or "").strip().lower()
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            dedup_links.append(link)
        links = dedup_links[:40]

        for link in links:
            evidence_text = _fetch_text(link["url"], max_chars=4000)
            lab_eval = _score_lab_candidate(
                lab_name=link["name"],
                evidence_text=evidence_text,
                keywords=keywords,
                interests=interests,
            )
            discovered.append(
                {
                    "school": school,
                    "lab_name": link["name"],
                    "lab_url": link["url"],
                    "professor": lab_eval["professor"],
                    "score": lab_eval["score"],
                    "rationale": lab_eval["rationale"],
                    "evidence": {
                        "keyword_hits": lab_eval["keyword_hits"],
                        "interest_hits": lab_eval["interest_hits"],
                        "base_url": base_url,
                        "content_preview": _compact_text(evidence_text, 280),
                    },
                }
            )

    if not discovered:
        for school in target_schools[:20]:
            discovered.append(
                {
                    "school": school,
                    "lab_name": f"{school} AI/ML Research Groups",
                    "lab_url": _school_to_base_url(school),
                    "professor": None,
                    "score": 5.0,
                    "rationale": "尚未抓到完整 lab 資訊，建議人工補充校系頁面",
                    "evidence": {"fallback": True},
                }
            )

    discovered = sorted(discovered, key=lambda x: x.get("score", 0), reverse=True)
    selected = discovered[: max(10, min(target_count, 60))]

    for lab in selected:
        upsert_grad_lab_candidate(profile_id, lab)

    top_labs = list_grad_lab_candidates(profile_id, limit=15)
    report_json = {
        "summary": "已根據履歷、研究興趣與目標學校整理公開研究群資訊，建議先投遞 10-15 組高分實驗室，再人工驗證教授近年研究主題。",
        "degree_target": degree_target,
        "target_schools": target_schools,
        "interests": interests,
        "recommended_labs": top_labs,
        "next_actions": [
            "依高分實驗室準備客製化 SOP 與研究計畫",
            "逐一閱讀近 1-2 年論文與專案",
            "寄送精準套磁信並附上履歷與作品",
        ],
    }

    markdown = _mk_grad_markdown(report_json)
    report_row = insert_grad_dd_report(profile_id, report_json, markdown)

    return {
        "profile": profile,
        "report": report_row,
        "report_json": report_json,
        "markdown": markdown,
        "candidates": list_grad_lab_candidates(profile_id, limit=50),
    }


def generate_grad_dd_report_direct(
    user_id: int,
    resume_text: str,
    target_school: Optional[str] = None,
    lab_url: Optional[str] = None,
    professor_name: Optional[str] = None,
    interests: Optional[List[str]] = None,
    degree_target: str = "master",
) -> Dict[str, Any]:
    interests = interests or []
    target_school = (target_school or "").strip()
    lab_url = (lab_url or "").strip()
    professor_name = (professor_name or "").strip()

    if not target_school and not lab_url and not professor_name:
        raise ValueError("請至少提供學校名稱、實驗室網址或教授姓名其中之一")

    schools = [target_school] if target_school else []
    if not schools and lab_url:
        schools = [_domain(lab_url)]
    if not schools:
        schools = ["target-school"]

    profile = upsert_grad_dd_profile(
        user_id=user_id,
        resume_text=resume_text or "N/A",
        target_schools=schools,
        interests=interests,
        degree_target=degree_target,
    )
    profile_id = int(profile["id"])
    clear_grad_lab_candidates(profile_id)

    keywords = _tokenize(resume_text or "")
    for tag in interests:
        keywords.extend(_tokenize(tag))
    keywords = list(dict.fromkeys(keywords))[:120]

    discovered: List[Dict[str, Any]] = []
    crawl_trace: List[Dict[str, Any]] = []
    if lab_url:
        text = _fetch_text(lab_url, max_chars=5000)
        eval_result = _score_lab_candidate(
            lab_name=professor_name or _name_from_url(lab_url),
            evidence_text=text,
            keywords=keywords,
            interests=interests,
        )
        crawl_trace.append({"mode": "lab_url", "url": lab_url, "chars": len(text)})
        discovered.append(
            {
                "school": target_school or _domain(lab_url),
                "lab_name": professor_name or _name_from_url(lab_url),
                "lab_url": lab_url,
                "professor": professor_name or eval_result.get("professor"),
                "score": eval_result["score"],
                "rationale": eval_result["rationale"],
                "evidence": {
                    "keyword_hits": eval_result["keyword_hits"],
                    "interest_hits": eval_result["interest_hits"],
                    "content_preview": _compact_text(text, 300),
                    "direct_mode": True,
                },
            }
        )

    if target_school:
        base_url = _school_to_base_url(target_school)
        links = _discover_lab_links(base_url, limit=60) if base_url else []
        crawl_trace.append({"mode": "school_scan", "school": target_school, "base_url": base_url, "links": len(links)})
        for link in links:
            if lab_url and link.get("url") == lab_url:
                continue
            text = _fetch_text(link["url"], max_chars=4000)
            probe = _text(link.get("name", ""), text)
            if professor_name and professor_name.lower() not in probe.lower():
                continue
            lab_eval = _score_lab_candidate(
                lab_name=link["name"],
                evidence_text=text,
                keywords=keywords,
                interests=interests,
            )
            discovered.append(
                {
                    "school": target_school,
                    "lab_name": link["name"],
                    "lab_url": link["url"],
                    "professor": lab_eval["professor"],
                    "score": lab_eval["score"],
                    "rationale": lab_eval["rationale"],
                    "evidence": {
                        "keyword_hits": lab_eval["keyword_hits"],
                        "interest_hits": lab_eval["interest_hits"],
                        "content_preview": _compact_text(text, 260),
                        "base_url": base_url,
                    },
                }
            )

    if not discovered and target_school:
        base_url = _school_to_base_url(target_school)
        discovered.extend(
            [
                {
                    "school": target_school,
                    "lab_name": f"{target_school} AI Lab（需人工確認）",
                    "lab_url": base_url,
                    "professor": professor_name or None,
                    "score": 5.4,
                    "rationale": "目前站點可擷取資料不足，建議補上明確系所或 lab URL 以提高精度。",
                    "evidence": {"fallback": True, "base_url": base_url},
                },
                {
                    "school": target_school,
                    "lab_name": f"{target_school} ML Research Group（需人工確認）",
                    "lab_url": base_url,
                    "professor": professor_name or None,
                    "score": 5.2,
                    "rationale": "目前站點可擷取資料不足，建議補上教授姓名或官方實驗室頁面。",
                    "evidence": {"fallback": True, "base_url": base_url},
                },
            ]
        )

    if not discovered and professor_name:
        discovered.append(
            {
                "school": target_school or "target-school",
                "lab_name": f"{professor_name} Lab",
                "lab_url": lab_url or "",
                "professor": professor_name,
                "score": 5.8,
                "rationale": "目前僅有教授姓名，建議補上實驗室網址可提高報告品質。",
                "evidence": {"fallback": True},
            }
        )

    discovered = sorted(discovered, key=lambda x: x.get("score", 0), reverse=True)
    top_labs = discovered[:15]
    for lab in top_labs:
        upsert_grad_lab_candidate(profile_id, lab)

    report_json = {
        "summary": "已依輸入的學校 / 教授 / 實驗室網址，整理可申請目標與公開資訊摘要。",
        "degree_target": degree_target,
        "target_schools": schools,
        "interests": interests,
        "focus_professor": professor_name or None,
        "recommended_labs": list_grad_lab_candidates(profile_id, limit=15),
        "crawl_trace": crawl_trace,
        "next_actions": [
            "確認教授近兩年論文與招生公告",
            "撰寫客製化研究計畫與套磁信",
            "優先投遞前 5 個高分實驗室",
        ],
    }
    markdown = _mk_grad_markdown(report_json)
    report_row = insert_grad_dd_report(profile_id, report_json, markdown)
    return {
        "profile": profile,
        "report": report_row,
        "report_json": report_json,
        "markdown": markdown,
        "candidates": list_grad_lab_candidates(profile_id, limit=50),
    }


def shortlist_grad_labs(user_id: int, candidate_ids: List[int]) -> Dict[str, Any]:
    profile = get_grad_dd_profile(user_id)
    if not profile:
        raise ValueError("尚未建立學術 DD profile")
    count = mark_grad_lab_shortlist(int(profile["id"]), candidate_ids)
    return {
        "profile_id": int(profile["id"]),
        "shortlisted": count,
        "items": list_grad_lab_candidates(int(profile["id"]), limit=50, shortlisted_only=True),
    }


def get_grad_dd_latest(user_id: int) -> Dict[str, Any]:
    profile = get_grad_dd_profile(user_id)
    if not profile:
        raise ValueError("尚未建立學術 DD profile")
    report = get_latest_grad_dd_report(int(profile["id"]))
    return {
        "profile": profile,
        "report": report,
        "candidates": list_grad_lab_candidates(int(profile["id"]), limit=50),
    }


def get_grad_dd_list(user_id: int, limit: int = 20) -> Dict[str, Any]:
    profile = get_grad_dd_profile(user_id)
    if not profile:
        raise ValueError("尚未建立學術 DD profile")
    reports = list_grad_dd_reports(int(profile["id"]), limit=limit)
    return {
        "profile": profile,
        "reports": reports,
        "candidates": list_grad_lab_candidates(int(profile["id"]), limit=50),
    }


def get_vc_dd_list(user_id: int, limit: int = 20) -> Dict[str, Any]:
    profile = get_vc_profile(user_id)
    if not profile:
        raise ValueError("尚未建立 VC profile")
    reports = list_vc_dd_reports(int(profile["id"]), limit=limit)
    return {"profile": profile, "reports": reports}
