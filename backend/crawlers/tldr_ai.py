from typing import List
from .rss import RssCrawler

class TldrAICrawler(RssCrawler):
    def __init__(self, feeds: List[str]):
        super().__init__("tldr_ai", feeds)
