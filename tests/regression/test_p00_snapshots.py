"""Phase 0 regression snapshots: the tool-schema registry (PLAN §6.4)."""

from __future__ import annotations

import pytest

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server
from tests.harness.snapshots import assert_or_update_snapshot, collect_tool_schemas

pytestmark = pytest.mark.regression


async def test_tool_schemas(request: pytest.FixtureRequest) -> None:
    settings = Settings(base_url="http://snapshot.invalid")
    server = build_server(settings)
    schemas = await collect_tool_schemas(server)
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("tool_schemas", schemas, update=update)
