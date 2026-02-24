from typing import Dict
from .llm_client import LLMClient

llm = LLMClient()


def normalize(raw: Dict) -> Dict:
    result = llm.summarize_and_classify(raw.get("title", ""), raw.get("content", ""))
    return {
        "raw_id": raw["id"],
        "title": raw.get("title", ""),
        "summary": result.get("summary", ""),
        "why_it_matters": result.get("why_it_matters", ""),
        "category": result.get("category", "product_biz"),
        "tags": result.get("tags", []),
        "language": "en",
        "entities": {},
    }
