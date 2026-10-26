"""#3137: `get_server_info` reports whether the live instance serves the vendored spec."""

from __future__ import annotations

import os

import pytest

from haxcms_mcp.generated import spec_info
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration


async def test_get_server_info_reports_spec_compatibility(mcp: McpTestClient) -> None:
    info = await mcp.call("get_server_info")
    compat = info["spec_compatibility"]
    assert compat["status"] in {"match", "mismatch"}  # the instance is reachable and serves a spec
    assert compat["expected_sha256"] == spec_info.SYSTEM_SPEC_SHA256
    assert compat["actual_sha256"]
    assert compat["vendored_ref"].startswith("HAXcms NodeJS ")


@pytest.mark.skipif(
    not os.environ.get("HAXCMS_MCP_TEST_HAXCMS_DIR"),
    reason="needs HAXCMS_MCP_TEST_HAXCMS_DIR pointing at the HAXcms the specs were synced from",
)
async def test_vendored_specs_match_the_checkout_under_test(mcp: McpTestClient) -> None:
    """When the live suite runs against a checkout, the vendored specs must equal it."""
    info = await mcp.call("get_server_info")
    assert info["spec_compatibility"]["status"] == "match", info["spec_compatibility"]
