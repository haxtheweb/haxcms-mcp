"""Shared helpers for tool modules (annotations, site addressing)."""

from __future__ import annotations

import mcp_types

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError


def tool_annotations(
    title: str,
    *,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = True,
    open_world: bool = False,
) -> mcp_types.ToolAnnotations:
    """Build ToolAnnotations with the project's hint defaults (PLAN §5)."""
    return mcp_types.ToolAnnotations(
        title=title,
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


def resolve_site(site: str | None, default_site: str | None) -> str:
    """Site addressing per PLAN §2.4: argument, else Default Site, else INVALID_ARGUMENT."""
    name = site or default_site
    if not name:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "site is required; set HAXCMS_MCP_DEFAULT_SITE or pass site",
        )
    return name.lower()
