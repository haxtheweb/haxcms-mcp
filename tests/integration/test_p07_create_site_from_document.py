"""Live integration tests for create_site_from_document (PLAN T7.6/T7.7).

T7.7 findings recorded here (live-probed):

* `build.type` per kind: the service sends `"<kind> import"` and createSite persists
  it under site.json `metadata.build` as {version, structure: "import", type} — the
  `version` is the SERVER's own build string ("26.8.0" on this checkout), so tests
  assert structure/type only.
* Inline images DO materialize: the docx's PNG becomes files/unit-one-cells.jpg
  (re-encoded JPEG) with a files/files.json record and a <media-image> reference in
  the page body; the item's metadata.files carries the record uuid.
* An imported site's outline is EXACTLY the document tree — no Home page is added.
"""

from __future__ import annotations

import contextlib
import json
import secrets
from pathlib import Path
from typing import Any

import pytest

from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "import"
SYLLABUS = FIXTURES / "syllabus.docx"
SLIDES = FIXTURES / "slides.pptx"
PAGE_HTML = FIXTURES / "page.html"


def _outline_titles(site_json: dict[str, Any]) -> list[str]:
    return [item["title"] for item in site_json["items"]]


def _files_store(haxcms: HaxcmsRuntime, site: str) -> list[dict[str, Any]]:
    path = haxcms.site_dir(site) / "files" / "files.json"
    return list(json.loads(path.read_text(encoding="utf-8"))["data"]["files"])


async def test_docx_creates_a_site_whose_outline_mirrors_the_headings(
    mcp: McpTestClient, haxcms: HaxcmsRuntime
) -> None:
    name = f"mcp-p7d-{secrets.token_hex(4)}"
    created = name
    try:
        detail = await mcp.call(
            "create_site_from_document",
            name=name,
            source=str(SYLLABUS),
            description="Biology 101, built from a Word document",
        )
        created = detail["name"]
        assert created == name
        assert detail["page_count"] == 4
        assert detail["theme"] == "clean-one"
        assert detail["description"] == "Biology 101, built from a Word document"

        site_json = haxcms.read_site_json(created)
        assert _outline_titles(site_json) == [
            "Biology 101 Syllabus",
            "Unit One: Cells",
            "Unit Two: Genetics",
            "Appendix: Lab Safety",
        ]
        items = site_json["items"]
        root, unit_one = items[0], items[1]
        assert unit_one["parent"] == root["id"]
        assert unit_one["slug"] == "biology-101-syllabus/unit-one-cells"
        assert items[3].get("parent") in (None, "null")

        # T7.7: build provenance is persisted under metadata.build
        build = site_json["metadata"]["build"]
        assert build["structure"] == "import"
        assert build["type"] == "docx import"
        assert isinstance(build["version"], str) and build["version"]

        # the first page carries the document's opening paragraph
        assert "Welcome to Biology 101" in haxcms.read_page_html(created, root["id"])

        # T7.7: the inline image materialized as a site file (JPEG re-encode), is
        # registered in files.json, and the body references it as <media-image>
        unit_html = haxcms.read_page_html(created, unit_one["id"])
        assert 'source="files/unit-one-cells.jpg"' in unit_html
        assert "data:image/png;base64," not in unit_html
        assert (haxcms.site_dir(created) / "files" / "unit-one-cells.jpg").is_file()
        records = _files_store(haxcms, created)
        assert [record["name"] for record in records] == ["unit-one-cells.jpg"]
        assert records[0]["mimetype"] == "image/jpeg"
        assert records[0]["uuid"] in (unit_one.get("metadata", {}).get("files") or [])

        # the site is live in the listing
        listing = await mcp.call("list_sites")
        assert created in [entry["name"] for entry in listing["sites"]]
    finally:
        with contextlib.suppress(Exception):
            await mcp.call("archive_site", site=created)


async def test_pptx_creates_one_flat_page_per_slide(
    mcp: McpTestClient, haxcms: HaxcmsRuntime
) -> None:
    name = f"mcp-p7s-{secrets.token_hex(4)}"
    created = name
    try:
        detail = await mcp.call("create_site_from_document", name=name, source=str(SLIDES))
        created = detail["name"]
        assert detail["page_count"] == 3

        site_json = haxcms.read_site_json(created)
        assert _outline_titles(site_json) == ["Introduction", "Methods", "Results"]
        assert all(item["indent"] == 0 for item in site_json["items"])
        assert site_json["metadata"]["build"]["type"] == "pptx import"

        first_html = haxcms.read_page_html(created, site_json["items"][0]["id"])
        assert "What this study measures and why it matters." in first_html
    finally:
        with contextlib.suppress(Exception):
            await mcp.call("archive_site", site=created)


async def test_duplicate_name_creates_a_suffixed_site_and_warns(
    mcp: McpTestClient,
) -> None:
    name = f"mcp-p7x-{secrets.token_hex(4)}"
    created: list[str] = []
    try:
        first = await mcp.call("create_site_from_document", name=name, source=str(PAGE_HTML))
        created.append(first["name"])
        second = await mcp.call("create_site_from_document", name=name, source=str(PAGE_HTML))
        created.append(second["name"])
        # the server silently suffixes duplicates; the composite surfaces it
        assert second["name"] != name
        assert second["name"].startswith(name)
        assert any("already taken" in warning for warning in second["warnings"] or [])
    finally:
        for site in created:
            with contextlib.suppress(Exception):
                await mcp.call("archive_site", site=site)
