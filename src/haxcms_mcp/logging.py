"""Logging configuration for the HAXcms MCP server.

All logging goes to stderr only; stdout is reserved for the stdio transport (PLAN.md Section 2.5).
Never log tokens or passwords. Outbound requests are logged at DEBUG as ``METHOD path status ms``.
"""

from __future__ import annotations

import logging
import re
import sys

ROOT_LOGGER_NAME = "haxcms_mcp"

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# C0 controls (CR and LF included) and DEL; tab is left alone
_CONTROL_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


class SingleLineFormatter(logging.Formatter):
    """Security: log messages carry caller-supplied text (usernames, tool names, upstream
    error text). Control characters in the message are written as `\\xNN`, so a value with
    a newline in it cannot forge a second log line. Tracebacks are appended after the
    message by `logging.Formatter.format` and keep their line breaks."""

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802 - stdlib name
        record.message = _CONTROL_RE.sub(
            lambda match: f"\\x{ord(match.group()):02x}", record.message
        )
        return super().formatMessage(record)


def configure_logging(level: str = "INFO") -> None:
    """Configure the ``haxcms_mcp`` logger tree to write to stderr.

    Idempotent: repeated calls replace the previously attached handler rather than
    duplicating output.
    """
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    resolved = getattr(logging, level.upper(), logging.INFO)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logger.setLevel(resolved)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(SingleLineFormatter(_FORMAT))
    logger.addHandler(handler)


def get_logger(module: str) -> logging.Logger:
    """Return a child logger named ``haxcms_mcp.<module>``."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{module}")
