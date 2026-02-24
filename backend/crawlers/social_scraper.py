import os
import requests
from typing import List
from .base import Crawler, RawItem

class SocialDataCrawler(Crawler):
    source_type = "x_socialdata"

    def __init__(self, handles: List[str]):
        self.handles = handles
        self.api_key = os.getenv("SOCIALDATA_API_KEY", "")
        self.base_url = os.getenv("SOCIALDATA_BASE_URL", "https://api.socialdata.tools").rstrip("/")

    def fetch(self) -> List[RawItem]:
        if not self.api_key or not self.handles:
            return []
        items: List[RawItem] = []
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        for handle in self.handles:
            # SocialData.tools API format may vary by plan.
            # Expected response: [{id,text,created_at,author,link}]
            url = f"{self.base_url}/v1/x/user/{handle}/posts"
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for post in data.get("data", data if isinstance(data, list) else []):
                items.append(
                    RawItem(
                        source_type=self.source_type,
                        url=post.get("link") or post.get("url") or "",
                        title=(post.get("text") or "")[:120],
                        content=post.get("text", ""),
                        author=post.get("author") or handle,
                        published_at=post.get("created_at"),
                        external_id=str(post.get("id", "")),
                        raw_meta={"handle": handle},
                    )
                )
        return items
