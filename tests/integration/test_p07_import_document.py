"""Live integration tests for the import_document tool (PLAN T7.6).

Fixture facts (live-probed in Phase 7, recorded in PROGRESS.md):

* syllabus.docx (two H1s, two H2s under the first, one H3, inline PNG): method=site
  -> 4 records (2 roots + 2 children with nested `parent-slug/child-slug` slugs);
  method=branch -> the 2 H1 pages only, FLAT; method=page -> ONE page titled with the
  filename stem holding the whole document.
* workbook.xlsx: the first sheet ("Schedule") follows the title/slug/parent/content
  header contract -> 3 pages; the parent column's slug resolves to the parent's
  server-fresh id. `selectedSheet` echoes at the API level.
* page.html -> h1 root + two h2 children (nested slugs); onepage.pdf -> ONE page.
* The bulk-create step materializes inline data-URI images on the server: Unit One's
  PNG lands as files/unit-one-cells.jpg (re-encoded JPEG, 120x80) with a files.json
  record, and the page body references it as <media-image>.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from haxcms_mcp.client import HaxcmsClient, system_api
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "import"
SYLLABUS = FIXTURES / "syllabus.docx"
WORKBOOK = FIXTURES / "workbook.xlsx"
PAGE_HTML = FIXTURES / "page.html"
ONEPAGE_PDF = FIXTURES / "onepage.pdf"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SYLLABUS_TITLES = [
    "Biology 101 Syllabus",
    "Unit One: Cells",
    "Unit Two: Genetics",
    "Appendix: Lab Safety",
]


def _titles(result: dict[str, Any]) -> list[str]:
    return [item["title"] for item in result["created"]]


async def test_docx_method_site_shapes_the_outline(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    result = await mcp.call("import_document", source=str(SYLLABUS), method="site", site=site)
    created = result["created"]
    assert _titles(result) == SYLLABUS_TITLES
    assert result["skipped"] == 0
    assert result["source_filename"] == "syllabus.docx"

    root, unit_one, unit_two, appendix = created
    assert root.get("parent") is None
    assert appendix.get("parent") is None
    assert unit_one["parent"] == root["id"]
    assert unit_two["parent"] == root["id"]
    assert unit_one["slug"] == "biology-101-syllabus/unit-one-cells"
    assert unit_two["slug"] == "biology-101-syllabus/unit-two-genetics"
    assert (unit_one["indent"], unit_two["indent"]) == (1, 1)

    # the outline tool shows the imported tree next to the site's Home page. Roots sort
    # by (order, title): the imported roots carry the importer's orders (0 and 1), so
    # order-0 "Biology 101 Syllabus" lands BEFORE Home and the children nest under it.
    outline = await mcp.call("get_outline", site=site)
    assert outline["count"] == 5
    roots = {node["item"]["title"]: node for node in outline["outline"]}
    assert set(roots) == {"Home", "Biology 101 Syllabus", "Appendix: Lab Safety"}
    children = roots["Biology 101 Syllabus"]["children"]
    assert [child["item"]["title"] for child in children] == [
        "Unit One: Cells",
        "Unit Two: Genetics",
    ]
    assert roots["Appendix: Lab Safety"]["children"] == []

    # bodies landed on disk: the welcome paragraph on the root, the H3 folded into
    # Unit Two's content stream, and Unit One's inline image materialized as a file
    assert "Welcome to Biology 101" in haxcms.read_page_html(site, root["id"])
    unit_one_html = haxcms.read_page_html(site, unit_one["id"])
    assert 'source="files/unit-one-cells.jpg"' in unit_one_html
    assert "data:image/png;base64," not in unit_one_html
    unit_two_html = haxcms.read_page_html(site, unit_two["id"])
    assert "Lesson: Punnett Squares" in unit_two_html

    store = json.loads((haxcms.site_dir(site) / "files" / "files.json").read_text(encoding="utf-8"))
    records = store["data"]["files"]
    assert [record["name"] for record in records] == ["unit-one-cells.jpg"]
    assert records[0]["mimetype"] == "image/jpeg"
    assert (records[0]["width"], records[0]["height"]) == (120, 80)


async def test_docx_method_branch_attaches_flat_pages_under_a_parent(
    mcp: McpTestClient, site: str
) -> None:
    parent = await mcp.call("create_page", title="Parent Page", site=site)
    result = await mcp.call(
        "import_document",
        source=str(SYLLABUS),
        method="branch",
        parent=parent["id"],
        site=site,
    )
    created = result["created"]
    # branch mode keeps ONLY the top-level headings, flat, wired under the parent;
    # the bulk create stores the importer's records verbatim, so `indent` stays 0 —
    # the nesting lives in the parent references, not the indent counters
    assert _titles(result) == ["Biology 101 Syllabus", "Appendix: Lab Safety"]
    assert all(item["parent"] == parent["id"] for item in created)
    assert all(item["indent"] == 0 for item in created)


async def test_docx_method_page_wraps_everything_into_one_page(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    result = await mcp.call("import_document", source=str(SYLLABUS), method="page", site=site)
    created = result["created"]
    assert len(created) == 1
    page = created[0]
    assert page["title"] == "syllabus"  # the filename stem
    assert page["slug"] == "syllabus"
    html = haxcms.read_page_html(site, page["id"])
    assert "<h1>Biology 101 Syllabus</h1>" in html
    assert "Welcome to Biology 101" in html
    assert "Goggles on" in html  # even the second H1's body is in the single page


async def test_docx_content_type_course_is_accepted(mcp: McpTestClient, site: str) -> None:
    result = await mcp.call(
        "import_document",
        source=str(SYLLABUS),
        method="site",
        content_type="course",
        site=site,
    )
    # the fixture's headings all carry body text, so the placeholder-content toggle
    # (course vs. lesson-overview) cannot change the shape — only that it is accepted
    assert _titles(result) == SYLLABUS_TITLES


async def test_xlsx_first_sheet_becomes_pages_with_parent_wiring(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    result = await mcp.call("import_document", source=str(WORKBOOK), site=site)
    created = result["created"]
    assert _titles(result) == ["Course Home", "Week One", "Week Two"]
    home, week_one, week_two = created
    assert home.get("parent") is None
    assert week_one["parent"] == home["id"]  # the sheet's slug column resolved to the id
    assert week_two["parent"] == home["id"]
    assert "Weekly schedule" in haxcms.read_page_html(site, home["id"])
    assert "<p>Cells.</p>" in haxcms.read_page_html(site, week_one["id"])


async def test_xlsx_api_response_echoes_the_selected_sheet(client: HaxcmsClient) -> None:
    data = await system_api.import_document(
        client,
        "xlsx",
        filename="workbook.xlsx",
        content=WORKBOOK.read_bytes(),
        mimetype=XLSX_MIME,
    )
    assert data["selectedSheet"] == "Schedule"  # the FIRST sheet
    assert data["filename"] == "workbook.xlsx"
    assert [item["title"] for item in data["items"]] == ["Course Home", "Week One", "Week Two"]


async def test_html_import_nests_under_the_h1(mcp: McpTestClient, site: str) -> None:
    result = await mcp.call("import_document", source=str(PAGE_HTML), site=site)
    created = result["created"]
    assert _titles(result) == ["Field Trip", "Logistics", "Packing List"]
    assert created[1]["slug"] == "field-trip/logistics"
    assert created[2]["slug"] == "field-trip/packing-list"
    assert created[1]["parent"] == created[0]["id"]


async def test_pdf_import_creates_one_page_with_the_extracted_text(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    result = await mcp.call("import_document", source=str(ONEPAGE_PDF), site=site)
    created = result["created"]
    assert len(created) == 1
    assert created[0]["title"] == "Quantum Field Theory Notes"
    html = haxcms.read_page_html(site, created[0]["id"])
    assert "path integral formulation" in html


async def test_legacy_doc_extension_is_refused_locally(mcp: McpTestClient, site: str) -> None:
    # the server's OOXML importers enforce .docx + zip magic, so legacy .doc binaries
    # are refused locally at kind detection — before a doomed upload (the base64:
    # source keeps the test independent of the input roots)
    error = await mcp.call_error(
        "import_document", source="base64:notes.doc:bm90IGEgZG9jdW1lbnQ=", site=site
    )
    assert "[INVALID_ARGUMENT]" in error
    assert "cannot detect an import kind" in error
