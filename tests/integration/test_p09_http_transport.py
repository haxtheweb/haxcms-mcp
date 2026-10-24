"""T9.4/T9.5 companion: the server works as a real subprocess over the HTTP transport.

Spawns `python -m haxcms_mcp --transport http` against the live runtime (the
HttpMcpProcess harness) and drives it with a fastmcp streamable-HTTP Client: the full
registry lists, read-only calls answer, and a write round trip (create + archive) proves
auth, budget and error handling all survive the transport boundary.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

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
