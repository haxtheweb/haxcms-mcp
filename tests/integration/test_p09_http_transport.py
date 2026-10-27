"""T9.4/T9.5 companion: the server works as a real subprocess over the HTTP transport.

Spawns `python -m haxcms_mcp --transport http` against the live runtime (the
HttpMcpProcess harness) and drives it with a fastmcp streamable-HTTP Client: the full
registry lists, read-only calls answer, and a write round trip (create + archive) proves
auth, budget and error handling all survive the transport boundary.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import httpx
import pytest
from fastmcp import Client

from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_process import HttpMcpProcess, server_env

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
async def http_server(
    haxcms: HaxcmsRuntime, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[HttpMcpProcess]:
    """One spawned HTTP-mode server shared by the tests in this module."""
    tmp = tmp_path_factory.mktemp("p09-http")
    env = server_env(
        haxcms.base_url,
        haxcms.username,
        haxcms.password,
        HAXCMS_MCP_OUTPUT_DIR=str(tmp / "output"),
    )
    async with HttpMcpProcess(env, log_dir=tmp) as proc:
        yield proc


async def test_full_registry_lists_over_http(http_server: HttpMcpProcess) -> None:
    async with Client(http_server.url) as client:
        tools = await client.list_tools()
        prompts = await client.list_prompts()
    assert len(tools) >= 100
    assert {prompt.name for prompt in prompts} >= {"hax_author", "build_page_from_brief"}


async def test_read_only_calls_over_http(http_server: HttpMcpProcess) -> None:
    async with Client(http_server.url) as client:
        me = await client.call_tool("whoami", {})
        sites = await client.call_tool("list_sites", {})
    assert me.data["authenticated"] is True
    assert me.data["read_only"] is False
    assert isinstance(sites.data["sites"], list)


async def test_write_round_trip_over_http(http_server: HttpMcpProcess) -> None:
    name = f"p09-http-{secrets.token_hex(3)}"
    async with Client(http_server.url) as client:
        created = await client.call_tool("create_site", {"name": name})
        assert created.data["name"] == name
        try:
            outline = await client.call_tool("get_outline", {"site": name})
            assert outline.data["site"] == name
        finally:
            archived = await client.call_tool("archive_site", {"site": name})
            assert archived.data["name"] == name


async def test_dns_rebinding_is_refused_on_the_loopback_server(http_server: HttpMcpProcess) -> None:
    """Security audit: a browser page that rebinds its name to 127.0.0.1 sends a foreign Host
    (and Origin); the server must refuse it before any tool can run with the operator's
    credentials."""
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
    port = http_server.url.split(":")[2].split("/")[0]
    async with httpx.AsyncClient(timeout=30) as http:
        rebound = await http.post(
            http_server.url,
            json=initialize,
            headers={**headers, "Host": f"attacker.example:{port}"},
        )
        cross_origin = await http.post(
            http_server.url,
            json=initialize,
            headers={**headers, "Origin": "http://attacker.example"},
        )
    assert rebound.status_code == 421
    assert cross_origin.status_code == 403
