"""Tests for the caching layer."""

from __future__ import annotations

from kicad_mcp.cache import CachedEntry, LRUCache


class TestCachedEntry:
    def test_not_expired_initially(self) -> None:
        entry = CachedEntry(value="test", ttl_seconds=60.0)
        assert not entry.is_expired()

    def test_expired_after_ttl(self) -> None:
        entry = CachedEntry(value="test", ttl_seconds=0.001)
        import time

        time.sleep(0.01)
        assert entry.is_expired()


class TestLRUCache:
    def test_basic_set_get(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_get_nonexistent(self) -> None:
        cache = LRUCache(max_size=10)
        assert cache.get("nonexistent") is None

    def test_lru_eviction(self) -> None:
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Now "a" should be evicted
        cache.get("b")  # Access b to make it most recently used
        cache.set("d", 4)
        assert cache.get("a") is None  # Evicted
        assert cache.get("b") == 2  # Still there
        assert cache.get("c") == 3  # Still there
        assert cache.get("d") == 4  # Just added

    def test_update_existing(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("key", "value1")
        cache.set("key", "value2")
        assert cache.get("key") == "value2"

    def test_delete(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("key", "value")
        assert cache.delete("key") is True
        assert cache.get("key") is None
        assert cache.delete("key") is False  # Already deleted

    def test_clear(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.clear()
        assert len(cache) == 0
        assert cache._hits == 0
        assert cache._misses == 0

    def test_expired_cleanup(self) -> None:
        cache = LRUCache(max_size=10, default_ttl=0.001)
        cache.set("a", 1)
        cache.set("b", 2)
        import time

        time.sleep(0.01)
        removed = cache.cleanup_expired()
        assert removed == 2
        assert len(cache) == 0

    def test_stats(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("key", "value")
        cache.get("key")
        cache.get("miss")

        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["max_size"] == 10

    def test_custom_ttl(self) -> None:
        cache = LRUCache(max_size=10, default_ttl=60.0)
        cache.set("key", "value", ttl=0.001)  # Short TTL override
        import time

        time.sleep(0.01)
        assert cache.get("key") is None  # Should be expired due to custom TTL
