"""Functional user story for the Phase 3 outline tools (PLAN Appendix D tutorial).

"Structure the course": build Unit 1 > Lesson 1.1, Lesson 1.2 in one bulk Tool call,
reorder the lessons, and unpublish/republish a lesson — checking the anonymous outline
after each step.
"""

from __future__ import annotations

import contextlib
import secrets
from typing import Any

import pytest

from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient
from tests.harness.site_reads import public_titles

pytestmark = pytest.mark.functional

SITE = f"p3-structure-{secrets.token_hex(3)}"


def _titles(nodes: list[dict[str, Any]]) -> list[str]:
    return [node["item"]["title"] for node in nodes]


async def test_structure_course(mcp: McpTestClient, haxcms: HaxcmsRuntime) -> None:
    try:
        await mcp.call("create_site", name=SITE, theme="clean-one", first_page_title="Welcome")

        # build Unit 1 > Lesson 1.1, Lesson 1.2 in ONE bulk call (one git commit)
        bulk = await mcp.call(
            "create_pages",
            items=[
                {"id": "unit-1", "title": "Unit 1"},
                {"id": "lesson-1-1", "title": "Lesson 1.1", "parent": "unit-1"},
                {"id": "lesson-1-2", "title": "Lesson 1.2", "parent": "unit-1"},
            ],
            site=SITE,
        )
        assert bulk["count"] == 3
        # bulk["pages"] are flat page records (input order), not outline nodes
        assert [page["title"] for page in bulk["pages"]] == [
            "Unit 1",
            "Lesson 1.1",
            "Lesson 1.2",
        ]

        outline = await mcp.call("get_outline", site=SITE)
        assert outline["count"] == 4
        unit = outline["outline"][1]
        assert unit["item"]["title"] == "Unit 1"
        assert _titles(unit["children"]) == ["Lesson 1.1", "Lesson 1.2"]
        assert public_titles(haxcms.base_url, SITE) == [
            "Welcome",
            "Unit 1",
            "Lesson 1.1",
            "Lesson 1.2",
        ]

        # reorder the lessons: 1.2 first (ordered_ids lists every child exactly once)
        reordered = await mcp.call(
            "reorder_pages",
            ordered_ids=["lesson-1-2", "lesson-1-1"],
            parent="unit-1",
            site=SITE,
        )
        assert _titles(reordered["outline"][1]["children"]) == ["Lesson 1.2", "Lesson 1.1"]

        # unpublish hides the lesson from anonymous visitors, not from the outline
        unpublished = await mcp.call(
            "update_page_details", page="lesson-1-1", published=False, site=SITE
        )
        assert unpublished["published"] is False
        assert "Lesson 1.1" not in public_titles(haxcms.base_url, SITE)
        assert "Lesson 1.2" in public_titles(haxcms.base_url, SITE)
        outline = await mcp.call("get_outline", site=SITE)
        assert _titles(outline["outline"][1]["children"]) == ["Lesson 1.2", "Lesson 1.1"]

        # republish brings it back
        await mcp.call("update_page_details", page="lesson-1-1", published=True, site=SITE)
        assert "Lesson 1.1" in public_titles(haxcms.base_url, SITE)
    finally:
        # cleanup must not mask the real failure
        with contextlib.suppress(Exception):
            await mcp.call("archive_site", site=SITE)
