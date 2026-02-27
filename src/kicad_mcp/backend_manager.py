"""Backend factory and manager for KiCad communication.

Provides a unified interface for selecting and accessing different
backends (kicad-cli, IPC, parser) based on availability and operation type.
"""

from __future__ import annotations

from typing import Any

from .logging_config import create_logger

logger = create_logger(__name__)


class BackendManager:
    """Manages backend selection and provides unified access.

    The backend manager handles:
    - Auto-detection of available backends
    - Smart backend selection based on operation type
    - Graceful degradation when backends are unavailable
    """

    def __init__(self, lazy_init: bool = True) -> None:
        """Initialize the backend manager.

        Args:
            lazy_init: If True (default), backends are initialized on first use.
                      If False, all backends are initialized immediately.
        """
        self._cli_backend: Any | None = None
        self._ipc_backend: Any | None = None
        self._parser_available = True
        self._lazy_init = lazy_init

        if not lazy_init:
            self._initialize_backends()

    def _initialize_backends(self) -> None:
        """Initialize detected backends."""
        try:
            from .backends import KiCadCli

            if KiCadCli.is_available():
                self._cli_backend = KiCadCli()
                logger.info("kicad-cli backend initialized")
            else:
                logger.warning("kicad-cli not available")
        except Exception as e:
            logger.warning(f"Failed to initialize kicad-cli backend: {e}")

        try:
            from .backends import IpcBackend

            ipc_backend_instance = IpcBackend.get()
            if ipc_backend_instance.connect():
                self._ipc_backend = ipc_backend_instance
                logger.info("IPC backend initialized")
            else:
                logger.info("IPC backend not available (KiCad not running or not KiCad 9+)")
        except Exception as e:
            logger.warning(f"Failed to initialize IPC backend: {e}")

    def get_backend_for_operation(self, operation: str) -> str | None:
        """Get the recommended backend for an operation.

        Args:
            operation: Operation type (e.g., 'drc', 'export', 'sync').

        Returns:
            Backend name: 'cli', 'ipc', 'parser', or None
        """
        operation = operation.lower()

        if operation in ["sync", "ipc_sync", "live_update"]:
            if self._ipc_backend is not None:
                return "ipc"
            logger.warning("IPC sync requested but not available")
            return None

        if operation in ["drc", "export", "render", "export_gerbers", "export_pdf", "export_svg"]:
            if self._cli_backend is not None:
                return "cli"
            logger.warning("kicad-cli requested but not available")
            return None

        if operation in ["read", "analyze", "parse", "extract"]:
            return "parser"

        if self._cli_backend is not None:
            return "cli"
        return "parser"

    @property
    def cli_backend(self) -> Any | None:
        """Get the kicad-cli backend instance."""
        if self._lazy_init and self._cli_backend is None:
            self._initialize_backends()
        return self._cli_backend

    @property
    def ipc_backend(self) -> Any | None:
        """Get the IPC backend instance."""
        if self._lazy_init and self._ipc_backend is None:
            self._initialize_backends()
        return self._ipc_backend

    @property
    def has_cli(self) -> bool:
        """Check if kicad-cli is available."""
        return self._cli_backend is not None

    @property
    def has_ipc(self) -> bool:
        """Check if IPC backend is available."""
        return self._ipc_backend is not None

    @property
    def has_parser(self) -> bool:
        """Check if parser is available (always True)."""
        return self._parser_available

    def is_available(self, operation: str) -> bool:
        """Check if an operation can be performed."""
        # Ensure backends are initialized before checking
        if self._lazy_init:
            self._initialize_backends()
        backend = self.get_backend_for_operation(operation)
        return backend is not None

    def health_check(self) -> dict[str, Any]:
        """Perform a health check on all backends."""
        # Ensure backends are initialized before checking
        if self._lazy_init:
            self._initialize_backends()

        result: dict[str, Any] = {
            "status": "healthy",
            "backends": {},
        }

        if self.has_cli and self._cli_backend is not None:
            try:
                version = self._cli_backend.version()
                result["backends"]["cli"] = {
                    "status": "healthy",
                    "version": version,
                }
            except Exception as e:
                result["backends"]["cli"] = {
                    "status": "degraded",
                    "error": str(e),
                }
        else:
            result["backends"]["cli"] = {"status": "unavailable"}

        if self.has_ipc:
            result["backends"]["ipc"] = {"status": "healthy"}
        else:
            result["backends"]["ipc"] = {
                "status": "unavailable",
                "reason": "KiCad not running or not KiCad 9+",
            }

        result["backends"]["parser"] = {"status": "healthy"}

        if not self.has_cli and not self.has_ipc:
            result["status"] = "degraded"
            result["message"] = "Only parser available - some operations will be disabled"

        return result


_backend_manager: BackendManager | None = None


def get_backend_manager() -> BackendManager:
    """Get the global backend manager instance (singleton)."""
    global _backend_manager
    if _backend_manager is None:
        _backend_manager = BackendManager()
    return _backend_manager
