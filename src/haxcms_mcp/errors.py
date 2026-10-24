"""Error type and codes for the HAXcms MCP server.

Only ``HaxcmsMcpError`` escapes services (PLAN.md Section 5). The MCP message format is
``[CODE] message. hint``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable machine-readable error codes surfaced to the Agent."""

    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_FAILED = "AUTH_FAILED"
    READ_ONLY = "READ_ONLY"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    ANCHOR_NOT_FOUND = "ANCHOR_NOT_FOUND"
    ANCHOR_AMBIGUOUS = "ANCHOR_AMBIGUOUS"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    UNSUPPORTED = "UNSUPPORTED"
    FILE_SOURCE_ERROR = "FILE_SOURCE_ERROR"
    TIMEOUT = "TIMEOUT"


class HaxcmsMcpError(Exception):
    """The single error type raised by services and translated by the error middleware."""

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        *,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = ErrorCode(code)
        self.message = message
        self.hint = hint
        self.details = details
        super().__init__(self.formatted)

    @property
    def formatted(self) -> str:
        """Render as the MCP message format ``[CODE] message. hint``."""
        text = f"[{self.code.value}] {self.message}"
        if self.hint:
            text = f"{text}. {self.hint}"
        return text

    def __str__(self) -> str:
        return self.formatted
