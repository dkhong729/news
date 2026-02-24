from typing import Dict
from .llm_client import LLMClient

llm = LLMClient()

# 定義商業大老感興趣的「高信號關鍵字」
HIGH_SIGNAL_KEYWORDS = {
    "infra": 1.2, "architecture": 1.5, "series": 1.3, 
    "funding": 1.3, "benchmark": 1.4, "open-source": 1.2,
    "acquisition": 1.5, "breakthrough": 1.4, "agent": 1.3
}

def score(normalized: Dict) -> Dict:
    text_to_analyze = f"{normalized.get('title', '')} {normalized.get('summary', '')}"
    
    # 1. 基礎啟發式打分 (Heuristic Score) - 快速過濾雜訊
    base_boost = 1.0
    for word, weight in HIGH_SIGNAL_KEYWORDS.items():
        if word.lower() in text_to_analyze.lower():
            base_boost *= weight

    # 2. LLM 深度打分
    # 這裡我們傳入一個特定的 System Prompt 給 LLM，告訴它你是 VC 的情報官
    try:
        result = llm.score(
            normalized.get("title", ""),
            normalized.get("summary", ""),
            normalized.get("why_it_matters", ""),
        )
    except Exception:
        result = {
            "value_score": 0,
            "novelty_score": 0,
            "relevance_score": 0,
            "influence_score": 0,
            "final_score": 0,
            "scoring_reason": "LLM scoring skipped",
        }

    # 3. 權重加總計算
    # 最終得分 = LLM 的綜合得分 * 關鍵字加權
    raw_final_score = result.get("final_score", 0) * base_boost
    
    # 確保分數在 0-100 之間
    final_score = min(round(raw_final_score, 2), 100)

    return {
        "item_id": normalized.get("id"),
        "value_score": result.get("value_score", 0),
        "novelty_score": result.get("novelty_score", 0),
        "relevance_score": result.get("relevance_score", 0),
        "influence_score": result.get("influence_score", 0),
        "final_score": final_score,
        "scoring_reason": f"[Heuristic Boost: {base_boost}x] {result.get('scoring_reason', '')}",
    }
