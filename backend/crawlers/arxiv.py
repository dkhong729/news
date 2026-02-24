import feedparser
import requests
from typing import List
from .base import Crawler, RawItem

class ArxivCrawler(Crawler):
    source_type = "arxiv"

    def __init__(self, feeds: List[str]):
        self.feeds = feeds

    def fetch(self) -> List[RawItem]:
        items: List[RawItem] = []
        for url in self.feeds:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
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
                        raw_meta={"tags": [t.term for t in getattr(entry, "tags", [])]},
                    )
                )
        return items
