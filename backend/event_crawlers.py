from typing import List
import re
import requests
from bs4 import BeautifulSoup
from .events import EventItem

class EventCrawler:
    source_type: str

    def fetch(self) -> List[EventItem]:
        raise NotImplementedError


class AccupassCrawler(EventCrawler):
    source_type = "accupass"

    def __init__(self, keywords: List[str]):
        self.keywords = keywords

    def fetch(self) -> List[EventItem]:
        items: List[EventItem] = []
        for kw in self.keywords:
            url = f"https://www.accupass.com/search?q={kw}"
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for card in soup.select("a.js-event-card-link"):
                title = card.get_text(strip=True)
                link = card.get("href")
                if link and link.startswith("//"):
                    link = "https:" + link
                if title and link:
                    items.append(
                        EventItem(
                            title=title,
                            description="",
                            location=None,
                            start_at=None,
                            end_at=None,
                            url=link,
                            organizer=None,
                            source_type=self.source_type,
                        )
                    )
        return items


class FBRssGroupCrawler(EventCrawler):
    source_type = "facebook_group"

    def __init__(self, group_rss_urls: List[str]):
        self.group_rss_urls = group_rss_urls

    def fetch(self) -> List[EventItem]:
        items: List[EventItem] = []
        for url in self.group_rss_urls:
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "xml")
            for item in soup.find_all("item"):
                title = item.title.get_text(strip=True) if item.title else ""
                link = item.link.get_text(strip=True) if item.link else ""
                if title and link:
                    items.append(
                        EventItem(
                            title=title,
                            description=item.description.get_text(strip=True) if item.description else "",
                            location=None,
                            start_at=None,
                            end_at=None,
                            url=link,
                            organizer=None,
                            source_type=self.source_type,
                        )
                    )
        return items


class EventListingCrawler(EventCrawler):
    source_type = "event_listing"

    def __init__(self, urls: List[str], keywords: List[str]):
        self.urls = urls
        self.keywords = [k.lower() for k in keywords]

    def fetch(self) -> List[EventItem]:
        items: List[EventItem] = []
        for url in self.urls:
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a"):
                title = a.get_text(strip=True)
                href = a.get("href")
                if not title or not href:
                    continue
                if self.keywords and not _match_keywords(title, self.keywords):
                    continue
                link = _absolute(url, href)
                items.append(
                    EventItem(
                        title=title,
                        description="",
                        location=None,
                        start_at=None,
                        end_at=None,
                        url=link,
                        organizer=None,
                        source_type=self.source_type,
                    )
                )
        return items


def _absolute(base: str, href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return re.sub(r"/+$", "", base) + href
    return base.rstrip("/") + "/" + href


def _match_keywords(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)
