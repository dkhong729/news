from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .db import (
    clear_vc_candidates,
    get_vc_profile,
    list_vc_candidates,
    mark_vc_shortlist,
    upsert_vc_candidate,
)
from .http_client import fetch_url


@dataclass
class ScoutResult:
    profile_id: int
    generated: int


DEFAULT_COMPANY_DISCOVERY_SOURCES = [
    "https://appworks.tw/",
    "https://garageplus.asia/",
    "https://www.tta.tw/",
    "https://www.taccplus.com/",
    "https://meet.bnext.com.tw/",
    "https://www.accupass.com/search?keyword=demo%20day",
    "https://www.innovex.com.tw/",
    "https://starfabx.com/",
    "https://www.sparklabstaiwan.com/",
    "https://startupgarage.ntu.edu.tw/",
    "https://www.ntupreneur.ntu.edu.tw/",
    "https://iaps.nycu.edu.tw/",
    # 政府/補助/獎項/展會名單（海量搜）
    "https://startup.sme.gov.tw/",
    "https://www.sme.gov.tw/",
    "https://service.moea.gov.tw/EE514/tw/aisearch.aspx",  # 經濟部資源入口（搜尋）
    "https://www.taiwanarena.tech/",
    "https://www.taipeiexpo.tw/zh-tw",
    "https://smartcity.org.tw/",
    "https://smartcity.org.tw/m_login.php?lang=tw",  # 智慧城市展入口
    "https://www.energytaiwan.com.tw/",
    "https://www.chanchao.com.tw/healthcare/",
    "https://www.twtc.com.tw/zh-tw/exhibitionSchedule",
    "https://www.tainex.com.tw/service/exhibitionschedule",
]

SOURCE_AUTHORITY = {
    "appworks.tw": 1.4,
    "garageplus.asia": 1.3,
    "tta.tw": 1.2,
    "taccplus.com": 1.2,
    "innovex.com.tw": 1.2,
    "meet.bnext.com.tw": 1.1,
    "accupass.com": 1.0,
    "sparklabstaiwan.com": 1.1,
    "startupgarage.ntu.edu.tw": 1.1,
    "startup.sme.gov.tw": 1.2,
    "sme.gov.tw": 1.2,
    "smartcity.org.tw": 1.2,
    "energytaiwan.com.tw": 1.1,
    "twtc.com.tw": 1.0,
    "tainex.com.tw": 1.0,
    "taiwanarena.tech": 1.1,
}

COMPANY_SIGNAL_KEYWORDS: Dict[str, float] = {
    "startup": 1.2,
    "company": 1.0,
    "team": 0.8,
    "founder": 1.1,
    "cofounder": 1.1,
    "新創": 1.3,
    "團隊": 1.0,
    "創辦": 1.0,
    "募資": 1.2,
    "seed": 1.2,
    "pre-seed": 1.2,
    "series a": 1.2,
    "series b": 1.2,
    "demo day": 1.5,
    "accelerator": 1.0,
    "加速器": 1.0,
    "路演": 1.0,
    "pitch": 1.0,
    "saas": 0.8,
    "b2b": 0.8,
    "ai": 0.5,
    "得獎": 1.1,
    "獲獎": 1.1,
    "補助": 1.3,
    "國科會": 1.0,
    "經濟部": 1.0,
    "入選": 1.1,
    "進駐": 1.1,
    "育成": 1.2,
    "加速": 1.1,
    "參展": 1.2,
    "展會": 1.0,
    "智慧城市展": 1.4,
    "能源週": 1.2,
}

STAGE_PATTERNS = [
    ("pre-seed", "pre-seed"),
    ("seed", "seed"),
    ("series a", "series-a"),
    ("series b", "series-b"),
    ("series c", "series-c"),
    ("天使輪", "angel"),
    ("種子輪", "seed"),
    ("a 輪", "series-a"),
    ("b 輪", "series-b"),
]

SECTOR_HINTS = {
    "agent": "AI Agent",
    "llm": "LLM",
    "enterprise": "Enterprise AI",
    "devtool": "Developer Tools",
    "developer": "Developer Tools",
    "health": "Healthcare AI",
    "醫療": "Healthcare AI",
    "fintech": "FinTech AI",
    "製造": "Industrial AI",
    "robot": "Robotics",
    "robotics": "Robotics",
}

RESEARCH_NOISE_KEYWORDS = [
    "paper",
    "benchmark",
    "arxiv",
    "dataset",
    "show hn",
    "lecture",
    "course",
    "github",
    "commit",
    "pull request",
    "研究生",
]

NAV_WORDS = [
    "read more",
    "learn more",
    "more",
    "contact",
    "about",
    "news",
    "blog",
    "privacy",
    "terms",
    "登入",
    "註冊",
    "首頁",
    "返回",
    "上一頁",
    "下一頁",
    "prev",
    "next",
]

GOVERNMENT_RESOURCE_QUERY_PACK = [
    # 獎項/企業共創/資源
    "台灣 新創 獎項 得獎名單",
    "環境部 資源循環 績優企業 得獎名單",
    "企業共創 新創 得獎 團隊 台灣",
    # 補助/研發/行銷/國際鏈結
    "台灣 新創 補助 名單 經濟部",
    "SBIR 台灣 得獎 名單 新創",
    "A+ 企業創新研發補助 名單",
    "國科會 新創 補助 名單",
    "國際鏈結 新創 補助 台灣 名單",
    # 空間進駐/育成
    "台灣 創業加速器 育成中心 進駐團隊 名單",
    "創育機構 進駐 新創 名單 台灣",
    # 展會/參展商名單
    "智慧城市展 參展廠商 名單 台灣",
    "台灣輔具暨長期照護大展 參展廠商 名單",
    "台灣國際智慧能源週 參展廠商 名單",
    "台灣國際淨零永續展 參展廠商 名單",
    "南港展覽館 展期 科技 AI 新創",
    "台北世貿 展期 科技 新創",
]

GOVERNMENT_RESOURCE_SOURCE_HINTS = [
    "startup.sme.gov.tw",
    "sme.gov.tw",
    "moenv.gov.tw",
    "moea.gov.tw",
    "nstc.gov.tw",
    "taiwanarena.tech",
    "smartcity.org.tw",
    "energytaiwan.com.tw",
    "chanchao.com.tw",
    "twtc.com.tw",
    "tainex.com.tw",
]


def _http_timeout() -> float:
    return float(os.getenv("MVP_HTTP_TIMEOUT", "8"))


def _tokenize(text: str) -> List[str]:
    normalized = (text or "").replace("，", " ").replace(",", " ").replace("/", " ").replace("|", " ")
    out: List[str] = []
    for chunk in normalized.split():
        token = chunk.strip().lower()
        if len(token) >= 2:
            out.append(token)
    return list(dict.fromkeys(out))


def _match_score(text: str, keywords: List[str]) -> float:
    lower = (text or "").lower()
    score = 0.0
    for kw in keywords:
        if not kw:
            continue
        if kw in lower:
            score += 1.0 if len(kw) <= 4 else 1.4
    return score


def _domain(url: str) -> str:
    try:
        return (urlparse(url or "").netloc or "").lower().replace("www.", "")
    except Exception:
        return ""


def _text(*parts: str) -> str:
    return " ".join([p or "" for p in parts]).strip().lower()


def _contains_any(text: str, keywords: List[str]) -> bool:
    lower = (text or "").lower()
    return any(k in lower for k in keywords)


def _company_signal_score(text: str) -> float:
    lower = (text or "").lower()
    score = 0.0
    for kw, weight in COMPANY_SIGNAL_KEYWORDS.items():
        if kw in lower:
            score += weight
    return score


def _extract_stage(text: str) -> str:
    lower = (text or "").lower()
    for marker, stage in STAGE_PATTERNS:
        if marker in lower:
            return stage
    return "unknown"


def _guess_sector(text: str, preferred_sectors: List[str]) -> str:
    lower = (text or "").lower()
    for sec in preferred_sectors:
        if sec and sec.lower() in lower:
            return sec
    for marker, sector in SECTOR_HINTS.items():
        if marker in lower:
            return sector
    return preferred_sectors[0] if preferred_sectors else "AI"


def _is_pre_series_c(stage: str) -> bool:
    if stage in {"pre-seed", "seed", "series-a", "series-b", "angel", "unknown"}:
        return True
    return False


def _sanitize_name(name: str) -> str:
    raw = re.sub(r"\s+", " ", (name or "")).strip()
    if not raw:
        return ""

    splitters = ["｜", "|", " - ", " — ", "：", ":", "／", "/"]
    candidates = [raw]
    for sep in splitters:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            if parts:
                candidates.extend(parts)

    cleanup_words = [
        "demo day",
        "accelerator",
        "新創",
        "團隊",
        "報名",
        "活動",
        "論壇",
        "講座",
        "workshop",
        "summit",
        "conference",
        "pitch",
        "session",
    ]

    best = ""
    for c in candidates:
        v = c.strip()
        for w in cleanup_words:
            v = re.sub(re.escape(w), "", v, flags=re.IGNORECASE)
        v = re.sub(r"\s+", " ", v).strip(" -|:：")
        if len(v) < 2:
            continue
        if len(v) > 90:
            continue
        if not best or len(v) < len(best):
            best = v

    if not best:
        best = raw[:90]

    best = best.strip()
    if len(best) > 120:
        best = best[:120]
    return best


def _looks_like_noise_anchor(title: str, url: str) -> bool:
    t = _text(title, url)
    if len((title or "").strip()) < 4:
        return True
    if any(w in t for w in NAV_WORDS):
        return True
    if _contains_any(t, RESEARCH_NOISE_KEYWORDS):
        return True
    return False


def _fetch_page(url: str, source_key: str) -> str:
    resp = fetch_url(
        url,
        headers={"User-Agent": "ai-insight-pulse/0.1"},
        timeout=_http_timeout(),
        source_key=source_key,
        cache_ttl_hours=24,
    )
    if not resp.ok:
        return ""
    return resp.text


def _search_duckduckgo_links(query: str, limit: int = 12) -> List[Dict[str, str]]:
    search_url = f"https://duckduckgo.com/html/?q={query}"
    html = _fetch_page(search_url, source_key="vc-scout:search")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, str]] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        title = a.get_text(" ", strip=True)
        if not href or not title:
            continue
        full = urljoin(search_url, href)
        # duckduckgo redirect link
        if "duckduckgo.com/l/?" in full and "uddg=" in full:
            try:
                from urllib.parse import parse_qs, unquote

                q = parse_qs(urlparse(full).query)
                full = unquote((q.get("uddg") or [""])[0])
            except Exception:
                pass
        if not (full.startswith("http://") or full.startswith("https://")):
            continue
        key = f"{title.lower()}::{full.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title[:220], "url": full})
        if len(out) >= limit:
            break
    return out


def _extract_table_candidates(source_url: str, html: str, max_rows: int = 120) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict[str, str]] = []
    seen = set()
    company_col_hints = ["公司", "團隊", "廠商", "單位", "企業", "品牌", "新創", "進駐"]

    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        rows = table.find_all("tr")
        if not rows:
            continue
        company_col_idx: Optional[int] = None
        for idx, h in enumerate(headers):
            if any(k in h for k in company_col_hints):
                company_col_idx = idx
                break

        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            if company_col_idx is not None and company_col_idx < len(cells):
                cell = cells[company_col_idx]
            else:
                cell = max(cells, key=lambda c: len(c.get_text(" ", strip=True)))
            name = _sanitize_name(cell.get_text(" ", strip=True))
            if not name or len(name) < 2:
                continue
            if any(x in name.lower() for x in ["公告", "說明", "下載", "名單", "附件"]):
                continue
            a = cell.find("a")
            row_url = urljoin(source_url, a.get("href")) if (a and a.get("href")) else source_url
            key = f"{name.lower()}::{row_url.lower()}"
            if key in seen:
                continue
            seen.add(key)
            results.append({"title": name, "url": row_url})
            if len(results) >= max_rows:
                return results
    return results


def _extract_candidate_links(source_url: str, html: str, max_links: int = 180) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[Dict[str, str]] = []
    seen = set()

    for a in soup.find_all("a"):
        title = a.get_text(" ", strip=True)
        href = a.get("href")
        if not title or not href:
            continue
        full_url = urljoin(source_url, href)
        key = f"{title.lower()}::{full_url.lower()}"
        if key in seen:
            continue
        seen.add(key)

        if _looks_like_noise_anchor(title, full_url):
            continue
        if len(title) > 180:
            continue

        links.append({"title": title[:180], "url": full_url})
        if len(links) >= max_links:
            break

    return links


def _page_snippet(url: str, source_domain: str) -> str:
    html = _fetch_page(url, source_key=f"vc-snippet:{source_domain}")
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:800]


def _candidate_score(
    source_url: str,
    title: str,
    link_url: str,
    snippet: str,
    thesis_keywords: List[str],
    preferred_sectors: List[str],
) -> Dict[str, Any]:
    combined = _text(title, link_url, snippet)
    source_domain = _domain(source_url)

    thesis_bonus = _match_score(combined, thesis_keywords)
    signal_bonus = _company_signal_score(combined)

    authority_bonus = SOURCE_AUTHORITY.get(source_domain, 0.8)
    taiwan_bonus = 0.8 if any(k in combined for k in ["台灣", "taiwan", ".tw"]) else 0.0

    stage = _extract_stage(combined)
    stage_bonus = 0.8 if _is_pre_series_c(stage) else -0.8

    penalty = 0.0
    if _contains_any(combined, RESEARCH_NOISE_KEYWORDS):
        penalty += 1.2

    score = round(max(0.0, min(10.0, 3.2 + thesis_bonus * 0.7 + signal_bonus + authority_bonus + taiwan_bonus + stage_bonus - penalty)), 2)

    rationale_parts = [
        f"thesis 命中 {thesis_bonus:.1f}",
        f"公司訊號 {signal_bonus:.1f}",
        f"來源權重 {authority_bonus:.1f}",
    ]
    if stage != "unknown":
        rationale_parts.append(f"階段判定 {stage}")
    if taiwan_bonus > 0:
        rationale_parts.append("台灣關聯 +0.8")
    if penalty > 0:
        rationale_parts.append(f"噪音扣分 -{penalty:.1f}")

    return {
        "score": score,
        "stage": stage,
        "sector": _guess_sector(combined, preferred_sectors),
        "rationale": "；".join(rationale_parts),
        "thesis_bonus": thesis_bonus,
        "signal_bonus": signal_bonus,
        "penalty": penalty,
        "source_domain": source_domain,
    }


def _extract_candidates_from_source(
    source_url: str,
    thesis_keywords: List[str],
    preferred_sectors: List[str],
    target_count_hint: int,
) -> Dict[str, Any]:
    source_domain = _domain(source_url)
    html = _fetch_page(source_url, source_key=f"vc-source:{source_domain}")
    if not html:
        return {"items": [], "trace": {"source": source_url, "status": "fetch_failed", "scanned": 0, "accepted": 0}}

    links = _extract_candidate_links(source_url, html)
    table_links = _extract_table_candidates(source_url, html, max_rows=120)
    if table_links:
        existing = {f"{x['title'].lower()}::{x['url'].lower()}" for x in links}
        for row in table_links:
            key = f"{row['title'].lower()}::{row['url'].lower()}"
            if key in existing:
                continue
            existing.add(key)
            links.append(row)
    results: List[Dict[str, Any]] = []
    accepted = 0

    for link in links:
        title = link["title"]
        url = link["url"]

        quick_text = _text(title, url)
        quick_signal = _company_signal_score(quick_text)
        quick_thesis = _match_score(quick_text, thesis_keywords)

        # 只在有機會時才抓詳情，避免過慢
        snippet = ""
        if quick_signal + quick_thesis >= 1.3:
            snippet = _page_snippet(url, source_domain)

        score_pack = _candidate_score(
            source_url=source_url,
            title=title,
            link_url=url,
            snippet=snippet,
            thesis_keywords=thesis_keywords,
            preferred_sectors=preferred_sectors,
        )

        score = float(score_pack["score"])
        if score < 5.2:
            continue

        name = _sanitize_name(title)
        if len(name) < 2:
            continue

        results.append(
            {
                "name": name,
                "summary": (snippet or title)[:600],
                "source_url": url,
                "source_type": source_domain or "startup_web",
                "stage": score_pack["stage"],
                "sector": score_pack["sector"],
                "score": score,
                "rationale": score_pack["rationale"],
                "contact_email": None,
                "raw_meta": {
                    "source": source_url,
                    "title": title,
                    "thesis_bonus": score_pack["thesis_bonus"],
                    "signal_bonus": score_pack["signal_bonus"],
                    "penalty": score_pack["penalty"],
                },
            }
        )
        accepted += 1
        if accepted >= max(20, target_count_hint // 2):
            break

    trace = {
        "source": source_url,
        "status": "ok",
        "scanned": len(links),
        "accepted": accepted,
        "table_rows": len(table_links),
    }
    return {"items": results, "trace": trace}


def _source_list(custom_sources: List[str]) -> List[str]:
    if custom_sources:
        cleaned = [x.strip() for x in custom_sources if x and x.strip()]
        if cleaned:
            return cleaned[:30]

    env_sources = [x.strip() for x in os.getenv("VC_SCOUT_SOURCES", "").split(",") if x.strip()]
    if env_sources:
        return env_sources[:30]

    return DEFAULT_COMPANY_DISCOVERY_SOURCES


def _government_query_list() -> List[str]:
    years = [str(y) for y in range(2022, 2027)]  # 先覆蓋近 5 年（可透過搜尋補回）
    queries = list(GOVERNMENT_RESOURCE_QUERY_PACK)
    for y in years:
        queries.extend(
            [
                f"{y} 智慧城市展 參展廠商 名單",
                f"{y} 能源週 參展廠商 名單 台灣",
                f"{y} 新創 補助 得獎 名單 台灣",
            ]
        )
    return queries


def _extract_candidates_from_query(
    query: str,
    thesis_keywords: List[str],
    preferred_sectors: List[str],
    target_count_hint: int,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    accepted = 0
    search_hits = _search_duckduckgo_links(query, limit=16)
    for hit in search_hits:
        title = hit["title"]
        url = hit["url"]
        dom = _domain(url)
        if not any(h in dom for h in GOVERNMENT_RESOURCE_SOURCE_HINTS) and dom not in {"expo.taipei", "www.chanchao.com.tw"}:
            # query 模式仍接受部分非官方新聞/名單頁，但降低優先
            pass
        snippet = _page_snippet(url, dom) if (len(results) < max(4, target_count_hint // 8)) else ""
        score_pack = _candidate_score(
            source_url=url,
            title=title,
            link_url=url,
            snippet=snippet,
            thesis_keywords=thesis_keywords,
            preferred_sectors=preferred_sectors,
        )
        # 政府補助/名單語境給一點加成，避免被一般文章壓掉
        title_text = _text(title, snippet)
        if any(k in title_text for k in ["補助", "得獎", "入選", "參展", "進駐", "育成", "新創"]):
            score_pack["score"] = min(10.0, float(score_pack["score"]) + 1.0)

        score = float(score_pack["score"])
        if score < 5.0:
            continue

        name = _sanitize_name(title)
        if len(name) < 2:
            continue

        results.append(
            {
                "name": name,
                "summary": (snippet or title)[:600],
                "source_url": url,
                "source_type": dom or "search_result",
                "stage": score_pack["stage"],
                "sector": score_pack["sector"],
                "score": round(score, 2),
                "rationale": f"政府資源/展會查詢：{query}；{score_pack['rationale']}",
                "contact_email": None,
                "raw_meta": {"source_query": query, "search": True},
            }
        )
        accepted += 1
        if accepted >= max(8, target_count_hint // 6):
            break

    return {
        "items": results,
        "trace": {
            "source": f"SEARCH:{query}",
            "status": "ok",
            "scanned": len(search_hits),
            "accepted": accepted,
        },
    }


def run_vc_scout(user_id: int, target_count: int = 50, source_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    profile = get_vc_profile(user_id)
    if not profile:
        raise ValueError("尚未建立 VC profile")

    thesis_keywords = _tokenize(profile.get("thesis") or "")
    for sector in profile.get("preferred_sectors") or []:
        thesis_keywords.extend(_tokenize(str(sector)))
    for stage in profile.get("preferred_stages") or []:
        thesis_keywords.extend(_tokenize(str(stage)))
    thesis_keywords = list(dict.fromkeys(thesis_keywords))[:80]

    preferred_sectors = [str(x) for x in (profile.get("preferred_sectors") or []) if str(x).strip()]

    source_list = _source_list(source_urls or [])
    raw_candidates: List[Dict[str, Any]] = []
    traces: List[Dict[str, Any]] = []

    for src in source_list:
        packed = _extract_candidates_from_source(
            source_url=src,
            thesis_keywords=thesis_keywords,
            preferred_sectors=preferred_sectors,
            target_count_hint=target_count,
        )
        raw_candidates.extend(packed["items"])
        traces.append(packed["trace"])

    if os.getenv("VC_SCOUT_ENABLE_GOV_QUERY_PACK", "1") == "1":
        query_cap = int(os.getenv("VC_SCOUT_GOV_QUERY_CAP", "12"))
        for query in _government_query_list()[:query_cap]:
            packed = _extract_candidates_from_query(
                query=query,
                thesis_keywords=thesis_keywords,
                preferred_sectors=preferred_sectors,
                target_count_hint=target_count,
            )
            raw_candidates.extend(packed["items"])
            traces.append(packed["trace"])

    by_key: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}

    for item in raw_candidates:
        source_url = (item.get("source_url") or "").strip().lower()
        name = (item.get("name") or "").strip().lower()
        if not name:
            continue

        key = f"{source_url}::{name}"
        if key not in by_key or float(item.get("score") or 0) > float(by_key[key].get("score") or 0):
            by_key[key] = item

    for item in by_key.values():
        name_key = (item.get("name") or "").strip().lower()
        if name_key not in by_name or float(item.get("score") or 0) > float(by_name[name_key].get("score") or 0):
            by_name[name_key] = item

    ranked = sorted(by_name.values(), key=lambda x: float(x.get("score") or 0), reverse=True)
    ranked = ranked[: max(15, min(target_count, 100))]

    clear_vc_candidates(int(profile["id"]))
    for item in ranked:
        upsert_vc_candidate(int(profile["id"]), item)

    return {
        "profile_id": int(profile["id"]),
        "used_sources": source_list,
        "gov_query_pack_enabled": os.getenv("VC_SCOUT_ENABLE_GOV_QUERY_PACK", "1") == "1",
        "generated": len(ranked),
        "trace": traces,
        "candidates": list_vc_candidates(int(profile["id"]), limit=min(100, target_count)),
    }


def shortlist_vc_candidates(user_id: int, candidate_ids: List[int]) -> Dict[str, Any]:
    profile = get_vc_profile(user_id)
    if not profile:
        raise ValueError("尚未建立 VC profile")
    count = mark_vc_shortlist(int(profile["id"]), candidate_ids)
    return {
        "profile_id": int(profile["id"]),
        "shortlisted": count,
        "items": list_vc_candidates(int(profile["id"]), limit=60, shortlisted_only=True),
    }
