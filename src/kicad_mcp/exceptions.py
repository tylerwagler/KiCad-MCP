"""Exception hierarchy for better error handling and categorization.

Defines typed exceptions for different error scenarios to enable
precise error handling and client-side error processing.
"""

from __future__ import annotations

from typing import Any


class KicadMcpError(Exception):
    """Base exception for all KiCad MCP errors."""

    error_code: str = ""

    def __init__(self, message: str, error_code: str | None = None, **kwargs: Any):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.__dict__.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Convert error to a serializable dict."""
        result: dict[str, Any] = {
            "error": True,
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
        }
        # Add any additional attributes
        result.update(
            {k: v for k, v in self.__dict__.items() if k not in ["message", "error_code"]}
        )
        return result


class ValidationError(KicadMcpError):
    """Raised when input validation fails."""

    error_code = "VALIDATION_ERROR"

    def __init__(self, message: str, field: str | None = None, **kwargs: Any):
        super().__init__(message, "VALIDATION_ERROR", field=field, **kwargs)


class AuthenticationError(KicadMcpError):
    """Raised when authentication fails."""

    error_code = "AUTHENTICATION_ERROR"


class AuthorizationError(KicadMcpError):
    """Raised when access is forbidden."""

    error_code = "AUTHORIZATION_ERROR"


class ResourceNotFoundError(KicadMcpError):
    """Raised when a requested resource is not found."""

    error_code = "NOT_FOUND"

    def __init__(self, message: str, resource_type: str | None = None, **kwargs: Any):
        super().__init__(message, "NOT_FOUND", resource_type=resource_type, **kwargs)


class RateLimitExceededError(KicadMcpError):
    """Raised when rate limits are exceeded."""

    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, message: str, retry_after: int | None = None, **kwargs: Any):
        super().__init__(message, "RATE_LIMIT_EXCEEDED", retry_after=retry_after, **kwargs)


class BackendError(KicadMcpError):
    """Raised when a backend operation fails."""

    error_code = "BACKEND_ERROR"

    def __init__(self, message: str, backend_name: str | None = None, **kwargs: Any):
        super().__init__(message, "BACKEND_ERROR", backend_name=backend_name, **kwargs)


class KiCadCliError(BackendError):
    """Raised when kicad-cli fails."""

    error_code = "KICAD_CLI_ERROR"

    def __init__(
        self,
        message: str,
        exit_code: int | None = None,
        stderr: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(message, "kicad-cli", exit_code=exit_code, stderr=stderr, **kwargs)


class IpcError(BackendError):
    """Raised when IPC communication fails."""

    error_code = "IPC_ERROR"

    def __init__(self, message: str, ipc_status: str | None = None, **kwargs: Any):
        super().__init__(message, "ipc", ipc_status=ipc_status, **kwargs)


class SessionError(KicadMcpError):
    """Raised when session operations fail."""

    error_code = "SESSION_ERROR"

    def __init__(self, message: str, session_id: str | None = None, **kwargs: Any):
        super().__init__(message, "SESSION_ERROR", session_id=session_id, **kwargs)


class SecurityError(KicadMcpError):
    """Raised when security checks fail.

    Note: This wraps the existing security module SecurityError.
    """

    error_code = "SECURITY_ERROR"

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(message, "SECURITY_ERROR", **kwargs)


class ToolExecutionError(KicadMcpError):
    """Raised when a tool execution fails."""

    error_code = "TOOL_EXECUTION_ERROR"

    def __init__(self, message: str, tool_name: str | None = None, **kwargs: Any):
        super().__init__(message, "TOOL_EXECUTION_ERROR", tool_name=tool_name, **kwargs)


class BoardLoadingError(KicadMcpError):
    """Raised when board loading fails."""

    error_code = "BOARD_LOADING_ERROR"

    def __init__(self, message: str, board_path: str | None = None, **kwargs: Any):
        super().__init__(message, "BOARD_LOADING_ERROR", board_path=board_path, **kwargs)


# Re-export for convenience
__all__ = [
    "KicadMcpError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "ResourceNotFoundError",
    "RateLimitExceededError",
    "BackendError",
    "KiCadCliError",
    "IpcError",
    "SessionError",
    "SecurityError",
    "ToolExecutionError",
    "BoardLoadingError",
]
