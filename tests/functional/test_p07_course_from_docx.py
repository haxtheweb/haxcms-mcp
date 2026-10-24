"""Functional user story for the Phase 7 import tools (PLAN Appendix D).

"Build a course from my syllabus.docx" — expressed only through Tool calls against the
live instance: create_site_from_document turns the Word document into a whole site
whose outline mirrors the headings, the opening paragraph lands on the first page, a
nested lesson is reachable by its slug, and the inline image became a listed site file.
"""

from __future__ import annotations

import contextlib
import secrets
from pathlib import Path

import pytest

from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.functional

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "import"
SYLLABUS = FIXTURES / "syllabus.docx"

SITE = f"p7-course-{secrets.token_hex(3)}"


async def test_build_a_course_from_a_docx_syllabus(mcp: McpTestClient) -> None:
    try:
        detail = await mcp.call(
            "create_site_from_document",
            name=SITE,
            source=str(SYLLABUS),
            description="Biology 101",
        )
        assert detail["name"] == SITE

        # the course shows up in the listing with its four document pages
        listing = await mcp.call("list_sites")
        assert SITE in [entry["name"] for entry in listing["sites"]]

        # the outline is the document tree: the two H1s as roots (ordered by the
        # importer's order counters), the H2 units nested under the first
        outline = await mcp.call("get_outline", site=SITE)
        assert outline["count"] == 4
        roots = outline["outline"]
        assert [node["item"]["title"] for node in roots] == [
            "Biology 101 Syllabus",
            "Appendix: Lab Safety",
        ]
        assert [child["item"]["title"] for child in roots[0]["children"]] == [
            "Unit One: Cells",
            "Unit Two: Genetics",
        ]
        assert roots[1]["children"] == []

        # the first page carries the document's opening paragraph
        first = outline["outline"][0]["item"]
        content = await mcp.call("get_page_content", page=first["id"], site=SITE)
        assert "Welcome to Biology 101" in content["html"]

        # a nested lesson is reachable by its document-derived slug
        unit_one = await mcp.call("get_page", page="biology-101-syllabus/unit-one-cells", site=SITE)
        assert unit_one["title"] == "Unit One: Cells"

        # the syllabus' inline image became a managed site file
        files = await mcp.call("list_files", site=SITE)
        assert "unit-one-cells.jpg" in [record["name"] for record in files["files"]]
    finally:
        # cleanup must not mask the real failure
        with contextlib.suppress(Exception):
            await mcp.call("archive_site", site=SITE)
