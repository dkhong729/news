from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .db import (
    cleanup_low_quality_content,
    content_quality_audit,
    get_source_health,
    list_all_active_user_sources,
    purge_listing_events,
    prune_stale_data,
    record_source_health,
    upsert_event,
    upsert_normalized_item,
    upsert_raw_item,
    upsert_score,
)
from .crawlers.base import RawItem
from .crawlers.github_trending import GitHubTrendingCrawler
from .crawlers.hn import HackerNewsCrawler
from .crawlers.reddit import RedditCrawler
from .llm_client import LLMClient
from .mvp_scraper import ScrapedItem, match_keywords, normalize_url, scrape_site

TZ_TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str
    bucket: str  # event | insight
    item_kind: str  # event | paper | post | web
    authority: float
    region_hint: str = "global"


EVENT_KEYWORDS = [
    "ai",
    "demo day",
    "新創",
    "創業",
    "創投",
    "加速器",
    "年會",
    "論壇",
    "講座",
    "交流會",
    "工作坊",
    "黑客松",
    "徵件",
    "路演",
    "媒合",
    "pitch",
    "meetup",
    "活動",
    "報名",
    "event",
    "研討會",
    "conference",
    "summit",
    "workshop",
    "seminar",
]

INSIGHT_KEYWORDS = [
    "ai",
    "llm",
    "model",
    "agent",
    "paper",
    "benchmark",
    "open-source",
    "研究",
    "創業",
    "融資",
]

SIGNAL_KEYWORDS = {
    "agent": 1.2,
    "benchmark": 1.2,
    "funding": 1.2,
    "series a": 1.15,
    "series b": 1.2,
    "inference": 1.15,
    "training": 1.1,
    "open-source": 1.1,
    "demo day": 1.2,
    "創投": 1.1,
    "加速器": 1.1,
    "論文": 1.1,
}

TAIWAN_MARKERS = [".tw", "taiwan", "台灣", "台北", "新竹", "台中", "高雄", "台南"]

DEFAULT_WINDOW_BY_KIND = {
    "paper": {"past_days": int(os.getenv("WINDOW_PAPER_PAST_DAYS", "14")), "future_days": 0},
    "post": {"past_days": int(os.getenv("WINDOW_POST_PAST_DAYS", "7")), "future_days": 0},
    "event": {"past_days": 0, "future_days": int(os.getenv("WINDOW_EVENT_FUTURE_DAYS", "60"))},
    "web": {
        "past_days": int(os.getenv("WINDOW_WEB_PAST_DAYS", "7")),
        "future_days": int(os.getenv("WINDOW_WEB_FUTURE_DAYS", "7")),
    },
}

DEFAULT_SOURCES: List[SourceSpec] = [
    SourceSpec("Accupass", "https://www.accupass.com/?area=north&channel=0", "event", "event", 8.5, "taiwan"),
    SourceSpec("Accupass AI 搜尋", "https://www.accupass.com/search?keyword=AI", "event", "event", 8.2, "taiwan"),
    SourceSpec("TechOrange 活動", "https://techorange.com/", "event", "event", 7.0, "taiwan"),
    SourceSpec("TechOrange 智慧製造", "https://2026-smart-manufacturing-taipei.techorange.com/", "event", "event", 7.4, "taiwan"),
    SourceSpec("AIATW", "https://www.aiatw.org/", "event", "event", 7.5, "taiwan"),
    SourceSpec("AIATW Calendar", "https://www.aiatw.org/calendar", "event", "event", 7.8, "taiwan"),
    SourceSpec("Taiwan Accelerator Plus", "https://www.facebook.com/TaiwanAcceleratorPlus/?locale=zh_TW", "event", "event", 7.0, "taiwan"),
    SourceSpec("Garage+", "https://garageplus.asia/", "event", "event", 8.0, "taiwan"),
    SourceSpec("AppWorks", "https://appworks.tw/", "event", "event", 8.2, "taiwan"),
    SourceSpec("AppWorks Events", "https://appworks.tw/events/", "event", "event", 8.1, "taiwan"),
    SourceSpec("Meet 活動", "https://meet.bnext.com.tw/", "event", "event", 8.0, "taiwan"),
    SourceSpec("Meet Startup 活動", "https://meet.bnext.com.tw/events", "event", "event", 8.0, "taiwan"),
    SourceSpec("iThome Seminar", "https://www.ithome.com.tw/seminar", "event", "event", 7.0, "taiwan"),
    SourceSpec("DigiTimes 活動", "https://www.digitimes.com.tw/eventplus/", "event", "event", 7.2, "taiwan"),
    SourceSpec("EventX", "https://www.eventx.io/zh-tw", "event", "event", 6.9, "taiwan"),
    SourceSpec("KKTIX", "https://kktix.com/events", "event", "event", 7.1, "taiwan"),
    SourceSpec("KKTIX AI 搜尋", "https://kktix.com/events?search=ai", "event", "event", 7.1, "taiwan"),
    SourceSpec("InnoVEX", "https://www.innovex.com.tw/", "event", "event", 8.2, "taiwan"),
    SourceSpec("COMPUTEX", "https://www.computextaipei.com.tw/", "event", "event", 8.0, "taiwan"),
    SourceSpec("TTA", "https://www.tta.tw/", "event", "event", 7.6, "taiwan"),
    SourceSpec("TAcc+", "https://www.taccplus.com/", "event", "event", 7.4, "taiwan"),
    SourceSpec("StarFab", "https://starfabx.com/", "event", "event", 7.2, "taiwan"),
    SourceSpec("SparkLabs Taiwan", "https://www.sparklabstaiwan.com/", "event", "event", 7.1, "taiwan"),
    SourceSpec("NTU Startup Garage", "https://startupgarage.ntu.edu.tw/", "event", "event", 7.5, "taiwan"),
    SourceSpec("台大創創中心", "https://www.ntupreneur.ntu.edu.tw/", "event", "event", 7.5, "taiwan"),
    SourceSpec("交大 IAPS", "https://iaps.nycu.edu.tw/", "event", "event", 7.1, "taiwan"),
    SourceSpec("清大育成中心", "https://cii.nthu.edu.tw/", "event", "event", 6.9, "taiwan"),
    SourceSpec("成大產創總中心", "https://iic.ncku.edu.tw/", "event", "event", 6.8, "taiwan"),
    SourceSpec("台科大育成中心", "https://www.bic.ntust.edu.tw/", "event", "event", 6.7, "taiwan"),
    SourceSpec("中山產學營運中心", "https://oic.nsysu.edu.tw/", "event", "event", 6.6, "taiwan"),
    SourceSpec("PyCon Taiwan", "https://tw.pycon.org/", "event", "event", 7.0, "taiwan"),
    SourceSpec("COSCUP", "https://coscup.org/", "event", "event", 7.0, "taiwan"),
    SourceSpec("SITCON", "https://sitcon.org/", "event", "event", 7.0, "taiwan"),
    SourceSpec("AWS 台灣活動", "https://aws.amazon.com/tw/events/", "event", "event", 7.1, "taiwan"),
    SourceSpec("Google Cloud Events", "https://cloud.google.com/events", "event", "event", 7.4, "global"),
    SourceSpec("NVIDIA Events", "https://www.nvidia.com/en-us/events/", "event", "event", 7.3, "global"),
    SourceSpec("Microsoft Reactor", "https://developer.microsoft.com/en-us/reactor/events", "event", "event", 7.1, "global"),
    SourceSpec("智慧城市展", "https://smartcity.org.tw/", "event", "event", 8.0, "taiwan"),
    SourceSpec("台灣國際智慧能源週", "https://www.energytaiwan.com.tw/", "event", "event", 7.8, "taiwan"),
    SourceSpec("台灣輔具暨長照大展", "https://www.chanchao.com.tw/healthcare/", "event", "event", 7.2, "taiwan"),
    SourceSpec("台北世貿展期", "https://www.twtc.com.tw/zh-tw/exhibitionSchedule", "event", "event", 7.3, "taiwan"),
    SourceSpec("南港展覽館展期", "https://www.tainex.com.tw/service/exhibitionschedule", "event", "event", 7.3, "taiwan"),
    SourceSpec("TechOrange 新知", "https://techorange.com/", "insight", "web", 7.0, "taiwan"),
    SourceSpec("Best Partners", "https://www.youtube.com/@bestpartners", "insight", "post", 6.5, "taiwan"),
    SourceSpec("Garage+ 新知", "https://garageplus.asia/", "insight", "web", 8.0, "taiwan"),
    SourceSpec("AppWorks 新知", "https://appworks.tw/", "insight", "web", 8.2, "taiwan"),
    SourceSpec("Hugging Face Blog", "https://huggingface.co/blog", "insight", "web", 8.7, "global"),
    SourceSpec("OpenAI Blog", "https://openai.com/news/", "insight", "web", 9.0, "global"),
    SourceSpec("Anthropic News", "https://www.anthropic.com/news", "insight", "web", 8.8, "global"),
    SourceSpec("Google DeepMind Blog", "https://deepmind.google/discover/blog/", "insight", "web", 8.9, "global"),
    SourceSpec("ArXiv", "https://arxiv.org/list/cs.AI/recent", "insight", "paper", 9.3, "global"),
    SourceSpec("Myeongha", "https://www.facebook.com/Myeongha0929", "insight", "post", 6.0, "taiwan"),
    SourceSpec("BlockTempo", "https://www.blocktempo.com/", "insight", "web", 6.4, "taiwan"),
    SourceSpec("Meet 新知", "https://meet.bnext.com.tw/", "insight", "web", 8.0, "taiwan"),
    SourceSpec("HuggingFace Papers", "https://huggingface.co/papers", "insight", "paper", 9.0, "global"),
    SourceSpec("TLDR AI", "https://tldr.tech/ai/archives", "insight", "post", 7.5, "global"),
    SourceSpec("AlphaSignal", "https://alphasignal.ai/", "insight", "post", 7.8, "global"),
    SourceSpec("Hacker News", "https://news.ycombinator.com/", "insight", "post", 8.0, "global"),
    SourceSpec("GitHub Trending", "https://github.com/trending", "insight", "post", 8.1, "global"),
    SourceSpec("Reddit ML", "https://www.reddit.com/r/MachineLearning/", "insight", "post", 7.2, "global"),
]


def _load_extra_sources() -> List[SourceSpec]:
    extras: List[SourceSpec] = []
    env_raw = os.getenv("MVP_EXTRA_SITES", "")
    for raw in [x.strip() for x in env_raw.split(",") if x.strip()]:
        extras.append(SourceSpec(raw, raw, "insight", "web", 5.5, "global"))

    try:
        user_urls = [row["url"] for row in list_all_active_user_sources() if row.get("url")]
    except Exception:
        user_urls = []

    for url in user_urls:
        extras.append(SourceSpec("使用者來源", url, "insight", "web", 5.0, "global"))

    return extras


def _selected_sources() -> List[SourceSpec]:
    base = list(DEFAULT_SOURCES)
    extras = _load_extra_sources()
    if not extras:
        return base
    # 80% 內建、20% 自訂
    max_extra = max(1, int(len(base) * 0.25))
    return base + extras[:max_extra]


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _to_timestamptz(d: Optional[date]) -> Optional[str]:
    if d is None:
        return None
    dt = datetime.combine(d, time(hour=9, minute=0), tzinfo=TZ_TAIPEI)
    return dt.isoformat()


def _content_hash(title: str, content: str) -> str:
    h = hashlib.sha256()
    h.update((title or "").encode("utf-8"))
    h.update((content or "").encode("utf-8"))
    return h.hexdigest()


def _guess_region(item: ScrapedItem, source: SourceSpec) -> str:
    if source.region_hint == "taiwan":
        return "taiwan"
    text = f"{item.title} {item.url}".lower()
    for marker in TAIWAN_MARKERS:
        if marker in text:
            return "taiwan"
    return "global"


def _is_event(item: ScrapedItem, source: SourceSpec) -> bool:
    if source.bucket == "event" or source.item_kind == "event":
        return True
    return match_keywords(item.title, EVENT_KEYWORDS)


def _signal_score(title: str, snippet: str, event: bool) -> float:
    base = 4.0 if event else 3.5
    text = f"{title} {snippet}".lower()
    bonus = 0.0
    for kw, weight in SIGNAL_KEYWORDS.items():
        if kw in text:
            bonus += (weight - 1.0) * 10
    if event and match_keywords(text, EVENT_KEYWORDS):
        bonus += 1.5
    if (not event) and match_keywords(text, INSIGHT_KEYWORDS):
        bonus += 1.0
    return min(10.0, max(0.0, base + bonus))


def _is_mostly_english(text: str) -> bool:
    sample = (text or "")[:400]
    alpha = len(re.findall(r"[A-Za-z]", sample))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", sample))
    return alpha >= 24 and alpha > cjk * 1.5


def _to_zh_tw(llm: Optional[LLMClient], text: str) -> str:
    if not text:
        return text
    if not _is_mostly_english(text):
        return text
    if llm:
        try:
            translated = llm.translate_to_zh_tw(text)
            if translated:
                return translated
        except Exception:
            pass
    return f"（原文摘要）{text[:180]}"


def _resolve_windows(overrides: Optional[Dict[str, int]] = None) -> Dict[str, Dict[str, int]]:
    windows = {
        "paper": dict(DEFAULT_WINDOW_BY_KIND["paper"]),
        "post": dict(DEFAULT_WINDOW_BY_KIND["post"]),
        "event": dict(DEFAULT_WINDOW_BY_KIND["event"]),
        "web": dict(DEFAULT_WINDOW_BY_KIND["web"]),
    }
    if not overrides:
        return windows
    if "paper_days" in overrides:
        windows["paper"]["past_days"] = max(1, int(overrides["paper_days"]))
    if "post_days" in overrides:
        windows["post"]["past_days"] = max(1, int(overrides["post_days"]))
    if "event_days" in overrides:
        windows["event"]["future_days"] = max(1, int(overrides["event_days"]))
    if "web_past_days" in overrides:
        windows["web"]["past_days"] = max(1, int(overrides["web_past_days"]))
    if "web_future_days" in overrides:
        windows["web"]["future_days"] = max(1, int(overrides["web_future_days"]))
    return windows


def _freshness_score(kind: str, published_at: Optional[date], windows: Dict[str, Dict[str, int]]) -> float:
    if published_at is None:
        return 5.0
    now = datetime.now(TZ_TAIPEI).date()
    delta_days = abs((now - published_at).days)
    window = windows.get(kind, {"past_days": 7, "future_days": 7})
    max_span = max(window["past_days"], window["future_days"], 1)
    score = 10.0 * (1.0 - (delta_days / max_span))
    return round(max(0.0, min(10.0, score)), 2)


def _authority_score(source: SourceSpec) -> float:
    return round(max(0.0, min(10.0, source.authority)), 2)


def _diversity_penalty(source_domain: str, picked_count_by_domain: Dict[str, int]) -> float:
    current = picked_count_by_domain.get(source_domain, 0)
    if current <= 1:
        return 0.0
    return min(3.0, (current - 1) * 1.0)


def _final_score(freshness: float, authority: float, signal: float, penalty: float) -> float:
    score = freshness * 0.35 + authority * 0.25 + signal * 0.40 - penalty
    return round(max(0.0, min(10.0, score)), 2)


def _dedupe(items: List[Tuple[SourceSpec, ScrapedItem]]) -> List[Tuple[SourceSpec, ScrapedItem]]:
    seen = set()
    output: List[Tuple[SourceSpec, ScrapedItem]] = []
    for source, item in items:
        key = (normalize_url(item.url).lower(), item.title.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        output.append((source, item))
    return output


def _raw_to_scraped(raw: RawItem, fallback_source: str) -> ScrapedItem:
    published: Optional[date] = None
    if raw.published_at:
        try:
            published = datetime.fromisoformat(str(raw.published_at).replace("Z", "+00:00")).date()
        except Exception:
            published = None
    return ScrapedItem(
        title=raw.title or raw.url,
        url=raw.url,
        source=fallback_source,
        published_at=published,
        snippet=(raw.content or raw.title or "")[:220],
    )


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _looks_mojibake(text: str) -> bool:
    t = (text or "")
    if not t:
        return False
    return ("�" in t) or ("Ã" in t) or ("â" in t and "—" not in t)


def _clean_text_field(text: Optional[str], max_len: int) -> str:
    value = re.sub(r"\s+", " ", (text or "")).strip()
    if not value:
        return ""
    # 去掉明顯 code block / 回覆型長文污染
    value = value.replace("```", " ").replace("\u0000", " ")
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_len:
        value = value[:max_len].rstrip(" ,.;:：，。")
    return value


def _sanitize_title_and_summary(title: str, summary: str) -> Tuple[str, str]:
    t = _clean_text_field(title, 180)
    s = _clean_text_field(summary, 600)
    # 若 title 異常過長/像段落，拆分回 summary
    if len(t) > 120 and ("。 " in t or "###" in t or "```" in title or "std::" in t or "\n" in (title or "")):
        if not s:
            s = t
        else:
            s = f"{t} {s}"[:600]
        t = _clean_text_field(t.split("。", 1)[0], 90) or "未命名條目"
    if _looks_mojibake(t):
        t = "（標題編碼異常，已待清理）"
    if _looks_mojibake(s):
        s = _clean_text_field(s.replace("�", " "), 600)
    return t or "未命名條目", s or "暫無摘要"


def _summarize_zh(
    llm: Optional[LLMClient], title: str, content: str
) -> Tuple[str, str, str, List[str], str]:
    fallback_summary = _to_zh_tw(llm, (content or title or "").strip()[:180])
    fallback_why = "此資訊與 AI 策略、技術或商業決策相關，建議追蹤。"
    fallback_category = "ai_tech"
    fallback_tags = ["AI"]

    if not llm:
        return fallback_summary, fallback_why, fallback_category, fallback_tags, _clean_text_field(title, 180)

    try:
        result = llm.summarize_and_classify(title, content)
        summary = _to_zh_tw(llm, result.get("summary", "").strip()) or fallback_summary
        why = _to_zh_tw(llm, result.get("why_it_matters", "").strip()) or fallback_why
        title_zh = _to_zh_tw(llm, title)
        category = result.get("category", fallback_category)
        tags = result.get("tags", fallback_tags)
        if not isinstance(tags, list):
            tags = fallback_tags
        return summary, why, category, [str(x) for x in tags][:8], title_zh
    except Exception:
        return fallback_summary, fallback_why, fallback_category, fallback_tags, _to_zh_tw(llm, title)


def run_mvp_pipeline(overrides: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    windows = _resolve_windows(overrides)
    verbose = os.getenv("MVP_VERBOSE", "1") == "1"
    source_cap_events = int(os.getenv("MVP_SOURCE_CAP_EVENTS", "12"))
    source_cap_insights = int(os.getenv("MVP_SOURCE_CAP_INSIGHTS", "5"))
    prune_stats = prune_stale_data(
        paper_days=windows["paper"]["past_days"],
        post_days=windows["post"]["past_days"],
        web_past_days=windows["web"]["past_days"],
        web_future_days=windows["web"]["future_days"],
        event_future_days=windows["event"]["future_days"],
    )
    listing_purged = purge_listing_events()
    pre_cleanup_stats = cleanup_low_quality_content(
        min_event_score=float(os.getenv("CLEANUP_MIN_EVENT_SCORE", "4.5")),
        min_insight_score=float(os.getenv("CLEANUP_MIN_INSIGHT_SCORE", "4.0")),
        max_title_len=int(os.getenv("CLEANUP_MAX_TITLE_LEN", "220")),
    )

    llm = LLMClient() if os.getenv("DEEPSEEK_API_KEY") else None
    candidates: List[Tuple[SourceSpec, ScrapedItem]] = []
    unhealthy_threshold = int(os.getenv("SOURCE_UNHEALTHY_CONSECUTIVE_FAILURES", "6"))
    unhealthy_cooloff_minutes = int(os.getenv("SOURCE_UNHEALTHY_COOLOFF_MINUTES", "120"))

    for source in _selected_sources():
        health = get_source_health(source.url)
        if health and int(health.get("consecutive_failures") or 0) >= unhealthy_threshold:
            last_failure = health.get("last_failure_at")
            if last_failure is not None:
                try:
                    mins_since_fail = (datetime.now(TZ_TAIPEI) - last_failure).total_seconds() / 60.0
                except Exception:
                    mins_since_fail = unhealthy_cooloff_minutes + 1
                if mins_since_fail < unhealthy_cooloff_minutes:
                    if verbose:
                        print(f"[MVP] skip unhealthy source: {source.name}")
                    continue
        window = windows[source.item_kind]
        keywords = [] if source.bucket == "event" else INSIGHT_KEYWORDS
        if verbose:
            print(f"[MVP] crawling {source.name} ({source.url})")
        try:
            crawled = scrape_site(
                source.url,
                keywords=keywords,
                max_age_days=window["past_days"],
                past_days=window["past_days"],
                future_days=window["future_days"],
                strict_future=(source.item_kind == "event"),
                fetch_detail=(source.item_kind in {"event", "paper"}),
            )
            for item in crawled:
                candidates.append((source, item))
            record_source_health(source.url, success=True)
            if verbose:
                print(f"[MVP] -> {len(crawled)} items")
        except Exception:
            record_source_health(source.url, success=False)
            if verbose:
                print(f"[MVP] -> failed")
            continue

    # Structured sources
    try:
        hn_source = SourceSpec("Hacker News", "https://news.ycombinator.com/", "insight", "post", 8.0, "global")
        hn_limit = int(os.getenv("HN_LIMIT", "40"))
        if verbose:
            print(f"[MVP] crawling structured source: HN ({hn_limit})")
        for raw in HackerNewsCrawler(limit=hn_limit).fetch():
            candidates.append((hn_source, _raw_to_scraped(raw, hn_source.url)))
        if verbose:
            print("[MVP] -> HN done")
    except Exception:
        pass

    try:
        gh_source = SourceSpec("GitHub Trending", "https://github.com/trending", "insight", "post", 8.1, "global")
        gh_since = os.getenv("GITHUB_TRENDING_SINCE", "daily")
        if verbose:
            print(f"[MVP] crawling structured source: GitHub Trending ({gh_since})")
        for raw in GitHubTrendingCrawler(since=gh_since).fetch():
            candidates.append((gh_source, _raw_to_scraped(raw, gh_source.url)))
        if verbose:
            print("[MVP] -> GitHub done")
    except Exception:
        pass

    try:
        reddit_source = SourceSpec("Reddit ML", "https://www.reddit.com/r/MachineLearning/", "insight", "post", 7.2, "global")
        subs = [x.strip() for x in os.getenv("REDDIT_SUBREDDITS", "MachineLearning,artificial,LocalLLaMA").split(",") if x.strip()]
        if verbose:
            print(f"[MVP] crawling structured source: Reddit ({','.join(subs)})")
        for raw in RedditCrawler(subreddits=subs).fetch():
            candidates.append((reddit_source, _raw_to_scraped(raw, reddit_source.url)))
        if verbose:
            print("[MVP] -> Reddit done")
    except Exception:
        pass

    deduped = _dedupe(candidates)
    if verbose:
        print(f"[MVP] candidates={len(candidates)}, deduped={len(deduped)}")

    scored_events: List[Dict] = []
    scored_insights: List[Dict] = []

    for source, item in deduped:
        is_event_item = _is_event(item, source)
        domain = _domain(item.url)
        freshness = _freshness_score(source.item_kind, item.published_at, windows)
        authority = _authority_score(source)
        signal = _signal_score(item.title, item.snippet, is_event_item)

        if is_event_item:
            # 活動只保留未來指定天數
            if not item.published_at:
                continue
            now_d = datetime.now(TZ_TAIPEI).date()
            event_future_days = windows["event"]["future_days"]
            if item.published_at < now_d or item.published_at > now_d + timedelta(days=event_future_days):
                continue
            title_clean, summary_clean = _sanitize_title_and_summary(
                _to_zh_tw(llm, item.title),
                _to_zh_tw(llm, item.snippet),
            )
            record = {
                "title": title_clean,
                "summary": summary_clean,
                "why_it_matters": "符合 VC、CEO 與技術決策者關注的活動訊號。",
                "url": item.url,
                "source": source.name,
                "source_domain": domain,
                "region": _guess_region(item, source),
                "date": item.published_at.isoformat() if item.published_at else None,
                "event_type": item.event_type or "活動",
                "freshness_score": freshness,
                "authority_score": authority,
                "signal_score": signal,
            }
            scored_events.append(record)
            continue

        summary, why, category, tags, title_zh = _summarize_zh(llm, item.title, item.snippet)
        title_clean, summary_clean = _sanitize_title_and_summary(title_zh, summary)
        why_clean = _clean_text_field(_to_zh_tw(llm, why), 500)
        if not why_clean:
            why_clean = "此資訊與 AI 策略、技術或商業決策相關，建議追蹤。"
        scored_insights.append(
            {
                "title": title_clean,
                "summary": summary_clean,
                "why_it_matters": why_clean,
                "category": category if category in {"ai_tech", "product_biz"} else "ai_tech",
                "url": item.url,
                "source": source.name,
                "source_domain": domain,
                "published_at": item.published_at,
                "item_kind": source.item_kind,
                "tags": tags,
                "freshness_score": freshness,
                "authority_score": authority,
                "signal_score": signal,
            }
        )

    # 來源平衡
    scored_events.sort(key=lambda x: (x["signal_score"], x["authority_score"], x["freshness_score"]), reverse=True)
    scored_insights.sort(key=lambda x: (x["signal_score"], x["authority_score"], x["freshness_score"]), reverse=True)

    events_balanced: List[Dict] = []
    insights_balanced: List[Dict] = []
    event_count_by_domain: Dict[str, int] = defaultdict(int)
    insight_count_by_domain: Dict[str, int] = defaultdict(int)

    for item in scored_events:
        domain = item.get("source_domain") or ""
        if event_count_by_domain[domain] >= source_cap_events:
            continue
        penalty = _diversity_penalty(domain, event_count_by_domain)
        final = _final_score(item["freshness_score"], item["authority_score"], item["signal_score"], penalty)
        item["diversity_penalty"] = penalty
        item["final_score"] = final
        item["scoring_reason"] = (
            f"新鮮度{item['freshness_score']}/10 + 權威度{item['authority_score']}/10 + 訊號{item['signal_score']}/10"
            f" - 多樣性懲罰{penalty}"
        )
        events_balanced.append(item)
        event_count_by_domain[domain] += 1

    for item in scored_insights:
        domain = item.get("source_domain") or ""
        if insight_count_by_domain[domain] >= source_cap_insights:
            continue
        penalty = _diversity_penalty(domain, insight_count_by_domain)
        final = _final_score(item["freshness_score"], item["authority_score"], item["signal_score"], penalty)
        item["diversity_penalty"] = penalty
        item["final_score"] = final
        item["scoring_reason"] = (
            f"新鮮度{item['freshness_score']}/10 + 權威度{item['authority_score']}/10 + 訊號{item['signal_score']}/10"
            f" - 多樣性懲罰{penalty}"
        )
        insights_balanced.append(item)
        insight_count_by_domain[domain] += 1

    events_balanced.sort(key=lambda x: x["final_score"], reverse=True)
    insights_balanced.sort(key=lambda x: x["final_score"], reverse=True)

    # 入庫
    event_inserted = 0
    insight_inserted = 0

    for ev in events_balanced[:150]:
        title_clean, desc_summary = _sanitize_title_and_summary(ev["title"], ev["summary"])
        upsert_event(
            {
                "title": title_clean,
                "description": _clean_text_field(
                    f"{ev.get('event_type','活動')}｜{ev.get('date','日期待確認')}｜{desc_summary}",
                    1200,
                ),
                "location": None,
                "start_at": _to_timestamptz(date.fromisoformat(ev["date"])) if ev.get("date") else None,
                "end_at": None,
                "url": ev["url"],
                "organizer": ev.get("source"),
                "source_type": "mvp_event",
                "source_domain": ev.get("source_domain"),
                "region": ev.get("region", "global"),
                "tags": ["AI", "活動", ev.get("event_type", "活動")],
                "score": ev["final_score"],
            }
        )
        event_inserted += 1

    for item in insights_balanced[:60]:
        title_clean, summary_clean = _sanitize_title_and_summary(item["title"], item["summary"])
        raw_id = upsert_raw_item(
            {
                "source_id": None,
                "source_type": item.get("source_domain") or "mvp",
                "item_kind": item.get("item_kind", "web"),
                "external_id": None,
                "url": item["url"],
                "title": title_clean,
                "content": summary_clean,
                "author": None,
                "published_at": _to_timestamptz(item.get("published_at")),
                "content_hash": _content_hash(title_clean, summary_clean),
                "raw_meta": {
                    "source": item.get("source"),
                    "kind": item.get("item_kind"),
                    "pipeline": "mvp_v2",
                },
            }
        )
        norm_id = upsert_normalized_item(
            {
                "raw_id": raw_id,
                "title": title_clean,
                "summary": summary_clean,
                "why_it_matters": _clean_text_field(item["why_it_matters"], 500),
                "category": item.get("category", "ai_tech"),
                "content_type": item.get("item_kind", "web") if item.get("item_kind") in {"paper", "post", "web"} else "web",
                "tags": item.get("tags", ["AI"]),
                "language": "zh-TW",
                "entities": {},
            }
        )
        upsert_score(
            {
                "item_id": norm_id,
                "freshness_score": item["freshness_score"],
                "authority_score": item["authority_score"],
                "signal_score": item["signal_score"],
                "diversity_penalty": item["diversity_penalty"],
                "final_score": item["final_score"],
                "scoring_reason": item["scoring_reason"],
            }
        )
        insight_inserted += 1

    taiwan_events = [x for x in events_balanced if x.get("region") == "taiwan"][:10]
    global_events = [x for x in events_balanced if x.get("region") == "global"][:10]
    top_insights = insights_balanced[:10]

    output_payload = {
        "generated_at": datetime.now(TZ_TAIPEI).isoformat(),
        "windows": windows,
        "maintenance": {
            "pruned": prune_stats,
            "listing_purged": listing_purged,
            "pre_cleanup": pre_cleanup_stats,
        },
        "events": {
            "taiwan": taiwan_events,
            "global": global_events,
        },
        "insights": top_insights,
    }

    output_dir = Path(__file__).resolve().parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "mvp_results.json").write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    if verbose:
        print(f"[MVP] done. events={event_inserted}, insights={insight_inserted}")
    listing_purged_post = purge_listing_events()
    post_cleanup_stats = cleanup_low_quality_content(
        min_event_score=float(os.getenv("CLEANUP_MIN_EVENT_SCORE", "4.5")),
        min_insight_score=float(os.getenv("CLEANUP_MIN_INSIGHT_SCORE", "4.0")),
        max_title_len=int(os.getenv("CLEANUP_MAX_TITLE_LEN", "220")),
    )
    audit = content_quality_audit(limit=5, max_title_len=int(os.getenv("CLEANUP_MAX_TITLE_LEN", "220")))
    if verbose:
        audit_brief = {
            "event_title_issues": audit.get("event_title_issues", 0),
            "insight_title_issues": audit.get("insight_title_issues", 0),
        }
        print(f"[MVP] cleanup pre={pre_cleanup_stats}, listing_post={listing_purged_post}, post={post_cleanup_stats}, audit={audit_brief}")

    return {
        "events": event_inserted,
        "insights": insight_inserted,
        "listing_purged": listing_purged,
        "pruned_raw_items": int(prune_stats.get("raw_items", 0)),
        "pruned_events": int(prune_stats.get("events", 0)),
        "cleanup_events": int(post_cleanup_stats.get("events_deleted_low_quality", 0)),
        "cleanup_insights": int(post_cleanup_stats.get("insights_deleted_low_quality", 0)),
        "listing_purged_post": int(listing_purged_post),
    }


if __name__ == "__main__":
    print(run_mvp_pipeline())
