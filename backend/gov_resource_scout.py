from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from .db import list_gov_resource_records, upsert_gov_resource_record
from .http_client import fetch_url


@dataclass(frozen=True)
class GovSource:
    name: str
    url: str
    source_category: str  # gov_award | gov_subsidy | incubator_space | exhibitor_list | exhibit_schedule
    authority: float = 7.0


CORE_SOURCES: List[GovSource] = [
    GovSource("智慧城市展", "https://smartcity.org.tw/", "exhibitor_list", 8.5),
    GovSource("台灣國際智慧能源週", "https://www.energytaiwan.com.tw/", "exhibitor_list", 8.2),
    GovSource("台灣輔具暨長照大展", "https://www.chanchao.com.tw/healthcare/", "exhibitor_list", 7.8),
    GovSource("台北世貿展期", "https://www.twtc.com.tw/zh-tw/exhibitionSchedule", "exhibit_schedule", 7.5),
    GovSource("南港展覽館展期", "https://www.tainex.com.tw/service/exhibitionschedule", "exhibit_schedule", 7.5),
    GovSource("創業圓夢網", "https://startup.sme.gov.tw/", "gov_subsidy", 7.8),
    GovSource("中小企業署", "https://www.sme.gov.tw/", "gov_subsidy", 7.8),
    GovSource("TTA", "https://www.taiwanarena.tech/", "incubator_space", 7.6),
]


QUERY_PACK = [
    ("gov_award", "環境部 資源循環 績優企業 得獎名單"),
    ("gov_award", "台灣 新創 獎項 得獎名單"),
    ("gov_subsidy", "台灣 新創 補助 名單 經濟部"),
    ("gov_subsidy", "SBIR 台灣 得獎 名單"),
    ("gov_subsidy", "A+ 企業創新研發補助 名單"),
    ("incubator_space", "台灣 創業加速器 育成中心 進駐團隊 名單"),
    ("exhibitor_list", "智慧城市展 參展廠商 名單"),
    ("exhibitor_list", "台灣國際智慧能源週 參展廠商 名單"),
    ("exhibitor_list", "台灣輔具暨長照大展 參展廠商 名單"),
]


def _timeout() -> float:
    return float(os.getenv("MVP_HTTP_TIMEOUT", "10"))


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
    keep: List[Tuple[str, str]] = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        if k.lower().startswith("utm_"):
            continue
        keep.append((k, v))
    return parsed._replace(query=urlencode(keep, doseq=True), fragment="").geturl()


def _fetch_html(url: str, source_key: str) -> str:
    resp = fetch_url(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=_timeout(),
        source_key=source_key,
        cache_ttl_hours=12,
    )
    if not resp.ok:
        return ""
    return resp.text or ""


def _search_duckduckgo(query: str, limit: int = 12) -> List[str]:
    search_url = "https://duckduckgo.com/html/?" + urlencode({"q": query})
    html = _fetch_html(search_url, "gov-search")
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
                pass
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


def _guess_year(*texts: str) -> Optional[int]:
    blob = " ".join([x or "" for x in texts])
    # 西元年
    for m in re.finditer(r"(20[1-3]\d)", blob):
        y = int(m.group(1))
        if 2018 <= y <= 2035:
            return y
    # 民國年 112/113...
    for m in re.finditer(r"\b(1[0-3]\d)\b", blob):
        roc = int(m.group(1))
        y = roc + 1911
        if 2018 <= y <= 2035:
            return y
    return None


def _text_clean(value: str, max_len: int = 180) -> str:
    text = re.sub(r"\s+", " ", (value or "")).strip(" \t\r\n-｜|:：")
    return text[:max_len]


def _extract_program_title(soup: BeautifulSoup) -> str:
    for tag in ["h1", "h2", "title"]:
        node = soup.find(tag)
        if node:
            txt = _text_clean(node.get_text(" ", strip=True), 160)
            if txt:
                return txt
    return ""


def _table_header_map(table) -> Tuple[List[str], Dict[str, int]]:
    headers = [re.sub(r"\s+", "", th.get_text(" ", strip=True)) for th in table.find_all("th")]
    mapping: Dict[str, int] = {}
    aliases = {
        "company": ["公司", "公司名稱", "廠商", "廠商名稱", "團隊", "企業", "單位", "參展商", "參展廠商", "品牌"],
        "award": ["獎項", "獲獎項目", "獎別", "類別"],
        "subsidy": ["補助", "補助項目", "計畫", "方案"],
        "year": ["年度", "年份"],
        "date": ["日期", "時間", "展期"],
        "booth": ["攤位", "攤位號碼", "Booth", "BoothNo", "booth"],
        "org": ["主辦", "機構", "學校", "育成單位", "單位名稱"],
    }
    for idx, h in enumerate(headers):
        for key, vals in aliases.items():
            if any(v.lower() in h.lower() for v in vals):
                mapping.setdefault(key, idx)
    return headers, mapping


def _parse_records_from_table(
    source: GovSource,
    table,
    source_url: str,
    year_floor: int,
    max_rows: int = 300,
) -> List[Dict[str, Any]]:
    headers, m = _table_header_map(table)
    rows = table.find_all("tr")
    if len(rows) <= 1:
        return []
    out: List[Dict[str, Any]] = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        texts = [_text_clean(c.get_text(" ", strip=True), 220) for c in cells]
        if not any(texts):
            continue
        company = texts[m["company"]] if "company" in m and m["company"] < len(texts) else ""
        org = texts[m["org"]] if "org" in m and m["org"] < len(texts) else ""
        award = texts[m["award"]] if "award" in m and m["award"] < len(texts) else ""
        subsidy = texts[m["subsidy"]] if "subsidy" in m and m["subsidy"] < len(texts) else ""
        date_text = texts[m["date"]] if "date" in m and m["date"] < len(texts) else ""
        booth_no = texts[m["booth"]] if "booth" in m and m["booth"] < len(texts) else ""
        year = _guess_year(*(texts[:6])) or _guess_year(source_url)
        if year is not None and year < year_floor:
            continue

        # 專用 parser 重點：展會參展商名單
        if source.source_category == "exhibitor_list":
            if not company:
                # fallback: 找最像公司名的欄位
                company = max(texts, key=len) if texts else ""
            if len(company) < 2:
                continue

        if source.source_category in {"gov_award", "gov_subsidy", "incubator_space"} and not (company or org):
            continue

        a = tr.find("a")
        row_url = _normalize_url(urljoin(source_url, a.get("href"))) if (a and a.get("href")) else None

        record_type_map = {
            "gov_award": "award",
            "gov_subsidy": "subsidy",
            "incubator_space": "incubator",
            "exhibitor_list": "exhibitor",
            "exhibit_schedule": "exhibit_schedule",
        }
        record_type = record_type_map[source.source_category]
        out.append(
            {
                "record_type": record_type,
                "source_category": source.source_category,
                "program_name": "",
                "event_name": "",
                "company_name": company or None,
                "organization_name": org or None,
                "year": year,
                "award_name": award or None,
                "subsidy_name": subsidy or None,
                "date_text": date_text or None,
                "booth_no": booth_no or None,
                "url": row_url or None,
                "source_url": source_url,
                "source_domain": _domain(source_url),
                "region": "taiwan",
                "score": source.authority,
                "raw_meta": {"headers": headers, "row_text": texts[:8]},
            }
        )
        if len(out) >= max_rows:
            break
    return out


def _parse_exhibitor_cards(source: GovSource, html: str, source_url: str, year_floor: int) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    selectors = [
        "[class*='exhibitor']",
        "[class*='vendor']",
        "[class*='company']",
        ".card",
        ".item",
    ]
    seen = set()
    for sel in selectors:
        for node in soup.select(sel):
            txt = _text_clean(node.get_text(" ", strip=True), 220)
            if len(txt) < 2:
                continue
            if any(k in txt.lower() for k in ["login", "filter", "search", "more", "read more"]):
                continue
            # 嘗試擷取較短的公司名（通常第一行）
            company_name = _text_clean(txt.split("｜")[0].split("|")[0].split(" - ")[0], 120)
            if len(company_name) < 2:
                continue
            key = company_name.lower()
            if key in seen:
                continue
            seen.add(key)
            a = node.find("a")
            row_url = _normalize_url(urljoin(source_url, a.get("href"))) if (a and a.get("href")) else None
            year = _guess_year(txt, source_url)
            if year and year < year_floor:
                continue
            out.append(
                {
                    "record_type": "exhibitor",
                    "source_category": source.source_category,
                    "program_name": None,
                    "event_name": _extract_program_title(soup) or source.name,
                    "company_name": company_name,
                    "organization_name": None,
                    "year": year,
                    "award_name": None,
                    "subsidy_name": None,
                    "date_text": None,
                    "booth_no": None,
                    "url": row_url or None,
                    "source_url": source_url,
                    "source_domain": _domain(source_url),
                    "region": "taiwan",
                    "score": source.authority - 0.2,
                    "raw_meta": {"card_text": txt},
                }
            )
            if len(out) >= 200:
                return out
    return out


def _parse_exhibit_schedule(source: GovSource, html: str, source_url: str, year_floor: int) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    tables = soup.find_all("table")
    for table in tables:
        recs = _parse_records_from_table(source, table, source_url, year_floor, max_rows=200)
        if recs:
            for r in recs:
                if r["record_type"] == "exhibit_schedule":
                    if not (r.get("company_name") or r.get("organization_name")):
                        # 展期頁通常 event_name 在「公司欄」位置，這裡重映射
                        row_txt = " ".join((r.get("raw_meta") or {}).get("row_text") or [])
                        r["event_name"] = _text_clean(row_txt, 140)
                        r["company_name"] = None
                out.append(r)
            if out:
                return out

    # fallback: 抓列表項目（展名 + 日期）
    for li in soup.find_all(["li", "tr", "div"]):
        txt = _text_clean(li.get_text(" ", strip=True), 260)
        if len(txt) < 8:
            continue
        if not any(k in txt for k in ["展", "Expo", "展覽", "展期"]):
            continue
        y = _guess_year(txt, source_url)
        if y and y < year_floor:
            continue
        a = li.find("a")
        out.append(
            {
                "record_type": "exhibit_schedule",
                "source_category": source.source_category,
                "program_name": None,
                "event_name": _text_clean(txt, 140),
                "company_name": None,
                "organization_name": None,
                "year": y,
                "award_name": None,
                "subsidy_name": None,
                "date_text": txt,
                "booth_no": None,
                "url": _normalize_url(urljoin(source_url, a.get("href"))) if (a and a.get("href")) else None,
                "source_url": source_url,
                "source_domain": _domain(source_url),
                "region": "taiwan",
                "score": source.authority - 0.5,
                "raw_meta": {"fallback": True},
            }
        )
        if len(out) >= 120:
            break
    return out


def _parse_page(source: GovSource, html: str, source_url: str, year_floor: int) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_program_title(soup)
    records: List[Dict[str, Any]] = []
    if source.source_category == "exhibit_schedule":
        records.extend(_parse_exhibit_schedule(source, html, source_url, year_floor))
        return records

    tables = soup.find_all("table")
    for table in tables:
        records.extend(_parse_records_from_table(source, table, source_url, year_floor))

    if source.source_category == "exhibitor_list":
        records.extend(_parse_exhibitor_cards(source, html, source_url, year_floor))

    # fallback 名單頁：從 anchor list 抓可能公司名
    if not records:
        seen = set()
        for a in soup.find_all("a"):
            text = _text_clean(a.get_text(" ", strip=True), 160)
            if len(text) < 2:
                continue
            if any(k in text.lower() for k in ["more", "login", "報名", "返回", "首頁", "全部"]):
                continue
            if source.source_category == "exhibitor_list" and len(text) > 60:
                continue
            row_url = _normalize_url(urljoin(source_url, a.get("href"))) if a.get("href") else None
            key = f"{text.lower()}::{row_url or ''}"
            if key in seen:
                continue
            seen.add(key)
            year = _guess_year(text, title, source_url)
            if year and year < year_floor:
                continue
            record_type_map = {
                "gov_award": "award",
                "gov_subsidy": "subsidy",
                "incubator_space": "incubator",
                "exhibitor_list": "exhibitor",
                "exhibit_schedule": "exhibit_schedule",
            }
            company_name = text if source.source_category in {"exhibitor_list", "incubator_space"} else None
            records.append(
                {
                    "record_type": record_type_map[source.source_category],
                    "source_category": source.source_category,
                    "program_name": title or source.name,
                    "event_name": title if source.source_category == "exhibitor_list" else None,
                    "company_name": company_name,
                    "organization_name": None,
                    "year": year,
                    "award_name": text if source.source_category == "gov_award" else None,
                    "subsidy_name": text if source.source_category == "gov_subsidy" else None,
                    "date_text": None,
                    "booth_no": None,
                    "url": row_url,
                    "source_url": source_url,
                    "source_domain": _domain(source_url),
                    "region": "taiwan",
                    "score": source.authority - 1.0,
                    "raw_meta": {"fallback_anchor": True},
                }
            )
            if len(records) >= 200:
                break

    # 補 program/event title
    for r in records:
        if not r.get("program_name"):
            r["program_name"] = title or source.name
        if source.source_category == "exhibitor_list" and not r.get("event_name"):
            r["event_name"] = title or source.name
        r["score"] = float(r.get("score") or source.authority)
    return records


def _source_from_url(url: str, category: str) -> GovSource:
    dom = _domain(url) or "unknown"
    return GovSource(name=dom, url=url, source_category=category, authority=6.5)


def run_gov_resource_scout(
    years_back: int = 5,
    categories: Optional[List[str]] = None,
    include_search: bool = True,
) -> Dict[str, Any]:
    now_year = datetime.now().year
    year_floor = now_year - max(1, years_back) + 1
    category_set = set(categories or [])
    if not category_set:
        category_set = {"gov_award", "gov_subsidy", "incubator_space", "exhibitor_list", "exhibit_schedule"}

    selected_sources = [s for s in CORE_SOURCES if s.source_category in category_set]
    traces: List[Dict[str, Any]] = []
    inserted = 0

    def process_source(source: GovSource, url: str) -> None:
        nonlocal inserted
        html = _fetch_html(url, source_key=f"gov:{source.source_category}:{_domain(url)}")
        if not html:
            traces.append({"source": source.name, "url": url, "category": source.source_category, "status": "fetch_failed", "parsed": 0, "inserted": 0})
            return
        recs = _parse_page(source, html, url, year_floor)
        count_before = inserted
        for rec in recs:
            try:
                rec["source_url"] = url
                rec["source_domain"] = _domain(url)
                upsert_gov_resource_record(rec)
                inserted += 1
            except Exception:
                continue
        traces.append(
            {
                "source": source.name,
                "url": url,
                "category": source.source_category,
                "status": "ok",
                "parsed": len(recs),
                "inserted": inserted - count_before,
            }
        )

    for source in selected_sources:
        process_source(source, source.url)

    if include_search:
        for cat, query in QUERY_PACK:
            if cat not in category_set:
                continue
            for year in range(year_floor, now_year + 1):
                q = f"{year} {query}"
                urls = _search_duckduckgo(q, limit=6)
                traces.append({"source": "search", "category": cat, "query": q, "status": "ok", "scanned": len(urls)})
                for url in urls[:4]:
                    process_source(_source_from_url(url, cat), url)

    # 匯總
    sample = list_gov_resource_records(limit=50, year_from=year_floor)
    by_cat: Dict[str, int] = {}
    for row in sample:
        cat = str(row.get("source_category") or "")
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return {
        "years_back": years_back,
        "year_floor": year_floor,
        "categories": sorted(category_set),
        "inserted_attempts": inserted,
        "trace": traces,
        "sample_records": sample[:20],
        "sample_counts": by_cat,
    }

