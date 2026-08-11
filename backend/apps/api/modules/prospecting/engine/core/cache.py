"""
core/cache.py - In-memory TTL provider result cache.

Purpose:
  Avoid redundant API calls for the same ICP or company across multiple
  pipeline runs within the same server session. Reduces free-tier quota burn.

Design:
  - Pure in-memory dict keyed by sha256(request_key).
  - TTL defaults to 3600 seconds (1 hour), configurable via engine settings.
  - No external dependencies (no Redis, no SQLite).
  - Cache does NOT survive server restarts (acceptable for quota preservation
    within a single session; persistence can be added later).

Usage:
    cache = ProviderCache()
    key = cache.make_key("apollo", {"icp": "healthcare", "region": "US"})
    result = cache.get(key)
    if result is None:
        result = await provider.search_companies(icp)
        cache.set(key, result)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ProviderCache:
    """
    Simple in-memory TTL cache for provider responses.

    Thread-safety: asyncio is single-threaded per event loop, so dict
    operations are safe without locks in an async context.
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._hits = 0
        self._misses = 0

    def make_key(self, provider_name: str, payload: Any) -> str:
        """
        Create a stable cache key from a provider name and request payload.

        Args:
            provider_name: e.g. "apollo", "tavily"
            payload: Any JSON-serialisable object (dict, list, str, etc.)

        Returns:
            Hex digest of sha256(provider_name + canonical JSON payload).
        """
        try:
            canonical = json.dumps(
                {"provider": provider_name, "payload": payload},
                sort_keys=True,
                default=str,
            )
        except Exception:
            canonical = f"{provider_name}:{str(payload)}"
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        """
        Return the cached value for key, or None if absent or expired.

        Expired entries are evicted on access.
        """
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None

        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            self._misses += 1
            logger.debug("Cache: expired entry evicted (key=%s...)", key[:8])
            return None

        self._hits += 1
        logger.debug("Cache: HIT (key=%s...)", key[:8])
        return value

    def set(self, key: str, value: Any) -> None:
        """Store value in cache with TTL starting now."""
        expires_at = time.monotonic() + self._ttl
        self._store[key] = (value, expires_at)
        logger.debug("Cache: SET (key=%s... ttl=%ds)", key[:8], self._ttl)

    def invalidate(self, key: str) -> None:
        """Remove a specific entry from cache."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._store.clear()
        logger.debug("Cache: cleared all entries")

    def evict_expired(self) -> int:
        """
        Remove all expired entries. Returns the count of evicted entries.
        Call periodically to prevent unbounded memory growth.
        """
        now = time.monotonic()
        expired_keys = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired_keys:
            del self._store[k]
        if expired_keys:
            logger.debug("Cache: evicted %d expired entries", len(expired_keys))
        return len(expired_keys)

    @property
    def stats(self) -> dict[str, int]:
        """Return cache hit/miss counters and current size."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._store),
        }


# Module-level singleton — shared across the engine within a single server session.
_cache: ProviderCache | None = None


def get_cache() -> ProviderCache:
    """Return the module-level cache singleton, initialising on first call."""
    global _cache  # noqa: PLW0603
    if _cache is None:
        from apps.api.modules.prospecting.engine.config import get_settings  # noqa: PLC0415
        _cache = ProviderCache(ttl_seconds=get_settings().cache_ttl_seconds)
    return _cache
