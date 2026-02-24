import feedparser
import requests
from typing import List
from .base import Crawler, RawItem

class RssCrawler(Crawler):
    source_type = "rss"

    def __init__(self, source_type: str, feeds: List[str]):
        self.source_type = source_type
        self.feeds = feeds

    def fetch(self) -> List[RawItem]:
        items: List[RawItem] = []
        for url in self.feeds:
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
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
                        raw_meta={},
                    )
                )
        return items
