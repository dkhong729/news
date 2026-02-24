import os
from typing import List

import feedparser

from .base import Crawler, RawItem
from ..http_client import fetch_url


class RedditCrawler(Crawler):
    source_type = "reddit"

    def __init__(self, subreddits: List[str]):
        self.subreddits = subreddits

    def fetch(self) -> List[RawItem]:
        items: List[RawItem] = []
        timeout = float(os.getenv("MVP_HTTP_TIMEOUT", "8"))
        headers = {"User-Agent": "ai-insight-pulse/0.1"}

        for sub in self.subreddits:
            url = f"https://www.reddit.com/r/{sub}/.rss"
            resp = fetch_url(url, headers=headers, source_key=f"reddit:{sub}", timeout=timeout, cache_ttl_hours=2)
            if not resp.ok:
                continue

            feed = feedparser.parse(resp.text)
            for entry in feed.entries:
                items.append(
                    RawItem(
                        source_type=self.source_type,
                        url=entry.link,
                        title=entry.title,
                        content=getattr(entry, "summary", ""),
                        author=getattr(entry, "author", None),
                        published_at=getattr(entry, "published", None),
                        external_id=getattr(entry, "id", None),
                        raw_meta={"subreddit": sub},
                    )
                )

        return items
