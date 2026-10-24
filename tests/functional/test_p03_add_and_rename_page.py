"""Functional user story for the Phase 3 page tools (PLAN Appendix D tutorial).

"Add a New Page" / "Rename the Page" — expressed only through Tool calls against the live
instance: Add > Page creates "page" below Welcome, the details-panel rename regenerates the
slug under Pathauto, and the outline shows the renamed page in place, reachable by its new
slug.
"""

from __future__ import annotations

import contextlib
import secrets

import pytest

from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.functional

SITE = f"p3-rename-{secrets.token_hex(3)}"
NEW_TITLE = "A Designerly Engagement with the World"
NEW_SLUG = "a-designerly-engagement-with-the-world"


async def test_add_and_rename_page(mcp: McpTestClient) -> None:
    try:
        course = await mcp.call(
            "create_site", name=SITE, theme="clean-one", first_page_title="Welcome"
        )
        assert course["name"] == SITE

        # the tutorial's "Add > Page": a page titled "page" lands below Welcome
        added = await mcp.call("create_page", title="page", site=SITE)
        assert added["title"] == "page"
        assert added["slug"] == "page"

        outline = await mcp.call("get_outline", site=SITE)
        assert outline["count"] == 2
        assert [node["item"]["title"] for node in outline["outline"]] == ["Welcome", "page"]

        # "page details -> Title": renaming regenerates the slug under Pathauto
        renamed = await mcp.call("update_page_details", page="page", title=NEW_TITLE, site=SITE)
        assert renamed["title"] == NEW_TITLE
        assert renamed["slug"] == NEW_SLUG

        outline = await mcp.call("get_outline", site=SITE)
        titles = [node["item"]["title"] for node in outline["outline"]]
        assert titles == ["Welcome", NEW_TITLE]  # still second, below Welcome

        # the renamed page is reachable by its new slug
        fetched = await mcp.call("get_page", page=NEW_SLUG, site=SITE)
        assert fetched["id"] == added["id"]
        assert fetched["title"] == NEW_TITLE
    finally:
        # cleanup must not mask the real failure
        with contextlib.suppress(Exception):
            await mcp.call("archive_site", site=SITE)
