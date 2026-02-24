import re
import os
from typing import Dict
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.output_parsers import JsonOutputParser
from .config import get_settings

class EventExtraction(BaseModel):
    title: str = Field(default="")
    start_at: str = Field(default="")
    end_at: str = Field(default="")
    location: str = Field(default="")
    organizer: str = Field(default="")


def extract_event_fields(text: str) -> Dict:
    settings = get_settings()
    llm = ChatOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        temperature=0,
    )
    parser = JsonOutputParser(pydantic_object=EventExtraction)
    prompt = (
        "Extract event details from the text.\n"
        "Return JSON with: title, start_at, end_at, location, organizer.\n"
        "Use ISO datetime if present; otherwise empty string.\n"
        "Text:\n" + _truncate(text)
    )
    result = llm.invoke(prompt)
    return parser.parse(result.content)


def _truncate(text: str, limit: int = 4000) -> str:
    text = re.sub(r"\s+", " ", text)
    return text[:limit]
