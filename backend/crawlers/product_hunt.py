import os
import requests
from typing import List
from .base import Crawler, RawItem

class ProductHuntCrawler(Crawler):
    source_type = "product_hunt"

    def __init__(self, limit: int = 20):
        self.limit = limit
        self.token = os.getenv("PRODUCT_HUNT_TOKEN", "")

    def fetch(self) -> List[RawItem]:
        if not self.token:
            return []
        url = "https://api.producthunt.com/v2/api/graphql"
        headers = {"Authorization": f"Bearer {self.token}"}
        query = {
            "query": "query { posts(order: NEWEST, first: %d) { edges { node { id name tagline url } } } }" % self.limit
        }
        resp = requests.post(url, json=query, headers=headers, timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json()
        items: List[RawItem] = []
        for edge in data.get("data", {}).get("posts", {}).get("edges", []):
            node = edge.get("node", {})
            items.append(
                RawItem(
                    source_type=self.source_type,
                    url=node.get("url", ""),
                    title=node.get("name", ""),
                    content=node.get("tagline", ""),
                    author=None,
                    published_at=None,
                    external_id=node.get("id"),
                    raw_meta={},
                )
            )
        return items
