"""Security audit small items: short download links, login tool warning."""

from __future__ import annotations

import pytest
from fastmcp import Client

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server

pytestmark = pytest.mark.unit

BASE = "http://haxcms.invalid"


def test_download_links_are_short_lived_by_default() -> None:
    assert Settings(base_url=BASE).download_ttl_s == 300


async def test_login_tool_is_closed_world_and_warns_about_the_password() -> None:
    mcp = build_server(Settings(base_url=BASE))
    async with Client(mcp) as client:
        login = next(tool for tool in await client.list_tools() if tool.name == "login")
    assert login.annotations is not None
    assert login.annotations.open_world_hint is False
    assert login.annotations.read_only_hint is False
    assert "password travels as a tool argument" in (login.description or "")
