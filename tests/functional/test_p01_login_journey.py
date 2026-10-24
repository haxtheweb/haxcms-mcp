"""Functional user stories for the session tools (PLAN Phase 1).

"As a new user I click Login" — expressed only through Tool calls against the live instance.
"""

from __future__ import annotations

import pytest

from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.functional


async def test_login_journey(mcp: McpTestClient, haxcms: HaxcmsRuntime) -> None:
    # start logged out, like a fresh server with no env credentials
    await mcp.call("logout")
    error = await mcp.call_error("whoami")
    assert error.startswith("[AUTH_REQUIRED]"), error

    # the user logs in and sees who they are
    result = await mcp.call("login", username=haxcms.username, password=haxcms.password)
    assert result["user"] == haxcms.username
    assert result["expires_in_s"] == 15 * 60

    me = await mcp.call("whoami")
    assert me["authenticated"] is True
    assert me["user"] == haxcms.username
    assert me["token_age_s"] is not None and me["token_age_s"] < 60

    # and can log out again
    assert await mcp.call("logout") == {"status": "loggedout"}
    error = await mcp.call_error("whoami")
    assert error.startswith("[AUTH_REQUIRED]"), error


async def test_whoami_with_env_credentials_needs_no_login(
    mcp: McpTestClient, haxcms: HaxcmsRuntime
) -> None:
    # the mcp fixture's server was built with the runtime credentials configured
    me = await mcp.call("whoami")
    assert me["authenticated"] is True
    assert me["user"] == haxcms.username
    assert me["default_site"] is None
    assert set(me["budget"]) == {"tokens", "waits", "denials"}


async def test_read_only_mode_blocks_writes_but_allows_whoami(
    haxcms: HaxcmsRuntime,
) -> None:
    # Read-Only Mode: login/logout are writes to server state and must be blocked; whoami stays.
    from fastmcp import Client

    from haxcms_mcp.config import Settings
    from haxcms_mcp.server import build_server
    from tests.harness.mcp_client import McpTestClient as Wrapper

    settings = Settings(
        base_url=haxcms.base_url,
        username=haxcms.username,
        password=haxcms.password,
        read_only=True,
    )
    server = build_server(settings)
    async with Client(server) as inner:
        ro_mcp = Wrapper(server, inner)
        error = await ro_mcp.call_error("login", username=haxcms.username, password="x")
        assert error.startswith("[READ_ONLY]"), error
        me = await ro_mcp.call("whoami")
        assert me["read_only"] is True
