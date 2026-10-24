"""Functional user story for the Phase 8 export tools (PLAN Appendix D).

"Export my course as a zip and the lesson as PDF" — expressed only through Tool calls
against the live instance: build a tiny course, download the whole-site archive, and get
the lesson as a document. Both files must exist in the Output Directory with the correct
extensions.

DEVIATION (live-probed): the lesson PDF renders only where the HAXcms server has Chrome;
this machine's instance has none, so `export_page(format="pdf")` answers `[UNSUPPORTED]`
with the no-Chrome hint. The journey asserts that contract and falls back to the docx
export (which needs no Chrome), so the operator still leaves with two files — a .zip and
a .docx — instead of .zip and .pdf.
"""

from __future__ import annotations

import contextlib
import secrets
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.functional

SITE = f"p08-course-{secrets.token_hex(3)}"


@pytest.fixture
async def mcp_out(haxcms: HaxcmsRuntime, tmp_path: Path) -> AsyncIterator[McpTestClient]:
    """An MCP app whose Output Directory is the test's tmp_path (artifacts stay local)."""
    settings = Settings(
        base_url=haxcms.base_url,
        username=haxcms.username,
        password=haxcms.password,
        output_dir=tmp_path,
    )
    server: FastMCP = build_server(settings)
    async with Client(server) as inner:
        yield McpTestClient(server, inner)


async def test_export_my_course_as_a_zip_and_the_lesson_as_pdf(
    mcp_out: McpTestClient, tmp_path: Path
) -> None:
    try:
        detail = await mcp_out.call("create_site", name=SITE, description="Algebra I")
        assert detail["name"] == SITE
        lesson = await mcp_out.call(
            "create_page",
            title="Lesson One",
            content_html="<p>Solve for x: 2x + 3 = 11.</p>",
            site=SITE,
        )
        assert lesson["title"] == "Lesson One"

        # 1. the whole course as a zip archive in the Output Directory
        archive = await mcp_out.call("download_site_zip", site=SITE)
        zip_path = Path(archive["path"])
        assert zip_path.suffix == ".zip"
        assert zip_path.parent == tmp_path / SITE  # <output>/<site>/ per PLAN §2.3
        assert zip_path.read_bytes()[:2] == b"PK"
        assert archive["bytes"] == zip_path.stat().st_size

        # 2. the lesson as a PDF — Chrome-rendered where the server has Chrome
        document: Path
        try:
            result = await mcp_out.client.call_tool(
                "export_page", {"page": lesson["id"], "format": "pdf", "site": SITE}
            )
        except ToolError as exc:
            message = str(exc)
            assert "[UNSUPPORTED]" in message, message
            assert "no Chrome for PDF rendering" in message, message
            # Chrome-less fallback: the operator still gets a document file
            fallback = await mcp_out.call(
                "export_page", page=lesson["id"], format="docx", site=SITE
            )
            document = Path(fallback["path"])
            assert document.suffix == ".docx"
            assert document.read_bytes()[:2] == b"PK"
        else:
            document = Path(result.data["path"])
            assert document.suffix == ".pdf"
            assert document.read_bytes().startswith(b"%PDF")

        # two files exist in the Output Directory with the correct extensions
        assert zip_path.is_file()
        assert document.is_file()
        assert zip_path != document
    finally:
        with contextlib.suppress(Exception):
            await mcp_out.call("archive_site", site=SITE)
