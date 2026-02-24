from dataclasses import dataclass
from typing import Optional

@dataclass
class EventItem:
    title: str
    description: str
    location: Optional[str]
    start_at: Optional[str]
    end_at: Optional[str]
    url: Optional[str]
    organizer: Optional[str]
    source_type: str
