import json
import os
from typing import List

from .base import Crawler, RawItem
from ..http_client import fetch_url


class HackerNewsCrawler(Crawler):
    source_type = "hackernews"

    def __init__(self, limit: int = 30):
        self.limit = limit

    def fetch(self) -> List[RawItem]:
        items: List[RawItem] = []
        timeout = float(os.getenv("MVP_HTTP_TIMEOUT", "8"))

        top_resp = fetch_url(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            source_key="hackernews:topstories",
            timeout=timeout,
            cache_ttl_hours=2,
        )
        if not top_resp.ok:
            return items
        try:
            top_ids = json.loads(top_resp.text)
        except Exception:
            return items

        for story_id in top_ids[: self.limit]:
            story_resp = fetch_url(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                source_key="hackernews:item",
                timeout=timeout,
                cache_ttl_hours=6,
            )
            if not story_resp.ok:
                continue
            try:
                story = json.loads(story_resp.text)
            except Exception:
                continue

            if not story or story.get("type") != "story":
                continue

            items.append(
                RawItem(
                    source_type=self.source_type,
                    url=story.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                    title=story.get("title", ""),
                    content=story.get("text", ""),
                    author=story.get("by"),
                    published_at=None,
                    external_id=str(story_id),
                    raw_meta={"score": story.get("score", 0), "comments": story.get("descendants", 0)},
                )
            )

        return items
