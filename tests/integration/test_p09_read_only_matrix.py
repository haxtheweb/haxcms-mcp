"""T9.4: HAXCMS_MCP_READ_ONLY must block EVERY non-read-only tool.

The whole-registry parametrised test the PLAN asks for: the write set is derived from the
live registry's annotations (never a hand-kept list), and each of those tools is called
with EMPTY arguments against a read-only server pointed at the live runtime. The refusal
must still be [READ_ONLY] — proving the gate fires ahead of argument validation and ahead
of any HTTP, so no blocked call can ever reach the instance. Read-only tools pass through
and work against the live instance.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server
from tests.harness.haxcms_runtime import HaxcmsRuntime

pytestmark = pytest.mark.integration


def _registry_flags() -> dict[str, bool]:
    """name -> read_only_hint for every registered tool (offline; annotations only)."""
    server = build_server(Settings(base_url="http://registry.invalid"))
    tools = asyncio.run(server.list_tools())
    return {tool.name: bool(tool.annotations and tool.annotations.read_only_hint) for tool in tools}


FLAGS = _registry_flags()
WRITE_TOOLS = sorted(name for name, read_only in FLAGS.items() if not read_only)
READ_TOOLS = sorted(name for name, read_only in FLAGS.items() if read_only)


@pytest.fixture(scope="module")
async def ro_client(haxcms: HaxcmsRuntime) -> AsyncIterator[Client]:
    """One read-only server + connection shared by the whole matrix."""
    settings = Settings(
        base_url=haxcms.base_url,
        username=haxcms.username,
        password=haxcms.password,
        read_only=True,
    )
    server = build_server(settings)
    async with Client(server) as client:
        yield client


def test_registry_partition_is_complete() -> None:
    assert len(FLAGS) >= 100, "registry should hold every phase's tools"
    assert len(WRITE_TOOLS) + len(READ_TOOLS) == len(FLAGS)
    # spot-check both sides of the partition against known annotations
    assert {"create_site", "add_paragraph", "delete_page", "export_site"} <= set(WRITE_TOOLS)
    assert {"whoami", "list_sites", "get_outline", "get_page_blocks"} <= set(READ_TOOLS)


@pytest.mark.parametrize("tool_name", WRITE_TOOLS)
async def test_every_write_tool_is_refused(tool_name: str, ro_client: Client) -> None:
    with pytest.raises(ToolError) as excinfo:
        await ro_client.call_tool(tool_name, {})
    message = str(excinfo.value)
    assert message.startswith("[READ_ONLY]"), message
    assert tool_name in message


async def test_read_only_tools_pass_the_gate(ro_client: Client) -> None:
    result = await ro_client.call_tool("whoami", {})
    assert result.data["read_only"] is True
    assert result.data["authenticated"] is True

    sites = await ro_client.call_tool("list_sites", {})
    assert isinstance(sites.data["sites"], list)
