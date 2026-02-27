"""Logging infrastructure for the KiCad MCP server.

Provides structured logging with configurable levels, request tracking,
and error formatting across all modules.
"""

from __future__ import annotations

import logging
import os
import sys
from contextvars import ContextVar
from typing import Any

# Request ID tracking for request-level correlation
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Get the current request ID if available."""
    return request_id_ctx.get()


def setup_logging(
    level: int | str | None = None,
    format_string: str | None = None,
) -> logging.Logger:
    """Configure logging for the application.

    Args:
        level: Logging level (e.g., 'DEBUG', 'INFO', 'ERROR').
               Defaults to LOGGING_LEVEL env var or 'INFO'.
        format_string: Custom log format string. Defaults to a structured format.

    Returns:
        The root logger configured for the application.
    """
    # Get level from environment or use default
    if level is None:
        level = os.environ.get("LOGGING_LEVEL", "INFO")

    # Default format with request ID support
    if format_string is None:
        format_string = (
            "%(asctime)s [%(levelname)s] [%(name)s] [request=%(request_id)s] %(message)s"
        )

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # Create formatter with request ID
    formatter = logging.Formatter(format_string)
    console_handler.setFormatter(formatter)

    # Add handler to root logger
    logger.addHandler(console_handler)

    # Disable noisy third-party loggers
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("httpx").propagate = False
    logging.getLogger("asyncio").setLevel("WARNING")
    logging.getLogger("asyncio").propagate = False

    return logger


class RequestLoggerAdapter(logging.LoggerAdapter[Any]):
    """Logger adapter that automatically adds request ID to log records."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Process the log record and add request context."""
        extra = kwargs.get("extra")
        if extra is None:
            extra = {}
        request_id = get_request_id()
        if request_id is not None:
            extra["request_id"] = request_id
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> RequestLoggerAdapter:
    """Get a logger for the given module name.

    Args:
        name: The module name (e.g., __name__).

    Returns:
        A configured logger with request context support.
    """
    logger = logging.getLogger(name)
    return RequestLoggerAdapter(logger, {})


# Convenience function for creating module-level loggers
def create_logger(name: str) -> RequestLoggerAdapter:
    """Create and return a logger for a module.

    Args:
        name: The module name (typically __name__).

    Returns:
        A configured logger instance.
    """
    return get_logger(name)
