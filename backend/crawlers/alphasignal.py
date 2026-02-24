from typing import List
from .rss import RssCrawler

class AlphaSignalCrawler(RssCrawler):
    def __init__(self, feeds: List[str]):
        super().__init__("alphasignal", feeds)
