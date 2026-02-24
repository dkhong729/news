import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup

from .http_client import fetch_url


@dataclass
class ScrapedItem:
    title: str
    url: str
    source: str
    published_at: Optional[date]
    snippet: str
    event_type: Optional[str] = None
    location_hint: Optional[str] = None


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def match_keywords(text: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def _safe_date(y: int, mo: int, d: int) -> Optional[date]:
    try:
        return date(y, mo, d)
    except Exception:
        return None


def extract_date(text: str) -> Optional[date]:
    m = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text)
    if m:
        y, mo, d = map(int, m.groups())
        return _safe_date(y, mo, d)

    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    if m:
        y, mo, d = map(int, m.groups())
        return _safe_date(y, mo, d)

    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        mo, d = map(int, m.groups())
        today = datetime.now().date()
        candidate = _safe_date(today.year, mo, d)
        if candidate is None:
            return None
        if candidate < today - timedelta(days=30):
            candidate = _safe_date(today.year + 1, mo, d)
        return candidate

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", text)
    if m:
        mo, d = map(int, m.groups())
        today = datetime.now().date()
        candidate = _safe_date(today.year, mo, d)
        if candidate is None:
            return None
        if candidate < today - timedelta(days=30):
            candidate = _safe_date(today.year + 1, mo, d)
        return candidate

    month_map = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    m = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
        r"sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:,\s*(20\d{2}))?\b",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        mon_str = m.group(1).lower()
        mo = month_map.get(mon_str)
        d = int(m.group(2))
        y = int(m.group(3)) if m.group(3) else datetime.now().year
        if mo:
            candidate = _safe_date(y, mo, d)
            if candidate is None:
                return None
            if not m.group(3):
                today = datetime.now().date()
                if candidate < today - timedelta(days=30):
                    candidate = _safe_date(today.year + 1, mo, d)
            return candidate

    return None


LISTING_URL_MARKERS = [
    "seminar_list",
    "/archive",
    "?page=",
]


def looks_like_listing_url(link: str) -> bool:
    lower = (link or "").lower()
    if not lower:
        return True
    try:
        parsed = urlparse(lower)
        path = (parsed.path or "").rstrip("/")
        query = parsed.query or ""
    except Exception:
        path = ""
        query = ""
    if path in {"/events", "/seminars", "/seminar-list", "/seminar_list", "/activities", "/calendar", "/search"}:
        return True
    if path.endswith("/list") or path.endswith("/lists") or path.endswith("/archive"):
        return True
    if "/category/" in path or "/tag/" in path:
        return True
    if "page=" in query or "category=" in query:
        return True
    for marker in LISTING_URL_MARKERS:
        if marker in lower:
            return True
    return False


def infer_event_type(text: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ["demo day", "路演", "pitch"]):
        return "Demo Day"
    if any(x in t for x in ["summit", "高峰會", "峰會", "年會"]):
        return "高峰會"
    if any(x in t for x in ["workshop", "工作坊"]):
        return "工作坊"
    if any(x in t for x in ["seminar", "講座", "論壇"]):
        return "論壇/講座"
    return "活動"


def is_within_window(
    d: Optional[date],
    past_days: int,
    future_days: int,
    allow_none: bool = True,
) -> bool:
    if d is None:
        return allow_none
    today = datetime.now().date()
    lower = today - timedelta(days=past_days)
    upper = today + timedelta(days=future_days)
    return lower <= d <= upper


def _http_timeout() -> float:
    return float(os.getenv("MVP_HTTP_TIMEOUT", "8"))


def _fetch_page_text(url: str) -> str:
    headers = {"User-Agent": "ai-insight-pulse/0.1"}
    resp = fetch_url(url, headers=headers, source_key=f"detail:{url}", timeout=_http_timeout())
    if not resp.ok:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(" ", strip=True)


def _extract_date_from_soup(soup: BeautifulSoup, raw_text: str) -> Optional[date]:
    for tag in soup.find_all("time"):
        dt_text = (tag.get("datetime") or tag.get_text(" ", strip=True) or "").strip()
        d = extract_date(dt_text)
        if d:
            return d

    meta_fields = [
        ("meta", "property", "article:published_time"),
        ("meta", "property", "article:modified_time"),
        ("meta", "property", "og:updated_time"),
        ("meta", "name", "publish_date"),
        ("meta", "name", "date"),
        ("meta", "itemprop", "startDate"),
    ]
    for tag_name, attr_name, attr_value in meta_fields:
        tag = soup.find(tag_name, attrs={attr_name: attr_value})
        if tag:
            val = (tag.get("content") or tag.get("value") or "").strip()
            d = extract_date(val)
            if d:
                return d

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        txt = script.get_text(" ", strip=True)
        if not txt:
            continue
        m = re.search(r'"startDate"\s*:\s*"([^"]+)"', txt)
        if m:
            d = extract_date(m.group(1))
            if d:
                return d
        m2 = re.search(r'"datePublished"\s*:\s*"([^"]+)"', txt)
        if m2:
            d = extract_date(m2.group(1))
            if d:
                return d

    return extract_date(raw_text)


def _fetch_page_detail(url: str) -> tuple[str, Optional[date]]:
    headers = {"User-Agent": "ai-insight-pulse/0.1"}
    resp = fetch_url(url, headers=headers, source_key=f"detail:{url}", timeout=_http_timeout())
    if not resp.ok:
        return "", None
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    detected = _extract_date_from_soup(soup, text)
    return text, detected


def _short_summary_from_detail(text: str, max_len: int = 220) -> str:
    compact = " ".join((text or "").split())
    if not compact:
        return ""
    return compact[:max_len]


def scrape_site(
    url: str,
    keywords: List[str],
    max_age_days: int,
    past_days: Optional[int] = None,
    future_days: int = 0,
    strict_future: bool = False,
    fetch_detail: bool = False,
) -> List[ScrapedItem]:
    items: List[ScrapedItem] = []
    max_anchors = int(os.getenv("MVP_MAX_ANCHORS_PER_SITE", "500"))
    max_items = int(os.getenv("MVP_MAX_ITEMS_PER_SITE", "30"))

    headers = {"User-Agent": "ai-insight-pulse/0.1"}
    resp = fetch_url(url, headers=headers, source_key=f"site:{url}", timeout=_http_timeout())
    if not resp.ok:
        return items

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a")[:max_anchors]:
        title = a.get_text(strip=True)
        href = a.get("href")
        if not title or not href:
            continue
        if len(title) < 6:
            continue
        if not match_keywords(title, keywords):
            continue

        link = urljoin(url, href)
        if looks_like_listing_url(link):
            continue
        published = extract_date(title)
        detail_text = ""
        if fetch_detail or strict_future:
            try:
                detail_text, detail_date = _fetch_page_detail(link)
                if published is None:
                    published = detail_date or extract_date(detail_text)
            except Exception:
                published = None

        today = datetime.now().date()
        if strict_future:
            if not published:
                continue
            if published < today:
                continue
            if future_days > 0 and published > today + timedelta(days=future_days):
                continue
        else:
            window_past_days = max_age_days if past_days is None else past_days
            if not is_within_window(published, window_past_days, future_days, allow_none=True):
                continue

        items.append(
            ScrapedItem(
                title=title,
                url=link,
                source=url,
                published_at=published,
                snippet=_short_summary_from_detail(detail_text) or title,
                event_type=infer_event_type(f"{title} {detail_text}"),
            )
        )

        if len(items) >= max_items:
            break

    return items
