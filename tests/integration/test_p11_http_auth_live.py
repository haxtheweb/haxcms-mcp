"""#3140: the authenticated HTTP transport against a live HAXcms.

A spawned `haxcms-mcp --transport http` with `HAXCMS_MCP_HTTP_AUTH=haxcms` and NO environment
credentials: unauthenticated and forged requests are rejected before any tool runs, a caller
with a real HAXcms access token acts as that HAXcms user, per-connection sessions do not leak
into each other's caches, and Read-Only Mode is still enforced for authenticated callers.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.exceptions import ToolError

from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_process import HttpMcpProcess, server_env

pytestmark = pytest.mark.integration


async def haxcms_token(haxcms: HaxcmsRuntime) -> str:
    """A HAXcms access token obtained the way a browser does (what the OAuth flow will mint)."""
    async with httpx.AsyncClient(base_url=haxcms.base_url, timeout=30) as http:
        response = await http.post(
            "/system/api/v1/session/login",
            json={"username": haxcms.username, "password": haxcms.password},
        )
    response.raise_for_status()
    jwt = response.json()["jwt"]
    assert isinstance(jwt, str) and jwt
    return jwt


async def _spawn(
    haxcms: HaxcmsRuntime, tmp_path_factory: pytest.TempPathFactory, name: str, **extra: str
) -> HttpMcpProcess:
    tmp = tmp_path_factory.mktemp(name)
    env = server_env(
        haxcms.base_url,
        HAXCMS_MCP_HTTP_AUTH="haxcms",
        HAXCMS_MCP_OUTPUT_DIR=str(tmp / "output"),
        **extra,
    )
    # never inherit credentials: the caller's token must be the only identity
    env.pop("HAXCMS_MCP_USERNAME", None)
    env.pop("HAXCMS_MCP_PASSWORD", None)
    return await HttpMcpProcess(env, log_dir=tmp).start()


@pytest.fixture(scope="module")
async def auth_server(
    haxcms: HaxcmsRuntime, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[HttpMcpProcess]:
    proc = await _spawn(haxcms, tmp_path_factory, "p11-auth")
    try:
        yield proc
    finally:
        await proc.stop()


@pytest.fixture(scope="module")
async def read_only_server(
    haxcms: HaxcmsRuntime, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[HttpMcpProcess]:
    proc = await _spawn(haxcms, tmp_path_factory, "p11-ro", HAXCMS_MCP_READ_ONLY="true")
    try:
        yield proc
    finally:
        await proc.stop()


async def test_unauthenticated_requests_are_rejected(auth_server: HttpMcpProcess) -> None:
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0"},
        },
    }
    headers = {"Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(timeout=30) as http:
        anonymous = await http.post(auth_server.url, json=initialize, headers=headers)
        forged = await http.post(
            auth_server.url,
            json=initialize,
            headers={**headers, "Authorization": "Bearer not-a-haxcms-token"},
        )
    assert anonymous.status_code == 401
    assert "resource_metadata" in anonymous.headers.get("www-authenticate", "")
    assert forged.status_code == 401


async def test_protected_resource_metadata_points_at_haxcms(
    auth_server: HttpMcpProcess, haxcms: HaxcmsRuntime
) -> None:
    origin = auth_server.url.rsplit("/", 1)[0]
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(f"{origin}/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200, response.text
    metadata = response.json()
    assert [s.rstrip("/") for s in metadata["authorization_servers"]] == [haxcms.base_url]


async def test_a_valid_haxcms_token_acts_as_that_user(
    auth_server: HttpMcpProcess, haxcms: HaxcmsRuntime
) -> None:
    token = await haxcms_token(haxcms)
    async with Client(auth_server.url, auth=BearerAuth(token)) as client:
        me = await client.call_tool("whoami", {})
        sites = await client.call_tool("list_sites", {})
    assert me.data["authenticated"] is True
    assert me.data["user"] == haxcms.username
    assert me.data["per_caller_auth"] is True
    assert isinstance(sites.data["sites"], list)


async def test_write_round_trip_with_a_caller_token(
    auth_server: HttpMcpProcess, haxcms: HaxcmsRuntime
) -> None:
    """Writes need the caller's User/Site Tokens, which the server fetches with THEIR bearer."""
    token = await haxcms_token(haxcms)
    name = f"p11-auth-{secrets.token_hex(3)}"
    async with Client(auth_server.url, auth=BearerAuth(token)) as client:
        created = await client.call_tool("create_site", {"name": name})
        assert created.data["name"] == name
        try:
            page = await client.call_tool("create_page", {"site": name, "title": "From OAuth"})
            assert page.data["title"] == "From OAuth"
        finally:
            await client.call_tool("archive_site", {"site": name})


async def test_login_and_logout_tools_are_refused(
    auth_server: HttpMcpProcess, haxcms: HaxcmsRuntime
) -> None:
    token = await haxcms_token(haxcms)
    async with Client(auth_server.url, auth=BearerAuth(token)) as client:
        with pytest.raises(ToolError, match="UNSUPPORTED"):
            await client.call_tool(
                "login", {"username": haxcms.username, "password": haxcms.password}
            )
        with pytest.raises(ToolError, match="UNSUPPORTED"):
            await client.call_tool("logout", {})
        # and the connection still works: logout did not touch anything
        me = await client.call_tool("whoami", {})
    assert me.data["user"] == haxcms.username


async def test_two_connections_with_different_tokens_work_side_by_side(
    auth_server: HttpMcpProcess, haxcms: HaxcmsRuntime
) -> None:
    """Each token gets its own session (isolation itself is unit-tested in test_p11_*)."""
    first = await haxcms_token(haxcms)
    second = await haxcms_token(haxcms)
    async with (
        Client(auth_server.url, auth=BearerAuth(first)) as one,
        Client(auth_server.url, auth=BearerAuth(second)) as two,
    ):
        assert (await one.call_tool("whoami", {})).data["authenticated"] is True
        assert (await two.call_tool("whoami", {})).data["authenticated"] is True
        assert (await one.call_tool("list_sites", {})).data["sites"] is not None


async def test_read_only_mode_still_applies_to_authenticated_callers(
    read_only_server: HttpMcpProcess, haxcms: HaxcmsRuntime
) -> None:
    token = await haxcms_token(haxcms)
    async with Client(read_only_server.url, auth=BearerAuth(token)) as client:
        me = await client.call_tool("whoami", {})
        assert me.data["read_only"] is True
        with pytest.raises(ToolError, match="READ_ONLY"):
            await client.call_tool("create_site", {"name": f"p11-ro-{secrets.token_hex(3)}"})
