"""Phase 9 regression snapshots: the rendered text of all four prompts (PLAN T9.1).

The prompts are pure text, so the golden captures every rendered prompt in full — any
wording change to journeys.py shows up here as a deliberate, reviewed diff.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server
from tests.harness.prompt_samples import PROMPT_NAMES, render_args
from tests.harness.snapshots import assert_or_update_snapshot

pytestmark = pytest.mark.regression


async def test_prompt_texts(request: pytest.FixtureRequest) -> None:
    server = build_server(Settings(base_url="http://snapshot.invalid"))
    texts: dict[str, str] = {}
    async with Client(server) as client:
        for name in PROMPT_NAMES:
            result = await client.get_prompt(name, render_args(name))
            texts[name] = result.messages[0].content.text
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("prompt_texts", texts, update=update)
