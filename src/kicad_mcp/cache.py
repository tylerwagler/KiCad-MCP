"""Caching layer for board parsing and lookups.

Provides in-memory caching with TTL support to avoid redundant
parsing operations and improve performance.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

try:
    from .logging_config import create_logger
except ImportError:
    from kicad_mcp.logging_config import create_logger

logger = create_logger(__name__)


@dataclass
class CachedEntry:
    """Represents a cached entry with TTL."""

    value: Any
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 300.0

    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return time.time() - self.created_at > self.ttl_seconds


class LRUCache:
    """Simple LRU cache with TTL support."""

    def __init__(self, max_size: int = 128, default_ttl: float = 300.0):
        """Initialize the cache.

        Args:
            max_size: Maximum number of entries.
            default_ttl: Default TTL in seconds.
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CachedEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        """Get a value from the cache."""
        if key not in self._cache:
            self._misses += 1
            return None

        entry = self._cache[key]
        if entry.is_expired():
            logger.debug(f"Cache entry expired: {key}")
            self.delete(key)
            self._misses += 1
            return None

        self._cache.move_to_end(key)
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Set a value in the cache."""
        if key in self._cache:
            self._cache.move_to_end(key)

        entry = CachedEntry(
            value=value, created_at=time.time(), ttl_seconds=ttl or self.default_ttl
        )

        while len(self._cache) >= self.max_size:
            oldest_key = next(iter(self._cache))
            self.delete(oldest_key)

        self._cache[key] = entry
        logger.debug(f"Cached value for key: {key}")

    def delete(self, key: str) -> bool:
        """Delete a cache entry."""
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Deleted cache key: {key}")
            return True
        return False

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        logger.info("Cache cleared")

    def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]
        for key in expired_keys:
            self.delete(key)
        logger.debug(f"Cleaned up {len(expired_keys)} expired entries")
        return len(expired_keys)

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
        }

    def __len__(self) -> int:
        """Get current cache size (excluding expired)."""
        return sum(1 for entry in self._cache.values() if not entry.is_expired())


_board_summary_cache = LRUCache(max_size=64, default_ttl=60.0)
_footprints_cache = LRUCache(max_size=64, default_ttl=60.0)
_library_cache = LRUCache(max_size=256, default_ttl=300.0)


def get_board_summary_cache() -> LRUCache:
    """Get the board summary cache instance."""
    return _board_summary_cache


def get_footprints_cache() -> LRUCache:
    """Get the footprints cache instance."""
    return _footprints_cache


def get_library_cache() -> LRUCache:
    """Get the library cache instance."""
    return _library_cache


def clear_all_caches() -> None:
    """Clear all cache instances."""
    _board_summary_cache.clear()
    _footprints_cache.clear()
    _library_cache.clear()
    logger.info("All caches cleared")


def get_cache_stats() -> dict[str, Any]:
    """Get statistics for all caches."""
    return {
        "board_summary": _board_summary_cache.stats,
        "footprints": _footprints_cache.stats,
        "library": _library_cache.stats,
        "total_entries": (len(_board_summary_cache) + len(_footprints_cache) + len(_library_cache)),
    }
