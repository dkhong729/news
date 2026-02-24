from dataclasses import dataclass
from typing import Dict, List, Optional
import hashlib

@dataclass
class RawItem:
    source_type: str
    url: str
    title: str
    content: str
    author: Optional[str]
    published_at: Optional[str]
    external_id: Optional[str] = None
    raw_meta: Optional[Dict] = None

    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update((self.title or "").encode("utf-8"))
        h.update((self.content or "").encode("utf-8"))
        return h.hexdigest()

class Crawler:
    source_type: str

    def fetch(self) -> List[RawItem]:
        raise NotImplementedError
