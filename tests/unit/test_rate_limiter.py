"""Tests for the rate limiter."""

from __future__ import annotations

from kicad_mcp.rate_limiter import RateLimitConfig, RateLimiter, TokenBucket


class TestTokenBucket:
    def test_acquire_initial(self) -> None:
        config = RateLimitConfig(max_tokens=10, refill_rate=1.0)
        bucket = TokenBucket(config)
        assert bucket.try_acquire() is True

    def test_exhausted_bucket(self) -> None:
        config = RateLimitConfig(max_tokens=2, refill_rate=0.1)
        bucket = TokenBucket(config)
        assert bucket.try_acquire() is True
        assert bucket.try_acquire() is True
        assert bucket.try_acquire() is False

    def test_refill(self) -> None:
        config = RateLimitConfig(max_tokens=10, refill_rate=100.0)
        bucket = TokenBucket(config)
        bucket.tokens = 0.0
        bucket.last_refill = 0
        import time

        time.sleep(0.01)
        bucket._refill()
        assert bucket.tokens > 0

    def test_retry_after(self) -> None:
        config = RateLimitConfig(max_tokens=1, refill_rate=1.0)
        bucket = TokenBucket(config)
        bucket.try_acquire()
        retry_after = bucket.get_retry_after()
        assert retry_after > 0 and retry_after <= 1.0


class TestRateLimiter:
    def test_default_allowed(self) -> None:
        limiter = RateLimiter()
        allowed, retry_after = limiter.is_allowed("drc")
        assert allowed is True
        assert retry_after == 0.0

    def test_rate_limit_exceeded(self) -> None:
        # Create a custom config with low limit for the test
        config = RateLimitConfig(max_tokens=3, refill_rate=0.01)  # Very slow refill
        limiter = RateLimiter({"test_op": config})
        # Use same user ID to get the same bucket
        assert limiter.is_allowed("test_op", user_id="testuser")[0] is True
        assert limiter.is_allowed("test_op", user_id="testuser")[0] is True
        assert limiter.is_allowed("test_op", user_id="testuser")[0] is True
        # Should now be rate limited
        allowed, retry_after = limiter.is_allowed("test_op", user_id="testuser")
        assert allowed is False
        assert retry_after > 0

    def test_per_user_limits(self) -> None:
        limiter = RateLimiter()
        for _ in range(20):
            limiter.is_allowed("placement_test", user_id="user1")
        allowed, _ = limiter.is_allowed("placement_test", user_id="user2")
        assert allowed is True

    def test_custom_config(self) -> None:
        config = RateLimitConfig(max_tokens=5, refill_rate=5.0)
        limiter = RateLimiter({"custom_op": config})
        for _ in range(5):
            allowed, _ = limiter.is_allowed("custom_op", user_id="test")
            assert allowed is True
        allowed, _ = limiter.is_allowed("custom_op", user_id="test")
        assert allowed is False

    def test_reset(self) -> None:
        limiter = RateLimiter()
        config = RateLimitConfig(max_tokens=2, refill_rate=0.01)
        limiter._operation_configs["test"] = config
        # Exhaust limits for user1
        for _ in range(2):
            limiter.is_allowed("test", user_id="user1")
        limiter.reset(user_id="user1")
        # Should work again after reset
        allowed, _ = limiter.is_allowed("test", user_id="user1")
        assert allowed is True

    def test_reset_all(self) -> None:
        limiter = RateLimiter()
        config = RateLimitConfig(max_tokens=2, refill_rate=0.01)
        limiter._operation_configs["test"] = config
        for user in ["user1", "user2"]:
            for _ in range(2):
                limiter.is_allowed("test", user_id=user)
        limiter.reset()
        # Both should work again
        allowed, _ = limiter.is_allowed("test", user_id="user1")
        assert allowed is True
        allowed, _ = limiter.is_allowed("test", user_id="user2")
        assert allowed is True

    def test_get_retry_after(self) -> None:
        config = RateLimitConfig(max_tokens=1, refill_rate=0.01)
        limiter = RateLimiter({"retry_test": config})
        limiter.is_allowed("retry_test", user_id="test")
        retry_after = limiter.get_retry_after("retry_test", user_id="test")
        assert retry_after > 0

    def test_get_stats(self) -> None:
        limiter = RateLimiter()
        limiter.is_allowed("test_op", user_id="u1")
        limiter.is_allowed("test_op2", user_id="u2")
        stats = limiter.get_stats()
        assert len(stats) >= 2

    def test_set_operation_limit(self) -> None:
        limiter = RateLimiter()
        config = RateLimitConfig(max_tokens=5, refill_rate=1.0)
        limiter.set_operation_limit("new_op", config)
        assert limiter._operation_configs.get("new_op") is not None
