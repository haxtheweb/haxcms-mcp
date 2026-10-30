"""Phase 0 (haxtheweb/issues#3140) against a live HAXcms: the instance publishes its MCP
policy on GET /system/api/v1, and this server obeys it.

The session runtime runs read-write (the harness default). Read-only and disabled
instances get a dedicated runtime each, with their own config.mcp.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastmcp import Client

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server
from tests.conftest import test_backend as selected_backend
from tests.harness.haxcms_php_runtime import HaxcmsPhpRuntime
from tests.harness.haxcms_runtime import HaxcmsRuntime

pytestmark = pytest.mark.integration


async def published_policy(runtime: HaxcmsRuntime) -> dict[str, Any] | None:
    async with httpx.AsyncClient(base_url=runtime.base_url, timeout=30) as http:
        body = (await http.get("/system/api/v1")).json()
    data = body.get("data") if isinstance(body, dict) else None
    policy = data.get("mcp") if isinstance(data, dict) else None
    return policy if isinstance(policy, dict) else None


def require_policy_support(policy: dict[str, Any] | None) -> None:
    if policy is None:
        pytest.skip("this HAXcms checkout does not publish data.mcp yet (needs Phase 0 upstream)")


def settings_for(runtime: HaxcmsRuntime) -> Settings:
    return Settings(base_url=runtime.base_url, username=runtime.username, password=runtime.password)


async def boot(policy: dict[str, Any]) -> HaxcmsRuntime:
    runtime_class = HaxcmsPhpRuntime if selected_backend() == "php" else HaxcmsRuntime
    runtime = runtime_class(mcp_policy=policy)
    return await runtime.__aenter__()


@pytest.fixture(scope="module")
async def read_only_instance() -> AsyncIterator[HaxcmsRuntime]:
    runtime = await boot({"enabled": True, "readOnly": True})
    try:
        yield runtime
    finally:
        await runtime.__aexit__(None, None, None)


@pytest.fixture(scope="module")
async def disabled_instance() -> AsyncIterator[HaxcmsRuntime]:
    runtime = await boot({"enabled": False, "readOnly": False})
    try:
        yield runtime
    finally:
        await runtime.__aexit__(None, None, None)


async def test_the_instance_publishes_its_policy(haxcms: HaxcmsRuntime) -> None:
    policy = await published_policy(haxcms)
    require_policy_support(policy)
    assert policy == {"enabled": True, "readOnly": False}


async def test_a_read_write_instance_allows_writes(haxcms: HaxcmsRuntime) -> None:
    require_policy_support(await published_policy(haxcms))
    name = f"p15-rw-{secrets.token_hex(3)}"
    async with Client(build_server(settings_for(haxcms))) as client:
        info = (await client.call_tool("get_server_info", {})).data
        assert info["instance_mcp_policy"] == {
            "state": "published",
            "enabled": True,
            "read_only": False,
        }
        created = await client.call_tool("create_site", {"name": name})
        assert created.data["name"] == name
        await client.call_tool("archive_site", {"site": name})


async def test_a_read_only_instance_refuses_writes(read_only_instance: HaxcmsRuntime) -> None:
    require_policy_support(await published_policy(read_only_instance))
    async with Client(build_server(settings_for(read_only_instance))) as client:
        sites = (await client.call_tool("list_sites", {})).data
        assert isinstance(sites["sites"], list)
        result = await client.call_tool(
            "create_site", {"name": f"p15-ro-{secrets.token_hex(3)}"}, raise_on_error=False
        )
    assert result.is_error
    text = result.content[0].text  # type: ignore[union-attr]
    assert "[READ_ONLY]" in text and "config.mcp.readOnly" in text


async def test_a_disabled_instance_refuses_everything_but_server_info(
    disabled_instance: HaxcmsRuntime,
) -> None:
    policy = await published_policy(disabled_instance)
    require_policy_support(policy)
    # disabled forces read-only too, whatever the config says
    assert policy == {"enabled": False, "readOnly": True}
    async with Client(build_server(settings_for(disabled_instance))) as client:
        for tool, args in (("list_sites", {}), ("whoami", {})):
            result = await client.call_tool(tool, args, raise_on_error=False)
            assert result.is_error, tool
            assert "[MCP_DISABLED]" in result.content[0].text  # type: ignore[union-attr]
        info = (await client.call_tool("get_server_info", {})).data
    assert info["instance_mcp_policy"]["enabled"] is False
