import os
import requests
from typing import Dict
from .config import get_settings

settings = get_settings()

class LLMClient:
    def __init__(self):
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.api_key = settings.deepseek_api_key
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def _post(self, payload: Dict) -> Dict:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/v1/chat/completions"
        resp = requests.post(url, json=payload, headers=headers, timeout=40)
        resp.raise_for_status()
        return resp.json()

    def summarize_and_classify(self, title: str, content: str) -> Dict:
        system = (
            "你是提供給技術主管、VC 與商業決策者的分析助手。"
            "請使用繁體中文回覆 JSON，欄位必須包含：summary, why_it_matters, category, tags。"
            "category 只能是 ai_tech 或 product_biz。tags 需為簡短陣列。"
        )
        user = f"Title: {title}\nContent: {content}\n請只回傳 JSON。"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        data = self._post(payload)
        text = data["choices"][0]["message"]["content"]
        return _parse_json(text)

    def translate_to_zh_tw(self, text: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "請將使用者提供的內容翻譯成自然、專業的繁體中文，只輸出翻譯結果。",
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
        }
        data = self._post(payload)
        return data["choices"][0]["message"]["content"].strip()

    def score(self, title: str, summary: str, why: str) -> Dict:
        system = (
            "You are scoring the value of insights for an executive digest. "
            "Return JSON with keys: value_score, novelty_score, relevance_score, influence_score, final_score, scoring_reason. "
            "Scores are 0-10, final_score is weighted average."
        )
        user = f"Title: {title}\nSummary: {summary}\nWhy: {why}\nReturn JSON only."
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        data = self._post(payload)
        text = data["choices"][0]["message"]["content"]
        return _parse_json(text)


def _parse_json(text: str) -> Dict:
    import json

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM returned non-JSON")
    return json.loads(text[start : end + 1])
