"""Shared pytest fixtures (PLAN.md Section 6.2).

Phase 0 provides: `haxcms` (session-scoped live instance), `settings` (per test, pointing at the
runtime with credentials), `mcp` (FastMCP app + in-memory client). Phase 1 adds `client` (a
logged-in HaxcmsClient). Phase 3 adds `site` (a throwaway `mcp-t-<8 hex>` site per test,
archived on teardown) and `page` (a fresh page in `site`).
"""

from __future__ import annotations

import contextlib
import os
import secrets
from collections.abc import AsyncIterator

import pytest
from fastmcp import Client

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import HaxcmsMcpError
from haxcms_mcp.models.item import Item
from haxcms_mcp.server import build_server
from haxcms_mcp.services import pages as pages_service
from haxcms_mcp.services import sites as sites_service
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

# NOTE: the --snapshot-update flag comes from the syrupy pytest plugin (installed);
# tests/harness/snapshots.py reuses it for the plain-JSON snapshots.


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `network`-marked tests unless HAXCMS_MCP_TEST_NETWORK=1 (PLAN §6.1)."""
    if os.environ.get("HAXCMS_MCP_TEST_NETWORK", "").lower() in {"1", "true", "yes"}:
        return
    skip_network = pytest.mark.skip(reason="needs HAXCMS_MCP_TEST_NETWORK=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)


@pytest.fixture(scope="session")
async def haxcms() -> AsyncIterator[HaxcmsRuntime]:
    """One real HAXcms NodeJS instance for the whole test session."""
    async with HaxcmsRuntime() as runtime:
        yield runtime


@pytest.fixture
def settings(haxcms: HaxcmsRuntime) -> Settings:
    """Per-test Settings pointing at the live runtime with its credentials."""
    return Settings(
        base_url=haxcms.base_url,
        username=haxcms.username,
        password=haxcms.password,
    )


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[HaxcmsClient]:
    """A HaxcmsClient pointed at the live runtime, logged in (PLAN §6.2)."""
    async with HaxcmsClient(settings) as haxcms_client:
        await haxcms_client.auth.ensure_access()
        yield haxcms_client


@pytest.fixture
async def mcp(settings: Settings) -> AsyncIterator[McpTestClient]:
    """Fresh FastMCP app plus in-memory client for one test."""
    server = build_server(settings)
    async with Client(server) as client:
        yield McpTestClient(server, client)


@pytest.fixture
async def site(client: HaxcmsClient) -> AsyncIterator[str]:
    """A throwaway live site (`mcp-t-<8 hex>`, clean-one), archived on teardown (PLAN §6.2)."""
    detail = await sites_service.create_site(client, f"mcp-t-{secrets.token_hex(4)}")
    try:
        yield detail.name
    finally:
        with contextlib.suppress(HaxcmsMcpError):
            await sites_service.archive_site(client, detail.name)


@pytest.fixture
async def page(client: HaxcmsClient, site: str) -> AsyncIterator[Item]:
    """A fresh page in `site` (the site fixture archives it away afterwards)."""
    yield await pages_service.create_page(client, site, "Test Page")
