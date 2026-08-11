import time
from typing import Any, Dict, Tuple

class SimpleTTLCache:
    """
    A naive thread-safe in-memory cache for API responses.
    Prevents redundant calls to external providers (Tavily, Hunter, PDL)
    during the same runtime session, saving API credits.
    """
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl = ttl_seconds
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        if key in self._cache:
            timestamp, value = self._cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)

# Global instance for providers to share
api_response_cache = SimpleTTLCache(ttl_seconds=3600 * 24)  # 24 hour TTL
