"""Pluggable sliding-window rate limiting for single- and multi-instance runs."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Protocol


class RateLimiter(Protocol):
    async def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool: ...

    async def close(self) -> None: ...

    @property
    def backend(self) -> str: ...


class MemoryRateLimiter:
    """Process-local fallback used by offline demos and single instances."""

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    async def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        window = self._windows[key]
        cutoff = now - window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    async def close(self) -> None:
        self._windows.clear()

    @property
    def backend(self) -> str:
        return "memory"


class RedisRateLimiter:
    """Atomic Redis ZSET limiter safe to share across API replicas."""

    _SCRIPT = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local cutoff = now - tonumber(ARGV[2])
    local limit = tonumber(ARGV[3])
    redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
    local count = redis.call('ZCARD', key)
    if count >= limit then return 0 end
    redis.call('ZADD', key, now, ARGV[4])
    redis.call('EXPIRE', key, tonumber(ARGV[2]) + 5)
    return 1
    """

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self.client = redis.from_url(url, decode_responses=True)
        self._script = self.client.register_script(self._SCRIPT)

    async def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.time()
        result = await self._script(
            keys=[f"campusguide:ratelimit:{key}"],
            args=[now, window_seconds, limit, f"{now}:{id(self)}"],
        )
        return bool(result)

    async def close(self) -> None:
        await self.client.aclose()

    @property
    def backend(self) -> str:
        return "redis"


def create_rate_limiter(settings) -> RateLimiter:
    """Use Redis when explicitly configured; otherwise remain dependency-free."""

    if settings.rate_limit_backend == "redis" or (
        settings.rate_limit_backend == "auto" and settings.redis_url
    ):
        try:
            return RedisRateLimiter(settings.redis_url)
        except ImportError as error:
            if settings.rate_limit_backend == "redis":
                raise RuntimeError(
                    "install the 'redis' extra to use Redis rate limiting"
                ) from error
    return MemoryRateLimiter()
