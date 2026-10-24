"""Phase 5 functional test: place the tutorial's two images with add_image_from_file.

PLAN Phase 5 functional list: `test_p05_tutorial_images.py` — upload `Songline_1` and
`Songline_2` and place them with alt, caption and citation exactly as the tutorial; the
page's `metadata.images` lists both sources and `metadata.files` lists both uuids.

This is the path that DOES populate `page.metadata.files`: the composite uploads (which no
longer touches metadata.files, #3043) then inserts a `media-image` whose `source` is the
uploaded `files/<name>` url, and the block insert SAVES the page — saveNode rebuilds
`metadata.images` from the media schema and `metadata.files` from a content path-scan
(`FileContentScanner.rebuildPageFilesUuids`, resolving each `files/...` reference to its
files.json uuid). The golden attributes are the two `media-image` blocks in
`tests/fixtures/pages/tutorial_finished.html`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from haxcms_mcp.services.content.parser import parse_blocks
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.functional

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
IMAGES = FIXTURES / "images"
SONGLINE_1 = IMAGES / "Songline_1.png"
SONGLINE_2 = IMAGES / "Songline_2.png"
TUTORIAL = FIXTURES / "pages" / "tutorial_finished.html"


def _store_uuids(haxcms: HaxcmsRuntime, site: str) -> set[str]:
    path = haxcms.site_dir(site) / "files" / "files.json"
    store: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return {str(record["uuid"]) for record in store["data"]["files"]}


async def test_tutorial_images(mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime) -> None:
    created = await mcp.call("create_page", title="Songlines", site=site)
    page = str(created["id"])

    # the tutorial's first image: alt + caption + citation + size="wide"
    first = await mcp.call(
        "add_image_from_file",
        page=page,
        source=str(SONGLINE_1),
        alt="Songline pattern across the prairie",
        caption="Figure 1. The songline as drawn by the walker.",
        citation="Photograph by the author.",
        size="wide",
        site=site,
    )
    # the tutorial's second image: alt + caption + card treatment
    second = await mcp.call(
        "add_image_from_file",
        page=page,
        source=str(SONGLINE_2),
        alt="Second songline panel",
        caption="Figure 2. The return walk.",
        card=True,
        site=site,
    )

    url_1 = first["file"]["url"]
    url_2 = second["file"]["url"]
    uuid_1 = first["file"]["uuid"]
    uuid_2 = second["file"]["uuid"]
    assert url_1 == "files/Songline_1.png"
    assert url_2 == "files/Songline_2.png"
    assert uuid_1 and uuid_2 and uuid_1 != uuid_2

    # --- the two stored blocks carry the EXACT tutorial attributes ---------------------
    fixture_blocks = parse_blocks(TUTORIAL.read_text(encoding="utf-8"))
    expected = [b for b in fixture_blocks if b.tag == "media-image"]
    assert len(expected) == 2
    blocks = await mcp.call("get_page_blocks", page=page, site=site)
    live = [b for b in blocks["blocks"] if b["tag"] == "media-image"]
    assert len(live) == 2
    for got, want in zip(live, expected, strict=True):
        assert got["attributes"] == want.attributes, want.tag

    # --- metadata.images lists both sources; metadata.files lists both uuids ------------
    record = await mcp.call("get_page", page=page, site=site)
    metadata = record["metadata"]
    assert set(metadata["images"]) == {url_1, url_2}
    assert set(metadata["files"]) == {uuid_1, uuid_2}

    # --- both files exist on disk and are indexed in files.json -------------------------
    site_dir = haxcms.site_dir(site)
    assert (site_dir / "files" / "Songline_1.png").is_file()
    assert (site_dir / "files" / "Songline_2.png").is_file()
    assert {uuid_1, uuid_2} <= _store_uuids(haxcms, site)
