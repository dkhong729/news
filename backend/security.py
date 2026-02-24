from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

try:
    import redis  # type: ignore
except Exception:
    redis = None


@dataclass
class LimitResult:
    allowed: bool
    count: int
    limit: int
    window_sec: int


class _MemoryLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, Tuple[int, float]] = {}

    def incr(self, key: str, window_sec: int) -> int:
        now = time.time()
        with self._lock:
            count, expires_at = self._buckets.get(key, (0, now + window_sec))
            if now >= expires_at:
                count = 0
                expires_at = now + window_sec
            count += 1
            self._buckets[key] = (count, expires_at)
            return count

    def set_with_ttl(self, key: str, value: str, ttl_sec: int) -> None:
        now = time.time()
        with self._lock:
            self._buckets[key] = (1, now + ttl_sec)

    def exists(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            data = self._buckets.get(key)
            if not data:
                return False
            _, expires_at = data
            if now >= expires_at:
                self._buckets.pop(key, None)
                return False
            return True


class SecurityEngine:
    def __init__(self) -> None:
        self.redis_url = os.getenv("REDIS_URL", "").strip()
        self._mem = _MemoryLimiter()
        self._redis = None
        if self.redis_url and redis is not None:
            try:
                self._redis = redis.Redis.from_url(self.redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:
                self._redis = None

        self.global_ip_limit = int(os.getenv("RATE_LIMIT_IP_PER_MIN", "120"))
        self.user_limit = int(os.getenv("RATE_LIMIT_USER_PER_MIN", "180"))
        self.waf_window_sec = int(os.getenv("WAF_WINDOW_SEC", "900"))
        self.waf_threshold = int(os.getenv("WAF_BLACKLIST_THRESHOLD", "5"))
        self.blacklist_ttl = int(os.getenv("BLACKLIST_TTL_SEC", "86400"))

        default_patterns = [
            r"(?i)(union\s+select)",
            r"(?i)(drop\s+table)",
            r"(?i)(insert\s+into)",
            r"(?i)(\bor\b\s+1=1)",
            r"(?i)(<script|javascript:)",
            r"(\.\./|%2e%2e%2f)",
        ]
        raw_patterns = os.getenv("WAF_BLOCK_PATTERNS", "")
        if raw_patterns:
            parts = [x.strip() for x in raw_patterns.split("||") if x.strip()]
            self.block_patterns = [re.compile(x) for x in parts]
        else:
            self.block_patterns = [re.compile(x) for x in default_patterns]

    def _incr(self, key: str, window_sec: int) -> int:
        if self._redis is not None:
            with self._redis.pipeline() as pipe:
                pipe.incr(key)
                pipe.expire(key, window_sec)
                values = pipe.execute()
            return int(values[0])
        return self._mem.incr(key, window_sec)

    def _set_with_ttl(self, key: str, value: str, ttl_sec: int) -> None:
        if self._redis is not None:
            self._redis.setex(key, ttl_sec, value)
            return
        self._mem.set_with_ttl(key, value, ttl_sec)

    def _exists(self, key: str) -> bool:
        if self._redis is not None:
            return bool(self._redis.exists(key))
        return self._mem.exists(key)

    def is_blacklisted(self, ip: str) -> bool:
        if not ip:
            return False
        return self._exists(f"sec:blacklist:{ip}")

    def blacklist_ip(self, ip: str, reason: str, ttl_sec: Optional[int] = None) -> None:
        if not ip:
            return
        self._set_with_ttl(f"sec:blacklist:{ip}", reason, ttl_sec or self.blacklist_ttl)

    def check_ip_rate_limit(self, ip: str) -> LimitResult:
        key = f"sec:rl:ip:{ip}:60"
        count = self._incr(key, 60)
        return LimitResult(allowed=count <= self.global_ip_limit, count=count, limit=self.global_ip_limit, window_sec=60)

    def check_user_rate_limit(self, user_id: int) -> LimitResult:
        key = f"sec:rl:user:{user_id}:60"
        count = self._incr(key, 60)
        return LimitResult(allowed=count <= self.user_limit, count=count, limit=self.user_limit, window_sec=60)

    def inspect_payload(self, payload_text: str) -> Optional[str]:
        text = (payload_text or "")[:8000]
        for pattern in self.block_patterns:
            if pattern.search(text):
                return pattern.pattern
        return None

    def register_waf_violation(self, ip: str, reason: str) -> int:
        key = f"sec:waf:viol:{ip}:{self.waf_window_sec}"
        count = self._incr(key, self.waf_window_sec)
        if count >= self.waf_threshold:
            self.blacklist_ip(ip, reason, self.blacklist_ttl)
        return count


engine = SecurityEngine()
