"""CLI entry point for the HAXcms MCP server.

Usage:
    haxcms-mcp                                        # stdio transport (default)
    haxcms-mcp --transport http --host 127.0.0.1 --port 8765 --path /mcp

All logging goes to stderr; stdout belongs to the stdio transport.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from haxcms_mcp import __version__
from haxcms_mcp.config import Settings
from haxcms_mcp.logging import configure_logging
from haxcms_mcp.server import build_server


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="haxcms-mcp",
        description="MCP server that operates a self-hosted HAXcms NodeJS instance.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=None,
        help="MCP transport (default: HAXCMS_MCP_TRANSPORT or stdio)",
    )
    parser.add_argument("--host", default=None, help="HTTP transport bind host")
    parser.add_argument("--port", type=int, default=None, help="HTTP transport bind port")
    parser.add_argument("--path", default=None, help="HTTP transport endpoint path")
    parser.add_argument(
        "--log-level",
        default=None,
        help="stderr log level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument("--version", action="version", version=f"haxcms-mcp {__version__}")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build settings, configure logging, and run the server. Returns a process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    overrides: dict[str, object] = {}
    if args.transport is not None:
        overrides["transport"] = args.transport
    if args.host is not None:
        overrides["http_host"] = args.host
    if args.port is not None:
        overrides["http_port"] = args.port
    if args.path is not None:
        overrides["http_path"] = args.path
    if args.log_level is not None:
        overrides["log_level"] = args.log_level

    try:
        settings = Settings(**overrides)  # type: ignore[arg-type]
    except Exception as exc:  # pydantic ValidationError and friends
        print(f"haxcms-mcp: configuration error: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level)
    mcp = build_server(settings)

    if settings.transport == "http":
        mcp.run(
            transport="http",
            host=settings.http_host,
            port=settings.http_port,
            path=settings.http_path,
        )
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
