"""Exit codes and exceptions shared by all commands."""

from __future__ import annotations

EXIT_OK = 0
EXIT_WARNINGS = 1
EXIT_ERROR = 2
EXIT_CRITICAL_LOSS = 3  # pack written, but critical information was dropped
EXIT_USAGE = 64


class ContextBridgeError(Exception):
    """Base class; carries the process exit code."""

    exit_code = EXIT_ERROR


class ConfigError(ContextBridgeError):
    """A configuration file is unreadable or invalid."""


class PolicyViolation(ContextBridgeError):
    """The requested root or source is blocked by a deny rule."""


class UnsafePathError(ContextBridgeError):
    """A path failed a safety check (outside root, symlink escape, special file, ...)."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason
