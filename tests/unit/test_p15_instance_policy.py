"""Phase 0 (haxtheweb/issues#3140): the server obeys the instance's published MCP policy."""

from __future__ import annotations

from typing import Any

import httpx
import mcp_types
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.policy import POLICY_TTL_S, PolicyChecker, parse_policy
from haxcms_mcp.server import build_server

pytestmark = pytest.mark.unit

BASE = "http://haxcms.invalid"
DISCOVERY = "/system/api/v1"


def discovery(mcp: dict[str, Any] | None) -> httpx.Response:
    data: dict[str, Any] = {"name": "HAXcms System API"}
    if mcp is not None:
        data["mcp"] = mcp
    return httpx.Response(200, json={"status": 200, "data": data})


def add_tools(mcp: FastMCP) -> None:
    @mcp.tool(annotations=mcp_types.ToolAnnotations(title="w", read_only_hint=False))
    async def fake_write(x: int) -> int:
        return x + 1

    @mcp.tool(annotations=mcp_types.ToolAnnotations(title="r", read_only_hint=True))
    async def fake_read() -> str:
        return "ok"


# --- parsing --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mcp", "enabled", "read_only"),
    [
        ({"enabled": True, "readOnly": False}, True, False),
        ({"enabled": True, "readOnly": True}, True, True),
        ({"enabled": True}, True, True),  # read-only unless explicitly false
        ({"enabled": False, "readOnly": False}, False, True),  # off is always read-only
        ({"enabled": "true", "readOnly": False}, False, True),  # only a real true enables
        ({}, False, True),
    ],
)
def test_parse_policy_fails_safe(mcp: dict[str, Any], enabled: bool, read_only: bool) -> None:
    policy = parse_policy({"status": 200, "data": {"mcp": mcp}})
    assert policy.state == "published"
    assert (policy.enabled, policy.read_only) == (enabled, read_only)


def test_an_instance_without_the_field_publishes_no_policy() -> None:
    policy = parse_policy({"status": 200, "data": {"name": "HAXcms System API"}})
    assert policy.state == "unpublished"
    assert not policy.disabled and not policy.forces_read_only


# --- checker ----------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def test_checker_caches_a_verdict_but_retries_an_outage() -> None:
    clock = Clock()
    async with HaxcmsClient(Settings(base_url=BASE)) as client:
        checker = PolicyChecker(client, clock=clock)
        with respx.mock(base_url=BASE) as router:
            route = router.get(DISCOVERY)
            route.side_effect = [
                httpx.ConnectError("down"),
                discovery({"enabled": True, "readOnly": False}),
                discovery({"enabled": False}),
            ]
            assert (await checker.current()).state == "unavailable"
            assert (await checker.current()).enabled is True  # outage not cached
            assert (await checker.current()).enabled is True  # verdict cached
            assert route.call_count == 2
            clock.now += POLICY_TTL_S + 1
            assert (await checker.current()).disabled is True  # config change picked up


async def test_policy_probe_never_retries() -> None:
    async with HaxcmsClient(Settings(base_url=BASE)) as client:
        with respx.mock(base_url=BASE) as router:
            route = router.get(DISCOVERY).mock(side_effect=httpx.ConnectError("down"))
            assert (await PolicyChecker(client).current()).state == "unavailable"
            assert route.call_count == 1


# --- enforcement through the real server --------------------------------------------------


async def test_mcp_disabled_refuses_every_tool_but_server_info() -> None:
    mcp = build_server(Settings(base_url=BASE))
    add_tools(mcp)
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.get(DISCOVERY).mock(return_value=discovery({"enabled": False}))
        router.route().mock(return_value=httpx.Response(503))  # anything else: unhealthy
        async with Client(mcp) as client:
            for name in ("fake_read", "fake_write"):
                args = {"x": 1} if name == "fake_write" else {}
                with pytest.raises(ToolError, match="MCP_DISABLED"):
                    await client.call_tool(name, args)
            info = (await client.call_tool("get_server_info", {})).data
    assert info["instance_mcp_policy"] == {
        "state": "published",
        "enabled": False,
        "read_only": True,
    }


async def test_instance_read_only_forces_read_only_mode() -> None:
    mcp = build_server(Settings(base_url=BASE, read_only=False))
    add_tools(mcp)
    with respx.mock(base_url=BASE) as router:
        router.get(DISCOVERY).mock(return_value=discovery({"enabled": True, "readOnly": True}))
        async with Client(mcp) as client:
            assert (await client.call_tool("fake_read", {})).data == "ok"
            with pytest.raises(ToolError) as excinfo:
                await client.call_tool("fake_write", {"x": 1})
    assert "[READ_ONLY]" in str(excinfo.value)
    assert "config.mcp.readOnly" in str(excinfo.value)


async def test_instance_read_write_allows_writes() -> None:
    mcp = build_server(Settings(base_url=BASE))
    add_tools(mcp)
    with respx.mock(base_url=BASE) as router:
        router.get(DISCOVERY).mock(return_value=discovery({"enabled": True, "readOnly": False}))
        async with Client(mcp) as client:
            assert (await client.call_tool("fake_write", {"x": 1})).data == 2


async def test_local_read_only_still_wins_over_a_permissive_instance() -> None:
    mcp = build_server(Settings(base_url=BASE, read_only=True))
    add_tools(mcp)
    with respx.mock(base_url=BASE) as router:
        router.get(DISCOVERY).mock(return_value=discovery({"enabled": True, "readOnly": False}))
        async with Client(mcp) as client:
            with pytest.raises(ToolError, match="HAXCMS_MCP_READ_ONLY"):
                await client.call_tool("fake_write", {"x": 1})


async def test_an_older_haxcms_without_a_policy_falls_back_to_local_settings() -> None:
    mcp = build_server(Settings(base_url=BASE))
    add_tools(mcp)
    with respx.mock(base_url=BASE) as router:
        router.get(DISCOVERY).mock(return_value=discovery(None))
        async with Client(mcp) as client:
            assert (await client.call_tool("fake_write", {"x": 1})).data == 2


async def test_every_request_identifies_the_server_as_an_agent() -> None:
    """HAXcms commit attribution (haxtheweb/issues#3191): X-HAX-Actor: agent."""
    async with HaxcmsClient(Settings(base_url=BASE, no_auth=True)) as client:
        with respx.mock(base_url=BASE) as router:
            route = router.get("/system/api/v1/sites").mock(
                return_value=httpx.Response(200, json={"status": 200, "data": []})
            )
            await client.request("GET", client.sys("sites"))
    assert route.calls.last.request.headers["x-hax-actor"] == "agent"
