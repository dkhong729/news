from typing import List
from .base import Crawler, RawItem

class FacebookCrawler(Crawler):
    source_type = "facebook"

    def __init__(self, page_ids: List[str]):
        self.page_ids = page_ids

    def fetch(self) -> List[RawItem]:
        # TODO: Implement with Graph API and page permissions.
        return []
