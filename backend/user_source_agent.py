import os
import requests
from bs4 import BeautifulSoup
from typing import Dict, List
from .db import insert_raw_item, list_user_sources
from .crawlers.base import RawItem
from .normalization import normalize
from .scoring import score
from .db import insert_normalized_item, insert_score


def _fetch_text(url: str) -> str:
    resp = requests.get(url, timeout=20)
    if resp.status_code != 200:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    return text[:8000]


def run_user_source_agent(user_id: int) -> Dict[str, int]:
    sources = list_user_sources(user_id)
    inserted = 0
    normalized = 0
    scored = 0

    for src in sources:
        url = src["url"]
        text = _fetch_text(url)
        if not text:
            continue
        raw = RawItem(
            source_type="custom_url",
            url=url,
            title=url,
            content=text,
            author=None,
            published_at=None,
            external_id=None,
            raw_meta={"user_id": user_id},
        )
        raw_id = insert_raw_item(
            {
                "source_id": None,
                "source_type": raw.source_type,
                "external_id": raw.external_id,
                "url": raw.url,
                "title": raw.title,
                "content": raw.content,
                "author": raw.author,
                "published_at": raw.published_at,
                "content_hash": raw.content_hash(),
                "raw_meta": raw.raw_meta,
            }
        )
        if not raw_id:
            continue
        inserted += 1

        if not os.getenv("DEEPSEEK_API_KEY"):
            continue
        normalized_item = normalize({"id": raw_id, "title": raw.title, "content": raw.content})
        norm_id = insert_normalized_item(normalized_item)
        if not norm_id:
            continue
        normalized += 1

        scored_item = score({**normalized_item, "id": norm_id})
        insert_score(scored_item)
        scored += 1

    return {"inserted": inserted, "normalized": normalized, "scored": scored}
