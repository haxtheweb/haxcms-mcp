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
from tests.harness.haxcms_php_runtime import HaxcmsPhpRuntime
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

# NOTE: the --snapshot-update flag comes from the syrupy pytest plugin (installed);
# tests/harness/snapshots.py reuses it for the plain-JSON snapshots.


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `network`-marked tests unless HAXCMS_MCP_TEST_NETWORK=1 (PLAN §6.1)."""
    _skip_php_parity_gaps(items)
    if os.environ.get("HAXCMS_MCP_TEST_NETWORK", "").lower() in {"1", "true", "yes"}:
        return
    skip_network = pytest.mark.skip(reason="needs HAXCMS_MCP_TEST_NETWORK=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)


# Live tests whose expectations encode HAXcms NodeJS behavior that the PHP backend implements
# differently (upstream parity gaps, not MCP defects). Skipped only under
# HAXCMS_MCP_TEST_BACKEND=php; each entry is a node-id prefix with the reason (#3139).
PHP_PARITY_GAPS: dict[str, str] = {
    "tests/integration/test_p00_harness.py::test_boot_and_disk_layout": (
        "asserts the NodeJS runtime's _config layout"
    ),
    "tests/integration/test_p01_live_auth.py::test_repeated_wrong_passwords_are_rate_limited": (
        "PHP has no login rate limiter (12 wrong logins all answer 401)"
    ),
    "tests/integration/test_p04_content_roundtrip.py::test_sanitisation_rewrites_are_exactly_the_documented_ones": (  # noqa: E501
        "golden of the NodeJS saveNode sanitiser; PHP stores these attributes as sent"
    ),
    "tests/integration/test_p04_typed_blocks_live.py": (
        "stored forms asserted per the NodeJS sanitiser golden"
    ),
    "tests/functional/test_p04_rebuild_tutorial_page.py": (
        "asserts the NodeJS sanitiser's link rewrite"
    ),
    "tests/integration/test_p05_files.py::test_file_lifecycle": (
        "PHP file responses carry no uuid"
    ),
    "tests/integration/test_p06_git.py::test_git_only_body_hits_the_form_token_wall": (
        "PHP words the token refusal differently"
    ),
    "tests/integration/test_p07_converters.py": (
        "converter output (markdown, pretty-print, pdf, pptx, xlsx) differs between backends"
    ),
    "tests/integration/test_p07_create_site_from_document.py": (
        "docx import output differs between backends"
    ),
    "tests/integration/test_p07_import_document.py::test_docx_method_branch_attaches_flat_pages_under_a_parent": (  # noqa: E501
        "docx import output differs between backends"
    ),
    "tests/integration/test_p07_import_document.py::test_docx_method_page_wraps_everything_into_one_page": (  # noqa: E501
        "docx import output differs between backends"
    ),
}


def _skip_php_parity_gaps(items: list[pytest.Item]) -> None:
    if os.environ.get("HAXCMS_MCP_TEST_BACKEND", "node").strip().lower() != "php":
        return
    for item in items:
        for prefix, reason in PHP_PARITY_GAPS.items():
            if item.nodeid.startswith(prefix):
                item.add_marker(pytest.mark.skip(reason=f"HAXcms PHP parity gap: {reason}"))
                break


def test_backend() -> str:
    """Which HAXcms backend the live suites run against: `node` (default) or `php` (#3139)."""
    backend = os.environ.get("HAXCMS_MCP_TEST_BACKEND", "node").strip().lower()
    if backend not in {"node", "php"}:
        raise pytest.UsageError(f"HAXCMS_MCP_TEST_BACKEND must be node or php, got {backend!r}")
    return backend


@pytest.fixture(scope="session")
async def haxcms() -> AsyncIterator[HaxcmsRuntime]:
    """One real HAXcms instance (NodeJS by default, PHP with HAXCMS_MCP_TEST_BACKEND=php)."""
    runtime_class = HaxcmsPhpRuntime if test_backend() == "php" else HaxcmsRuntime
    async with runtime_class() as runtime:
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
