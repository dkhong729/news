from typing import List
from .rss import RssCrawler

class ResearchBlogsCrawler(RssCrawler):
    def __init__(self, feeds: List[str]):
        super().__init__("research_blogs", feeds)
