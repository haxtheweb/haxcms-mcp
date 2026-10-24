"""Logging configuration for the HAXcms MCP server.

All logging goes to stderr only; stdout is reserved for the stdio transport (PLAN.md Section 2.5).
Never log tokens or passwords. Outbound requests are logged at DEBUG as ``METHOD path status ms``.
"""

from __future__ import annotations

import logging
import sys

ROOT_LOGGER_NAME = "haxcms_mcp"

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


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
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)


def get_logger(module: str) -> logging.Logger:
    """Return a child logger named ``haxcms_mcp.<module>``."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{module}")
