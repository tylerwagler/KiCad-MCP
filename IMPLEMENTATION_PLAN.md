# Production Readiness Implementation Plan

**Document Version:** 1.0  
**Last Updated:** March 7, 2026  
**Status:** Ready to Execute

---

## Overview

This document provides a detailed, step-by-step implementation plan for the production readiness recommendations identified in the audit. Each recommendation includes implementation details, code examples, testing criteria, and timeline estimates.

---

## Phase 1: High Priority (Week 1)

### Goal: Enable production deployment with proper observability and configuration management

---

## 1.1 Health Check Endpoint

**Objective:** Enable container orchestration health checks and load balancer monitoring

**Time Estimate:** 2-3 hours

**Dependencies:** None

### Implementation Steps

#### Step 1: Create Health Check Module

Create `src/kicad_mcp/health.py`:

```python
"""Health check system for production monitoring."""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .backends.kicad_cli import KiCadCli, KiCadCliNotFound


@dataclass
class HealthStatus:
    """Health check result."""

    status: str  # "healthy", "degraded", "unhealthy"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: str = "0.1.0"
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "version": self.version,
            "checks": self.checks,
        }


class HealthChecker:
    """Manages health checks for the application."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_check: datetime | None = None
        self._check_history: list[HealthStatus] = []
        self._max_history = 100

    def check_all(self) -> HealthStatus:
        """Run all health checks and return aggregated status."""
        checks: dict[str, dict[str, Any]] = {}
        overall_status = "healthy"

        # Check 1: File system accessibility
        fs_check = self._check_filesystem()
        checks["filesystem"] = fs_check
        if fs_check["status"] != "healthy":
            overall_status = "degraded"

        # Check 2: kicad-cli availability (optional)
        kicad_check = self._check_kicad_cli()
        checks["kicad_cli"] = kicad_check
        if kicad_check["status"] == "unhealthy":
            # kicad-cli is optional, so only mark as degraded
            if overall_status == "healthy":
                overall_status = "degraded"

        # Check 3: Memory usage (basic check)
        memory_check = self._check_memory()
        checks["memory"] = memory_check
        if memory_check["status"] != "healthy":
            overall_status = "degraded"

        status = HealthStatus(status=overall_status, checks=checks)

        with self._lock:
            self._last_check = datetime.now(timezone.utc)
            self._check_history.append(status)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

        return status

    def _check_filesystem(self) -> dict[str, Any]:
        """Check if filesystem is accessible."""
        try:
            # Test write access to temp directory
            test_file = Path("/tmp/kicad_mcp_health_check")
            test_file.write_text("ok")
            test_file.unlink()
            return {"status": "healthy", "message": "Filesystem accessible"}
        except OSError as e:
            return {"status": "unhealthy", "message": f"Filesystem error: {e}"}

    def _check_kicad_cli(self) -> dict[str, Any]:
        """Check if kicad-cli is available."""
        try:
            if KiCadCli.is_available():
                return {"status": "healthy", "message": "kicad-cli available"}
            return {
                "status": "degraded",
                "message": "kicad-cli not installed (optional for read-only operations)",
            }
        except Exception as e:
            return {"status": "unhealthy", "message": f"kicad-cli error: {e}"}

    def _check_memory(self) -> dict[str, Any]:
        """Basic memory check."""
        try:
            import resource

            # Get memory usage (Unix only)
            usage = resource.getrusage(resource.RUSAGE_SELF)
            memory_mb = usage.ru_maxrss / 1024  # Convert to MB on Linux

            if memory_mb > 4000:  # 4GB threshold
                return {
                    "status": "degraded",
                    "message": f"High memory usage: {memory_mb:.0f}MB",
                }
            return {"status": "healthy", "memory_mb": round(memory_mb, 2)}
        except ImportError:
            # Windows doesn't have resource module
            return {"status": "healthy", "message": "Memory check not available on Windows"}

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent health check history."""
        with self._lock:
            return [check.to_dict() for check in self._check_history[-limit:]]


# Singleton instance
_health_checker: HealthChecker | None = None
_health_checker_lock = threading.Lock()


def get_health_checker() -> HealthChecker:
    """Get the health checker singleton."""
    global _health_checker
    if _health_checker is None:
        with _health_checker_lock:
            if _health_checker is None:
                _health_checker = HealthChecker()
    return _health_checker


def check_health() -> HealthStatus:
    """Public API for health checks."""
    return get_health_checker().check_all()
```

#### Step 2: Integrate with MCP Server

Modify `src/kicad_mcp/server.py`:

```python
"""KiCad MCP Server — entry point."""

from __future__ import annotations

from fastmcp import FastMCP

from .health import check_health
from .prompts import register_prompts
from .resources import register_board_resources
from .tools import TOOL_REGISTRY, register_router_tools


def create_server() -> FastMCP:
    """Create and configure the KiCad MCP server."""
    mcp = FastMCP("kicad-mcp")

    # Register health check as an MCP tool
    @mcp.tool()
    def health_check() -> dict:
        """Check the health status of the server.

        Returns the status of various system components:
        - filesystem: File system accessibility
        - kicad_cli: kicad-cli availability (optional)
        - memory: Memory usage status

        Use this to verify the server is operational.
        """
        return check_health().to_dict()

    # Register the 4 router meta-tools
    register_router_tools(mcp)

    # Register direct tools with FastMCP (always visible to the LLM)
    for spec in TOOL_REGISTRY.values():
        if spec.direct:
            mcp.tool(spec.handler, name=spec.name, description=spec.description)

    # Register MCP resources (read-only board state)
    register_board_resources(mcp)

    # Register MCP prompt templates
    register_prompts(mcp)

    return mcp


def main() -> None:
    """CLI entry point."""
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
```

#### Step 3: Add HTTP Health Endpoint (Optional)

If deploying with HTTP transport, add in `server.py`:

```python
# Add after creating the FastMCP instance
@app.get("/health")
async def health_endpoint():
    """HTTP health check endpoint for load balancers."""
    return check_health().to_dict()
```

### Testing Criteria

- [ ] Health check returns `{"status": "healthy", ...}` when system is operational
- [ ] Health check returns `{"status": "degraded", ...}` when optional components unavailable
- [ ] Health check returns `{"status": "unhealthy", ...}` on critical failures
- [ ] kicad-cli check shows "degraded" when not installed (expected)
- [ ] Memory check reports current usage
- [ ] All check results include timestamps

---

## 1.2 Structured Logging

**Objective:** Enable production debugging, log aggregation, and incident response

**Time Estimate:** 3-4 hours

**Dependencies:** None

### Implementation Steps

#### Step 1: Create Logging Configuration Module

Create `src/kicad_mcp/logging_config.py`:

```python
"""Structured logging configuration for production."""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .config import get_config


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter for production."""

    def __init__(self) -> None:
        super().__init__()
        self._environment = os.getenv("KICAD_MCP_ENV", "development")

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "environment": self._environment,
        }

        # Add context
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "tool_name"):
            log_data["tool_name"] = record.tool_name

        # Add location info
        log_data["location"] = f"{record.filename}:{record.lineno}"

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add extra fields
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in {
                    "args",
                    "created",
                    "exc_info",
                    "exc_text",
                    "filename",
                    "funcName",
                    "levelname",
                    "levelno",
                    "lineno",
                    "module",
                    "msecs",
                    "message",
                    "msg",
                    "name",
                    "pathname",
                    "process",
                    "processName",
                    "relativeCreated",
                    "stack_info",
                    "thread",
                    "threadName",
                }:
                    log_data[key] = value

        return json.dumps(log_data)


class LoggingContextFilter(logging.Filter):
    """Add context to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context to log record."""
        # Add request ID if not present
        if not hasattr(record, "request_id"):
            record.request_id = str(uuid4())[:8]

        return True


def setup_logging() -> logging.Logger:
    """Configure structured logging.

    Returns the root logger configured for the application.
    """
    config = get_config()

    # Get log level from config
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.addFilter(LoggingContextFilter())
    console_handler.setFormatter(StructuredFormatter())

    root_logger.addHandler(console_handler)

    # Add file handler for production
    if config.log_file:
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            config.log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )
        file_handler.setLevel(log_level)
        file_handler.addFilter(LoggingContextFilter())
        file_handler.setFormatter(StructuredFormatter())

        root_logger.addHandler(file_handler)

    # Set library log levels
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


def log_with_context(
    logger: logging.Logger,
    level: str,
    message: str,
    **context: Any,
) -> None:
    """Log a message with additional context.

    Args:
        logger: Logger instance
        level: Log level ('debug', 'info', 'warning', 'error')
        message: Log message
        **context: Additional context to include
    """
    extra = {k: v for k, v in context.items()}

    if level == "debug":
        logger.debug(message, extra=extra)
    elif level == "info":
        logger.info(message, extra=extra)
    elif level == "warning":
        logger.warning(message, extra=extra)
    elif level == "error":
        logger.error(message, extra=extra)
    elif level == "critical":
        logger.critical(message, extra=extra)
```

#### Step 2: Create Configuration Module

Create `src/kicad_mcp/config.py`:

```python
"""Configuration management for the MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Application configuration."""

    # Logging
    log_level: str = field(default_factory=lambda: os.getenv("KICAD_MCP_LOG_LEVEL", "INFO"))
    log_file: str | None = field(default_factory=lambda: os.getenv("KICAD_MCP_LOG_FILE"))

    # Rate limiting
    rate_limit_max_requests: int = field(
        default_factory=lambda: int(os.getenv("KICAD_MCP_RATE_LIMIT_MAX_REQUESTS", "100"))
    )
    rate_limit_window: int = field(
        default_factory=lambda: int(os.getenv("KICAD_MCP_RATE_LIMIT_WINDOW", "60"))
    )

    # Timeouts
    timeout: int = field(default_factory=lambda: int(os.getenv("KICAD_MCP_TIMEOUT", "120"))
    kicad_cli_timeout: int = field(
        default_factory=lambda: int(os.getenv("KICAD_MCP_KICAD_CLI_TIMEOUT", "120"))
    )

    # Security
    trusted_roots: list[str] = field(
        default_factory=lambda: os.getenv("KICAD_MCP_TRUSTED_ROOTS", "").split(":")
    )

    # Environment
    environment: str = field(default_factory=lambda: os.getenv("KICAD_MCP_ENV", "development"))

    # Feature flags
    enable_metrics: bool = field(
        default_factory=lambda: os.getenv("KICAD_MCP_ENABLE_METRICS", "false").lower() == "true"
    )
    enable_error_tracking: bool = field(
        default_factory=lambda: os.getenv("KICAD_MCP_ENABLE_ERROR_TRACKING", "false").lower()
        == "true"
    )


# Singleton
_config: Config | None = None


def get_config() -> Config:
    """Get the application configuration singleton."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload configuration from environment variables."""
    global _config
    _config = Config()
    return _config
```

#### Step 3: Update Server to Use Structured Logging

Modify `src/kicad_mcp/server.py`:

```python
"""KiCad MCP Server — entry point."""

from __future__ import annotations

from fastmcp import FastMCP

from .config import get_config
from .health import check_health
from .logging_config import get_logger, setup_logging
from .prompts import register_prompts
from .resources import register_board_resources
from .tools import TOOL_REGISTRY, register_router_tools

logger = get_logger(__name__)


def create_server() -> FastMCP:
    """Create and configure the KiCad MCP server."""
    logger.info("Creating KiCad MCP server", extra={"config": get_config().__dict__})

    mcp = FastMCP("kicad-mcp")

    @mcp.tool()
    def health_check() -> dict:
        """Check the health status of the server."""
        return check_health().to_dict()

    register_router_tools(mcp)

    for spec in TOOL_REGISTRY.values():
        if spec.direct:
            mcp.tool(spec.handler, name=spec.name, description=spec.description)

    register_board_resources(mcp)
    register_prompts(mcp)

    logger.info("Server created successfully")
    return mcp


def main() -> None:
    """CLI entry point."""
    setup_logging()
    logger.info("Starting KiCad MCP server")

    server = create_server()
    logger.info("Server ready to accept connections")

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutting down")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
```

#### Step 4: Add Logging to Tool Handlers

Example for a tool handler in `src/kicad_mcp/tools/drc.py`:

```python
"""DRC tools."""

from __future__ import annotations

from ..logging_config import get_logger
from ..backends.kicad_cli import KiCadCli

logger = get_logger(__name__)


async def run_drc(board_path: str, severity: str = "all") -> dict:
    """Run Design Rule Check on a board.

    Args:
        board_path: Path to .kicad_pcb file.
        severity: 'all', 'error', or 'warning'.

    Returns:
        DRC results.
    """
    logger.info(
        "Running DRC",
        extra={"tool_name": "run_drc", "board_path": board_path, "severity": severity},
    )

    try:
        cli = KiCadCli()
        result = await cli.run_drc(board_path, severity=severity)

        if result.passed:
            logger.info(
                "DRC passed",
                extra={
                    "tool_name": "run_drc",
                    "warnings": result.warning_count,
                },
            )
        else:
            logger.warning(
                "DRC found violations",
                extra={
                    "tool_name": "run_drc",
                    "errors": result.error_count,
                    "warnings": result.warning_count,
                },
            )

        return result.to_dict()

    except Exception as e:
        logger.error(
            f"DRC failed: {e}",
            extra={"tool_name": "run_drc", "board_path": board_path},
            exc_info=True,
        )
        raise
```

### Testing Criteria

- [ ] Logs are formatted as valid JSON
- [ ] Each log entry includes timestamp, level, logger, message, location
- [ ] Exception logs include full traceback
- [ ] Context fields (request_id, tool_name) are included when provided
- [ ] Log rotation works correctly (10MB max, 5 backups)
- [ ] Log level respects environment variable configuration
- [ ] No logs written when level is above configured threshold

---

## 1.3 Configuration Externalization

**Objective:** Enable environment-specific configuration without code changes

**Time Estimate:** 2-3 hours

**Dependencies:** `src/kicad_mcp/config.py` (created in 1.2)

### Implementation Steps

#### Step 1: Review Configuration Module

The `Config` dataclass was created in 1.2. Ensure all configurable values are included:

```python
# Already created in logging_config.py - verify completeness

# Add any missing configuration options:
@dataclass
class Config:
    # ... existing fields ...

    # Session management
    max_sessions: int = field(
        default_factory=lambda: int(os.getenv("KICAD_MCP_MAX_SESSIONS", "10"))
    )
    session_timeout_minutes: int = field(
        default_factory=lambda: int(os.getenv("KICAD_MCP_SESSION_TIMEOUT", "60"))
    )

    # Performance
    max_response_size_bytes: int = field(
        default_factory=lambda: int(os.getenv("KICAD_MCP_MAX_RESPONSE_SIZE", "50000"))
    )
    cache_enabled: bool = field(
        default_factory=lambda: os.getenv("KICAD_MCP_CACHE_ENABLED", "true").lower() == "true"
    )
    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("KICAD_MCP_CACHE_TTL", "300"))
    )

    # Debug
    enable_debug_mode: bool = field(
        default_factory=lambda: os.getenv("KICAD_MCP_DEBUG", "false").lower() == "true"
    )
```

#### Step 2: Create Configuration Validation

Create `src/kicad_mcp/config_validation.py`:

```python
"""Configuration validation utilities."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from .config import Config
from .exceptions import ValidationError


def validate_config(config: Config) -> list[str]:
    """Validate configuration values.

    Args:
        config: Configuration to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    # Log level validation
    valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if config.log_level.upper() not in valid_log_levels:
        errors.append(
            f"Invalid log level: {config.log_level}. "
            f"Must be one of: {', '.join(valid_log_levels)}"
        )

    # Timeout validation
    if config.timeout < 10:
        errors.append(f"Timeout too low: {config.timeout}s. Minimum: 10s")
    if config.timeout > 3600:
        errors.append(f"Timeout too high: {config.timeout}s. Maximum: 3600s")

    # Rate limit validation
    if config.rate_limit_max_requests < 1:
        errors.append(f"Rate limit must be at least 1, got: {config.rate_limit_max_requests}")
    if config.rate_limit_window < 1:
        errors.append(f"Rate limit window must be at least 1s, got: {config.rate_limit_window}s")

    # Memory limits
    if config.max_response_size_bytes < 1000:
        errors.append(f"Max response size too small: {config.max_response_size_bytes}")
    if config.max_response_size_bytes > 100_000_000:  # 100MB
        errors.append(f"Max response size too large: {config.max_response_size_bytes}")

    return errors


def validate_and_raise(config: Config | None = None) -> None:
    """Validate configuration and raise if invalid.

    Args:
        config: Configuration to validate. If None, uses default config.

    Raises:
        ValidationError: If configuration is invalid
    """
    from .config import get_config

    config = config or get_config()
    errors = validate_config(config)

    if errors:
        raise ValidationError(
            f"Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )
```

#### Step 3: Add Configuration Documentation

Create `CONFIGURATION.md`:

```markdown
# Configuration Reference

All configuration options can be set via environment variables.

## Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `KICAD_MCP_LOG_LEVEL` | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `KICAD_MCP_LOG_FILE` | `None` | Path to log file (optional) |

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `KICAD_MCP_RATE_LIMIT_MAX_REQUESTS` | `100` | Max requests per window |
| `KICAD_MCP_RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds |

## Timeouts

| Variable | Default | Description |
|----------|---------|-------------|
| `KICAD_MCP_TIMEOUT` | `120` | Default timeout in seconds |
| `KICAD_MCP_KICAD_CLI_TIMEOUT` | `120` | kicad-cli timeout in seconds |

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `KICAD_MCP_TRUSTED_ROOTS` | `None` | Colon-separated list of trusted directories |

## Session Management

| Variable | Default | Description |
|----------|---------|-------------|
| `KICAD_MCP_MAX_SESSIONS` | `10` | Maximum concurrent sessions |
| `KICAD_MCP_SESSION_TIMEOUT` | `60` | Session timeout in minutes |

## Performance

| Variable | Default | Description |
|----------|---------|-------------|
| `KICAD_MCP_MAX_RESPONSE_SIZE` | `50000` | Max response size in bytes |
| `KICAD_MCP_CACHE_ENABLED` | `true` | Enable caching |
| `KICAD_MCP_CACHE_TTL` | `300` | Cache TTL in seconds |

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `KICAD_MCP_ENV` | `development` | Environment: development, staging, production |
| `KICAD_MCP_DEBUG` | `false` | Enable debug mode |

## Monitoring

| Variable | Default | Description |
|----------|---------|-------------|
| `KICAD_MCP_ENABLE_METRICS` | `false` | Enable Prometheus metrics |
| `KICAD_MCP_ENABLE_ERROR_TRACKING` | `false` | Enable error tracking (Sentry) |
| `SENTRY_DSN` | `None` | Sentry DSN for error tracking |

## Example Production Configuration

```bash
export KICAD_MCP_LOG_LEVEL=INFO
export KICAD_MCP_LOG_FILE=/var/log/kicad-mcp/server.log
export KICAD_MCP_RATE_LIMIT_MAX_REQUESTS=100
export KICAD_MCP_RATE_LIMIT_WINDOW=60
export KICAD_MCP_TIMEOUT=120
export KICAD_MCP_ENV=production
export KICAD_MCP_ENABLE_METRICS=true
export KICAD_MCP_ENABLE_ERROR_TRACKING=true
export SENTRY_DSN=https://your-sentry-dsn
```

### Docker Compose Example

```yaml
version: '3.8'

services:
  kicad-mcp:
    image: kicad-mcp:latest
    environment:
      - KICAD_MCP_LOG_LEVEL=INFO
      - KICAD_MCP_LOG_FILE=/var/log/kicad-mcp/server.log
      - KICAD_MCP_ENV=production
      - KICAD_MCP_RATE_LIMIT_MAX_REQUESTS=100
      - KICAD_MCP_RATE_LIMIT_WINDOW=60
    volumes:
      - ./logs:/var/log/kicad-mcp
      - ./data:/data
    ports:
      - "8080:8080"
```
```

#### Step 4: Add Configuration Validation to Startup

Modify `src/kicad_mcp/server.py`:

```python
def main() -> None:
    """CLI entry point."""
    from .config_validation import validate_and_raise

    setup_logging()
    logger.info("Starting KiCad MCP server")

    # Validate configuration
    try:
        validate_and_raise()
        logger.info("Configuration validated successfully")
    except ValidationError as e:
        logger.error(f"Configuration validation failed: {e}")
        sys.exit(1)

    server = create_server()
    logger.info("Server ready to accept connections")

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutting down")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise
```

### Testing Criteria

- [ ] Configuration loads from environment variables
- [ ] Default values used when environment variables not set
- [ ] Configuration validation catches invalid values
- [ ] Invalid configuration causes clear error messages
- [ ] Configuration can be reloaded dynamically
- [ ] Documentation covers all configuration options

---

## Phase 2: Medium Priority (Month 1)

### Goal: Add observability and incident response capabilities

---

## 2.1 Monitoring/Metrics Collection

**Objective:** Enable performance tracking, alerting, and capacity planning

**Time Estimate:** 6-8 hours

**Dependencies:** Configuration module, structured logging

### Implementation Steps

#### Step 1: Install Prometheus Client

Update `pyproject.toml`:

```toml
[project.optional-dependencies]
# ... existing ...
monitoring = [
    "prometheus-client>=0.19",
]
```

#### Step 2: Create Metrics Module

Create `src/kicad_mcp/metrics.py`:

```python
"""Prometheus metrics for monitoring."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    start_http_server,
)

from .config import get_config

# Initialize metrics

# Server info
server_info = Info(
    "kicad_mcp",
    "KiCad MCP Server information",
    instance="default",
)

# Tool execution metrics
tool_executions = Counter(
    "kicad_mcp_tool_executions_total",
    "Total number of tool executions",
    ["tool_name", "status", "category"],
)

tool_execution_duration = Histogram(
    "kicad_mcp_tool_execution_seconds",
    "Time spent executing tools",
    ["tool_name", "category"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
)

# Session metrics
sessions_active = Gauge(
    "kicad_mcp_sessions_active",
    "Number of active sessions",
)

session_operations = Counter(
    "kicad_mcp_session_operations_total",
    "Total session operations",
    ["operation_type", "status"],
)

# Error metrics
errors_total = Counter(
    "kicad_mcp_errors_total",
    "Total number of errors",
    ["error_type", "tool_name"],
)

# Performance metrics
response_size = Histogram(
    "kicad_mcp_response_size_bytes",
    "Size of tool responses",
    buckets=[100, 1000, 10000, 50000, 100000, 500000],
)

# Resource metrics
memory_usage_bytes = Gauge(
    "kicad_mcp_memory_usage_bytes",
    "Current memory usage in bytes",
)

# Initialize server info
def init_server_info() -> None:
    """Initialize server information."""
    import __version__

    server_info.info(
        {
            "version": __version__,
            "environment": get_config().environment,
        }
    )


def start_metrics_server(port: int = 8000) -> None:
    """Start Prometheus HTTP metrics server.

    Args:
        port: Port to expose metrics on
    """
    config = get_config()
    if config.enable_metrics:
        start_http_server(port)
        init_server_info()


def track_tool_execution(
    tool_name: str,
    category: str = "general",
) -> Generator[dict[str, Any], None, None]:
    """Context manager to track tool execution metrics.

    Usage:
        with track_tool_execution("run_drc", "drc"):
            result = await run_drc(board_path)
    """
    start_time = time.time()
    try:
        yield {"start_time": start_time}
        tool_executions.labels(tool_name=tool_name, status="success", category=category).inc()
    except Exception:
        tool_executions.labels(tool_name=tool_name, status="error", category=category).inc()
        raise
    finally:
        duration = time.time() - start_time
        tool_execution_duration.labels(tool_name=tool_name, category=category).observe(duration)


def record_response_size(size_bytes: int) -> None:
    """Record response size.

    Args:
        size_bytes: Size of response in bytes
    """
    response_size.observe(size_bytes)


def record_error(error_type: str, tool_name: str | None = None) -> None:
    """Record an error.

    Args:
        error_type: Type of error
        tool_name: Tool that caused the error (optional)
    """
    errors_total.labels(error_type=error_type, tool_name=tool_name or "unknown").inc()


def update_memory_usage() -> None:
    """Update memory usage gauge."""
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        memory_usage_bytes.set(usage.ru_maxrss * 1024)  # Convert KB to bytes
    except ImportError:
        pass  # Windows doesn't have resource module


@contextmanager
def track_session_operation(operation_type: str) -> Generator[None, None, None]:
    """Track session operation metrics."""
    try:
        session_operations.labels(operation_type=operation_type, status="success").inc()
        yield
    except Exception:
        session_operations.labels(operation_type=operation_type, status="error").inc()
        raise
```

#### Step 3: Integrate Metrics with Tool Handlers

Example integration in `src/kicad_mcp/tools/drc.py`:

```python
from ..metrics import track_tool_execution, record_response_size, record_error

async def run_drc(board_path: str, severity: str = "all") -> dict:
    """Run Design Rule Check on a board."""
    try:
        with track_tool_execution("run_drc", "drc"):
            cli = KiCadCli()
            result = await cli.run_drc(board_path, severity=severity)

            # Record response size
            import json
            response_size = len(json.dumps(result.to_dict(), default=str))
            record_response_size(response_size)

            return result.to_dict()

    except Exception as e:
        record_error(type(e).__name__, "run_drc")
        raise
```

#### Step 4: Update Server Startup

Modify `src/kicad_mcp/server.py`:

```python
from .metrics import start_metrics_server

def main() -> None:
    """CLI entry point."""
    setup_logging()
    logger.info("Starting KiCad MCP server")

    # Start metrics server if enabled
    config = get_config()
    if config.enable_metrics:
        start_metrics_server()
        logger.info("Metrics server started on port 8000")

    server = create_server()
    logger.info("Server ready to accept connections")

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutting down")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise
```

#### Step 5: Create Grafana Dashboard

Create `grafana/dashboard.json` with pre-built dashboard configuration.

### Testing Criteria

- [ ] Metrics endpoint accessible at configured port
- [ ] Tool executions tracked with correct labels
- [ ] Error counts increment correctly
- [ ] Response sizes recorded
- [ ] Memory usage updated periodically
- [ ] Metrics persist across restarts

---

## 2.2 Error Tracking Integration

**Objective:** Enable rapid incident response and debugging

**Time Estimate:** 3-4 hours

**Dependencies:** Structured logging

### Implementation Steps

#### Step 1: Install Sentry SDK

Update `pyproject.toml`:

```toml
[project.optional-dependencies]
# ... existing ...
error_tracking = [
    "sentry-sdk>=2.0",
]
```

#### Step 2: Create Error Tracking Module

Create `src/kicad_mcp/error_tracking.py`:

```python
"""Error tracking integration (Sentry)."""

from __future__ import annotations

import os
import sys
from typing import Any

from .config import get_config


def init_error_tracking() -> None:
    """Initialize error tracking if configured."""
    config = get_config()

    if not config.enable_error_tracking:
        return

    sentry_dsn = os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.threading import ThreadingIntegration

        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=config.environment,
            integrations=[
                LoggingIntegration(
                    event_level=logging.ERROR,
                    breadcrumb_level=logging.INFO,
                ),
                ThreadingIntegration(propagate_hub=True),
            ],
            traces_sample_rate=0.1,  # 10% sampling for performance
            profiles_sample_rate=0.1,  # 10% profiling
            max_breadcrumbs=50,
            send_default_pii=False,
        )

        # Set release version
        try:
            from . import __version__

            sentry_sdk.set_tag("version", __version__)
        except ImportError:
            pass

        logging.info("Error tracking initialized")

    except ImportError:
        logging.warning("Error tracking enabled but sentry-sdk not installed")


def capture_exception(exception: Exception, **context: Any) -> str | None:
    """Capture an exception for error tracking.

    Args:
        exception: Exception to capture
        **context: Additional context to include

    Returns:
        Event ID if captured, None otherwise
    """
    try:
        import sentry_sdk

        with sentry_sdk.push_context() as scope:
            for key, value in context.items():
                scope.set_tag(key, str(value))

            return sentry_sdk.capture_exception(exception)

    except ImportError:
        return None


def capture_message(message: str, level: str = "info", **context: Any) -> str | None:
    """Capture a message for error tracking.

    Args:
        message: Message to capture
        level: Log level (info, warning, error)
        **context: Additional context to include

    Returns:
        Event ID if captured, None otherwise
    """
    try:
        import sentry_sdk

        with sentry_sdk.push_context() as scope:
            scope.set_level(getattr(sentry_sdk.Hub.current.client.options, "level", level))
            for key, value in context.items():
                scope.set_tag(key, str(value))

            return sentry_sdk.capture_message(message, level=level)

    except ImportError:
        return None
```

#### Step 3: Integrate with Server

Modify `src/kicad_mcp/server.py`:

```python
from .error_tracking import init_error_tracking, capture_exception

def main() -> None:
    """CLI entry point."""
    setup_logging()
    logger.info("Starting KiCad MCP server")

    # Initialize error tracking
    init_error_tracking()

    server = create_server()
    logger.info("Server ready to accept connections")

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutting down")
    except Exception as e:
        capture_exception(e, context={"server": "kicad-mcp"})
        logger.error(f"Server error: {e}", exc_info=True)
        raise
```

### Testing Criteria

- [ ] Errors captured when SENTRY_DSN configured
- [ ] Error context includes relevant tags
- [ ] No errors reported when SENTRY_DSN not set
- [ ] Error tracking doesn't block normal operation
- [ ] Performance impact minimal (<1%)

---

## Phase 3: Low Priority (Quarter 1)

### Goal: Add multi-tenant support and advanced features

---

## 3.1 Authentication/Authorization

**Objective:** Enable secure multi-tenant deployment

**Time Estimate:** 20-40 hours

**Dependencies:** Configuration module, error tracking

### Implementation Options

#### Option A: API Key Authentication (Simple)

```python
# src/kicad_mcp/auth.py
from __future__ import annotations

import hashlib
import os
from typing import Callable

from fastmcp import FastMCP


class APIKeyAuth:
    """Simple API key authentication."""

    def __init__(self, api_keys: set[str]) -> None:
        self._api_keys = {hashlib.sha256(key.encode()).hexdigest() for key in api_keys}

    def verify(self, api_key: str) -> bool:
        """Verify API key."""
        hashed = hashlib.sha256(api_key.encode()).hexdigest()
        return hashed in self._api_keys


def create_auth_middleware(api_keys: set[str]) -> Callable[[FastMCP], FastMCP]:
    """Create authentication middleware.

    Args:
        api_keys: Set of valid API keys

    Returns:
        Middleware function
    """
    auth = APIKeyAuth(api_keys)

    def middleware(mcp: FastMCP) -> FastMCP:
        # Add authentication logic
        return mcp

    return middleware
```

#### Option B: OAuth2 Integration (Complex)

- Use `authlib` library
- Support OAuth2 providers (GitHub, Google, etc.)
- Implement JWT token validation
- Add user session management

**Implementation Steps:**

1. Choose authentication method based on requirements
2. Design authentication flow
3. Implement authentication middleware
4. Add user management (if needed)
5. Test with various authentication scenarios
6. Document authentication setup

### Testing Criteria

- [ ] Authentication required for all tool executions
- [ ] Invalid credentials rejected with clear error
- [ ] Authentication doesn't break existing functionality
- [ ] Multiple authentication methods supported (if applicable)
- [ ] Security audit passed

---

## 3.2 Enhanced Rate Limiting

**Objective:** Per-user rate limiting for multi-tenant deployments

**Time Estimate:** 8-10 hours

**Dependencies:** Authentication system

### Implementation Steps

#### Step 1: Create Per-User Rate Limiter

```python
# src/kicad_mcp/rate_limiter.py (enhanced)

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .config import get_config


@dataclass
class UserRateLimit:
    """Per-user rate limit state."""

    tokens: float
    last_refill: float
    request_count: int = 0


class PerUserRateLimiter:
    """Rate limiter with per-user limits."""

    def __init__(self) -> None:
        config = get_config()
        self._max_tokens = config.rate_limit_max_requests
        self._window = config.rate_limit_window
        self._user_buckets: dict[str, UserRateLimit] = defaultdict(
            lambda: UserRateLimit(
                tokens=float(self._max_tokens),
                last_refill=time.time(),
            )
        )

    def check_rate_limit(self, user_id: str, tool_name: str) -> tuple[bool, float]:
        """Check if request is allowed for user.

        Args:
            user_id: Unique user identifier
            tool_name: Tool being executed

        Returns:
            (allowed, retry_after_seconds)
        """
        bucket = self._user_buckets[user_id]
        current_time = time.time()

        # Refill tokens based on elapsed time
        elapsed = current_time - bucket.last_refill
        bucket.tokens = min(
            self._max_tokens,
            bucket.tokens + elapsed * (self._max_tokens / self._window),
        )
        bucket.last_refill = current_time

        # Check if request allowed
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            bucket.request_count += 1
            return True, 0.0

        # Calculate retry time
        retry_after = (1.0 - bucket.tokens) / (self._max_tokens / self._window)
        return False, retry_after

    def get_user_stats(self, user_id: str) -> dict[str, Any]:
        """Get rate limit stats for user."""
        bucket = self._user_buckets[user_id]
        return {
            "tokens_remaining": bucket.tokens,
            "max_tokens": self._max_tokens,
            "window_seconds": self._window,
            "request_count": bucket.request_count,
        }
```

#### Step 2: Integrate with Tool Router

Update `src/kicad_mcp/tools/router.py` to accept user_id and check rate limits.

### Testing Criteria

- [ ] Each user has independent rate limit
- [ ] Rate limits reset after window expires
- [ ] Rate limit exceeded returns clear error with retry time
- [ ] Rate limit stats accessible per user
- [ ] No performance degradation from per-user tracking

---

## 3.3 Performance Monitoring Dashboard

**Objective:** Visualize system health and performance

**Time Estimate:** 16-20 hours

**Dependencies:** Metrics collection

### Implementation Steps

1. **Set up Prometheus** (1-2 hours)
   - Install Prometheus server
   - Configure scraping kicad-mcp metrics
   - Set retention policy

2. **Create Grafana Dashboard** (8-10 hours)
   - Design dashboard layout
   - Create panels for key metrics:
     - Tool execution rate
     - Error rate
     - Response times
     - Memory usage
     - Active sessions
   - Configure alerting rules
   - Test dashboard functionality

3. **Set up Alerting** (4-6 hours)
   - Configure Prometheus Alertmanager
   - Define alert rules:
     - High error rate (>5%)
     - High latency (p95 > 5s)
     - Memory usage (>80%)
     - Service down
   - Configure notification channels (Slack, email, etc.)
   - Test alert delivery

4. **Documentation** (2-3 hours)
   - Document dashboard usage
   - Create runbooks for common alerts
   - Train operations team

### Deliverables

- Grafana dashboard JSON configuration
- Prometheus alerting rules
- Alert notification configuration
- Operational runbooks
- Training materials

---

## Implementation Timeline

### Week 1: High Priority Items

| Day | Tasks | Deliverables |
|-----|-------|--------------|
| 1-2 | Health Check Endpoint | `src/kicad_mcp/health.py`, integration tests |
| 3-4 | Structured Logging | `src/kicad_mcp/logging_config.py`, updated tool handlers |
| 5 | Configuration Externalization | `src/kicad_mcp/config.py`, `CONFIGURATION.md` |
| End of Week | Integration & Testing | All Phase 1 features working together |

### Month 1: Medium Priority Items

| Week | Tasks | Deliverables |
|------|-------|--------------|
| 2-3 | Monitoring/Metrics | `src/kicad_mcp/metrics.py`, Grafana dashboard draft |
| 4 | Error Tracking | `src/kicad_mcp/error_tracking.py`, Sentry integration |
| End of Month | Integration & Testing | Full observability stack operational |

### Quarter 1: Low Priority Items

| Month | Tasks | Deliverables |
|-------|-------|--------------|
| 2 | Authentication | API key or OAuth2 implementation |
| 3 | Enhanced Rate Limiting | Per-user rate limiting |
| 4 | Performance Dashboard | Complete Grafana + Prometheus setup |
| End of Quarter | Documentation & Training | Complete operational documentation |

---

## Success Criteria

### Phase 1 (Week 1)
- [ ] Health check returns accurate system status
- [ ] Logs are structured JSON format
- [ ] All configuration via environment variables
- [ ] Zero downtime deployment possible

### Phase 2 (Month 1)
- [ ] Metrics accessible via Prometheus endpoint
- [ ] Grafana dashboards operational
- [ ] Error tracking captures exceptions
- [ ] Alerting configured and tested

### Phase 3 (Quarter 1)
- [ ] Authentication required for all requests
- [ ] Per-user rate limiting functional
- [ ] Performance dashboard provides actionable insights
- [ ] Operations team trained on new systems

---

## Risk Mitigation

### Risk: Configuration Changes Break Existing Functionality

**Mitigation:**
- Add comprehensive configuration validation
- Provide clear migration guide
- Maintain backward compatibility where possible
- Test in staging environment first

### Risk: Performance Impact from Monitoring

**Mitigation:**
- Use sampling for traces (10%)
- Configure appropriate metric retention
- Monitor monitoring overhead
- Disable in development environments

### Risk: Authentication Complexity

**Mitigation:**
- Start with simple API key authentication
- Add OAuth2 later if needed
- Provide clear authentication documentation
- Test with multiple authentication scenarios

---

## Conclusion

This implementation plan provides a clear, phased approach to production readiness. All Phase 1 items are critical for production deployment and should be completed first. Phases 2 and 3 enhance operational capabilities and can be implemented iteratively based on actual usage patterns and requirements.

**Total Estimated Effort:** 60-80 hours
- Phase 1: 7-10 hours
- Phase 2: 9-12 hours
- Phase 3: 44-70 hours

**Recommended Approach:**
1. Complete Phase 1 immediately (1 week)
2. Deploy to production with Phase 1 features
3. Gather real-world usage data
4. Prioritize Phase 2 and 3 based on actual needs

---

**Document Owner:** Engineering Team  
**Review Cycle:** Quarterly  
**Next Review:** June 2026
