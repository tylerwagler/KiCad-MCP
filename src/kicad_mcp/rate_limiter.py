"""Rate limiting for tool execution.

Provides token bucket rate limiting to prevent abuse and ensure
fair usage across different operations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

try:
    from .logging_config import create_logger
except ImportError:
    from kicad_mcp.logging_config import create_logger

logger = create_logger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""

    max_tokens: int
    refill_rate: float
    burst_size: int | None = None

    def __post_init__(self) -> None:
        if self.burst_size is None:
            self.burst_size = self.max_tokens


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.tokens = float(config.max_tokens)
        self.last_refill = time.time()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.config.refill_rate
        self.tokens = min(self.config.max_tokens, self.tokens + tokens_to_add)
        self.last_refill = now

    def try_acquire(self) -> bool:
        """Try to acquire a token."""
        self._refill()
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def get_retry_after(self) -> float:
        """Get seconds until a token is available."""
        self._refill()
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.config.refill_rate


class RateLimiter:
    """Rate limiter with multiple buckets for different operation types."""

    DEFAULT_LIMITS = {
        "drc": RateLimitConfig(max_tokens=10, refill_rate=10 / 60),
        "export": RateLimitConfig(max_tokens=5, refill_rate=5 / 60),
        "move": RateLimitConfig(max_tokens=30, refill_rate=30 / 60),
        "route": RateLimitConfig(max_tokens=10, refill_rate=10 / 60),
        "placement": RateLimitConfig(max_tokens=20, refill_rate=20 / 60),
        "default": RateLimitConfig(max_tokens=100, refill_rate=100 / 60),
    }

    def __init__(self, configs: dict[str, RateLimitConfig] | None = None) -> None:
        """Initialize the rate limiter."""
        # Store operation-level configs, not per-user buckets
        self._operation_configs: dict[str, RateLimitConfig] = {}
        if configs:
            self._operation_configs = configs.copy()
        self.buckets: dict[str, TokenBucket] = {}

    def _get_config(self, operation: str) -> RateLimitConfig:
        """Get the rate limit config for an operation."""
        return self._operation_configs.get(operation, self.DEFAULT_LIMITS["default"])

    def _get_bucket(self, bucket_key: str, config: RateLimitConfig) -> TokenBucket:
        """Get or create a token bucket."""
        if bucket_key not in self.buckets:
            self.buckets[bucket_key] = TokenBucket(config)
        return self.buckets[bucket_key]

    def is_allowed(self, operation: str, user_id: str = "default") -> tuple[bool, float]:
        """Check if an operation is allowed."""
        bucket_key = f"{user_id}:{operation}"
        config = self._get_config(operation)
        bucket = self._get_bucket(bucket_key, config)

        if bucket.try_acquire():
            logger.debug(f"Rate limit check passed: {operation} (user: {user_id})")
            return True, 0.0
        else:
            retry_after = bucket.get_retry_after()
            logger.warning(
                f"Rate limit exceeded: {operation} (user: {user_id}), "
                f"retry after {retry_after:.1f}s"
            )
            return False, retry_after

    def get_retry_after(self, operation: str, user_id: str = "default") -> float:
        """Get retry-after time for an operation."""
        bucket_key = f"{user_id}:{operation}"
        bucket = self.buckets.get(bucket_key)

        if bucket is None:
            return 0.0
        return bucket.get_retry_after()

    def reset(self, user_id: str | None = None) -> None:
        """Reset rate limits."""
        if user_id:
            keys_to_remove = [key for key in self.buckets if key.startswith(f"{user_id}:")]
            for key in keys_to_remove:
                del self.buckets[key]
        else:
            self.buckets.clear()
        logger.info("Rate limits reset")

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        stats = {}
        for key, bucket in self.buckets.items():
            bucket._refill()
            stats[key] = {
                "tokens": bucket.tokens,
                "max_tokens": bucket.config.max_tokens,
                "refill_rate": bucket.config.refill_rate,
            }
        return stats

    def set_operation_limit(self, operation: str, config: RateLimitConfig) -> None:
        """Set a custom rate limit for an operation."""
        self._operation_configs[operation] = config
