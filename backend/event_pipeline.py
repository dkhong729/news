import os
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from .event_crawlers import AccupassCrawler, FBRssGroupCrawler, EventListingCrawler
from .events import EventItem
from .db import get_conn


def _split_env(key: str) -> List[str]:
    raw = os.getenv(key, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _fetch_text(url: str) -> str:
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        return soup.get_text(" ", strip=True)
    except Exception:
        return ""


def _insert_event(item: EventItem) -> None:
    sql = """
    INSERT INTO events (title, description, location, start_at, end_at, url, organizer, source_type)
    VALUES (%(title)s, %(description)s, %(location)s, %(start_at)s, %(end_at)s, %(url)s, %(organizer)s, %(source_type)s)
    ON CONFLICT DO NOTHING;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                {
                    "title": item.title,
                    "description": item.description,
                    "location": item.location,
                    "start_at": item.start_at,
                    "end_at": item.end_at,
                    "url": item.url,
                    "organizer": item.organizer,
                    "source_type": item.source_type,
                },
            )
        conn.commit()


def run_event_pipeline() -> Dict[str, int]:
    acc_keywords = _split_env("EVENT_ACCUPASS_KEYWORDS")
    fb_rss = _split_env("EVENT_FB_RSS")
    listing_urls = _split_env("EVENT_SOURCE_URLS") + _split_env("EVENT_SOURCE_URLS_EXTRA")
    listing_keywords = _split_env("EVENT_KEYWORDS")

    use_llm = os.getenv("EVENT_USE_LLM", "0") == "1" and os.getenv("DEEPSEEK_API_KEY")
    if use_llm:
        from .event_extractor import extract_event_fields

    crawlers = []
    if acc_keywords:
        crawlers.append(AccupassCrawler(acc_keywords))
    if fb_rss:
        crawlers.append(FBRssGroupCrawler(fb_rss))
    if listing_urls:
        crawlers.append(EventListingCrawler(listing_urls, listing_keywords))

    inserted = 0
    for crawler in crawlers:
        for item in crawler.fetch():
            if use_llm and item.url:
                text = _fetch_text(item.url)
                if text:
                    fields = extract_event_fields(text)
                    item.start_at = fields.get("start_at") or item.start_at
                    item.end_at = fields.get("end_at") or item.end_at
                    item.location = fields.get("location") or item.location
                    item.organizer = fields.get("organizer") or item.organizer
                    if fields.get("title"):
                        item.title = fields.get("title")
            _insert_event(item)
            inserted += 1

    return {"inserted": inserted}


if __name__ == "__main__":
    print(run_event_pipeline())
