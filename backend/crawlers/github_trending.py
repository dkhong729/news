import os
from typing import List

from bs4 import BeautifulSoup

from .base import Crawler, RawItem
from ..http_client import fetch_url


class GitHubTrendingCrawler(Crawler):
    source_type = "github_trending"

    def __init__(self, since: str = "daily"):
        self.since = since

    def fetch(self) -> List[RawItem]:
        items: List[RawItem] = []
        timeout = float(os.getenv("MVP_HTTP_TIMEOUT", "8"))
        url = f"https://github.com/trending?since={self.since}"
        resp = fetch_url(url, source_key="github:trending", timeout=timeout, cache_ttl_hours=4)
        if not resp.ok:
            return items

        soup = BeautifulSoup(resp.text, "html.parser")
        for row in soup.select("article.Box-row"):
            repo_link = row.select_one("h2 a")
            if not repo_link:
                continue
            repo_path = repo_link.get("href", "").strip()
            if not repo_path:
                continue
            repo_url = f"https://github.com{repo_path}"
            title = repo_path.strip("/")
            desc_el = row.select_one("p")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            items.append(
                RawItem(
                    source_type=self.source_type,
                    url=repo_url,
                    title=title,
                    content=desc,
                    author=None,
                    published_at=None,
                    external_id=repo_path,
                    raw_meta={},
                )
            )

        return items
