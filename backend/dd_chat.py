from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .db import get_latest_grad_dd_report, get_latest_vc_dd_report, get_vc_profile
from .llm_client import LLMClient



def _tokenize(text: str) -> List[str]:
    return [x.lower() for x in re.findall(r"[\w\u4e00-\u9fff]{2,}", text or "")][:50]



def _retrieve_chunks(context: str, query: str, chunk_size: int = 500, top_k: int = 4) -> List[str]:
    text = context or ""
    if not text:
        return []
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    q_tokens = set(_tokenize(query))
    scored = []
    for chunk in chunks:
        c_tokens = set(_tokenize(chunk))
        score = len(q_tokens & c_tokens)
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for s, c in scored[:top_k] if c.strip()]



def _chat_fallback(answer_context: str, question: str) -> str:
    snippet = answer_context[:450].strip() if answer_context else "目前尚未有足夠資料，請先產生 DD 報告。"
    return f"依目前 DD 資料，先回答你：\n\n問題：{question}\n\n可用資訊摘要：{snippet}"



def dd_chat(mode: str, user_id: int, message: str, candidate_id: Optional[int] = None) -> Dict[str, Any]:
    mode_norm = (mode or "").lower()
    context = ""
    source_title = ""

    if mode_norm == "company":
        profile = get_vc_profile(user_id)
        if not profile:
            raise ValueError("尚未建立 VC profile")
        report = get_latest_vc_dd_report(int(profile["id"]), candidate_id=candidate_id)
        if not report:
            raise ValueError("尚未生成公司 DD 報告")
        context = (report.get("markdown") or "") + "\n" + str(report.get("report_json") or "")
        source_title = str(report.get("title") or "公司 DD 報告")
    elif mode_norm == "academic":
        from .db import get_grad_dd_profile

        profile = get_grad_dd_profile(user_id)
        if not profile:
            raise ValueError("尚未建立學術 DD profile")
        report = get_latest_grad_dd_report(int(profile["id"]))
        if not report:
            raise ValueError("尚未生成學術 DD 報告")
        context = (report.get("markdown") or "") + "\n" + str(report.get("report_json") or "")
        source_title = "學術 DD 報告"
    else:
        raise ValueError("mode 只支援 company 或 academic")

    chunks = _retrieve_chunks(context, message)
    answer_context = "\n\n".join(chunks) if chunks else context[:1200]

    answer = ""
    llm = LLMClient() if __import__("os").getenv("DEEPSEEK_API_KEY") else None
    if llm:
        try:
            data = llm._post(
                {
                    "model": llm.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是 DD 顧問，請基於提供的檢索內容，以繁體中文回答。若資料不足請明確說明。",
                        },
                        {
                            "role": "user",
                            "content": f"問題：{message}\n\n檢索內容：\n{answer_context}",
                        },
                    ],
                    "temperature": 0.2,
                }
            )
            answer = data["choices"][0]["message"]["content"].strip()
        except Exception:
            answer = ""

    if not answer:
        answer = _chat_fallback(answer_context, message)

    return {
        "mode": mode_norm,
        "answer": answer,
        "source_title": source_title,
        "retrieved_chunks": chunks,
    }
