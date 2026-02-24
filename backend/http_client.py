from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Dict, Optional

import requests

from .db import get_source_cache, record_source_health, upsert_source_cache


@dataclass
class HttpResult:
    ok: bool
    status_code: int
    text: str
    url: str
    from_cache: bool = False
    error: Optional[str] = None


def _timeout() -> float:
    return float(os.getenv("MVP_HTTP_TIMEOUT", "8"))


def _max_retries() -> int:
    return int(os.getenv("HTTP_MAX_RETRIES", "2"))


def _proxy_pool() -> list[str]:
    raw = os.getenv("PROXY_POOL_URLS", "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _cache_ttl_hours() -> int:
    return int(os.getenv("HTTP_CACHE_TTL_HOURS", "24"))


def _trust_env_proxy() -> bool:
    # 預設關閉 requests 的系統代理，避免本機代理設定導致所有抓取失敗
    return os.getenv("HTTP_TRUST_ENV_PROXY", "0") == "1"


def _retryable(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _sleep_backoff(attempt: int) -> None:
    base = min(6.0, 0.5 * (2 ** attempt))
    jitter = random.uniform(0.0, 0.3)
    time.sleep(base + jitter)


def _retryable_exception(exc: Exception) -> bool:
    text = str(exc).lower()
    hard_fail_markers = [
        "winerror 10051",
        "name resolution",
        "no route to host",
        "temporary failure in name resolution",
    ]
    return not any(marker in text for marker in hard_fail_markers)


def fetch_url(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    source_key: Optional[str] = None,
    cache_ttl_hours: Optional[int] = None,
    timeout: Optional[float] = None,
) -> HttpResult:
    headers = headers or {"User-Agent": "ai-insight-pulse/0.1"}
    timeout = timeout if timeout is not None else _timeout()
    retries = max(1, _max_retries())
    proxies = _proxy_pool()
    cache_hours = cache_ttl_hours if cache_ttl_hours is not None else _cache_ttl_hours()
    source = source_key or url

    last_error: Optional[str] = None
    last_status = 0

    session = requests.Session()
    session.trust_env = _trust_env_proxy()

    for attempt in range(retries):
        proxy_dict = None
        if proxies:
            chosen = proxies[attempt % len(proxies)]
            proxy_dict = {"http": chosen, "https": chosen}

        try:
            resp = session.get(url, headers=headers, timeout=timeout, proxies=proxy_dict)
            last_status = int(resp.status_code)
            if resp.status_code == 200:
                try:
                    upsert_source_cache(url, int(resp.status_code), resp.text, source)
                    record_source_health(source, success=True)
                except Exception:
                    pass
                return HttpResult(ok=True, status_code=200, text=resp.text, url=url)

            if _retryable(resp.status_code) and attempt < retries - 1:
                _sleep_backoff(attempt)
                continue

            last_error = f"HTTP {resp.status_code}"
            break
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries - 1 and _retryable_exception(exc):
                _sleep_backoff(attempt)
                continue
            break

    try:
        record_source_health(source, success=False)
    except Exception:
        pass

    try:
        cached = get_source_cache(url, max_age_hours=cache_hours)
    except Exception:
        cached = None

    if cached and cached.get("body"):
        return HttpResult(
            ok=True,
            status_code=int(cached.get("status_code") or 200),
            text=str(cached.get("body") or ""),
            url=url,
            from_cache=True,
            error=last_error,
        )

    return HttpResult(ok=False, status_code=last_status or 0, text="", url=url, from_cache=False, error=last_error)
