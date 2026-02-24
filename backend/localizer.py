from __future__ import annotations

from typing import Dict

from .db import list_non_zh_events, list_non_zh_insights, update_event, update_insight
from .llm_client import LLMClient



def _is_english_like(text: str) -> bool:
    alpha = sum(1 for c in (text or "") if "a" <= c.lower() <= "z")
    cjk = sum(1 for c in (text or "") if "\u4e00" <= c <= "\u9fff")
    return alpha >= 10 and alpha > cjk * 1.2


def _looks_mojibake(text: str) -> bool:
    value = text or ""
    return ("�" in value) or ("Ã" in value) or ("â€" in value)


def _clean_text(text: str) -> str:
    return " ".join((text or "").replace("�", " ").split()).strip()



def _to_zh(llm: LLMClient | None, text: str) -> str:
    if not text:
        return text
    if _looks_mojibake(text):
        text = _clean_text(text)
    if not _is_english_like(text):
        return text
    if llm:
        try:
            out = llm.translate_to_zh_tw(text)
            if out:
                return out
        except Exception:
            pass
    return f"（原文）{text[:200]}"



def localize_existing_content(limit_insights: int = 200, limit_events: int = 200) -> Dict[str, int]:
    llm = LLMClient() if __import__("os").getenv("DEEPSEEK_API_KEY") else None

    insights = list_non_zh_insights(limit=limit_insights)
    events = list_non_zh_events(limit=limit_events)

    i_count = 0
    for item in insights:
        fields = {
            "title": _to_zh(llm, item.get("title") or ""),
            "summary": _to_zh(llm, item.get("summary") or ""),
            "why_it_matters": _to_zh(llm, item.get("why_it_matters") or ""),
            "language": "zh-TW",
        }
        update_insight(int(item["id"]), fields)
        i_count += 1

    e_count = 0
    for ev in events:
        fields = {
            "title": _to_zh(llm, ev.get("title") or ""),
            "description": _to_zh(llm, ev.get("description") or ""),
        }
        update_event(int(ev["id"]), fields)
        e_count += 1

    return {"insights_localized": i_count, "events_localized": e_count}
