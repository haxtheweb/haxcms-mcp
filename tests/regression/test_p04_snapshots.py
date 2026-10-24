"""Phase 4 regression snapshots (PLAN §6.4, Phase 4 regression list).

* `page_break`: the envelope contract with saveNode.js/pageBreakParser — attribute order,
  canonical flag values, escaping, and absence-means-false/deletes reproduction.
* `serializer`: parse → serialize output for every fixture page — pins the lxml html
  serialisation (double quotes, bare empty attributes, slot preservation) the block
  operations and goldens build on.
* `catalog`: every bundled catalog entry — pins the extraction pipeline output and the
  CatalogEntry model shape agents read through list_blocks / get_block_schema.

Update deliberately with `pytest --snapshot-update`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from haxcms_mcp.models.item import Item
from haxcms_mcp.services.catalog.service import CatalogService
from haxcms_mcp.services.content.page_break import build_page_break
from haxcms_mcp.services.content.parser import parse_blocks
from haxcms_mcp.services.content.serializer import serialize
from tests.harness.snapshots import assert_or_update_snapshot

pytestmark = pytest.mark.regression

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pages"
FIXTURE_NAMES = ("tutorial_finished", "grid_plate", "quiz", "bare_text", "empty")

FULL_RECORD: dict[str, Any] = {
    "id": "item-123",
    "title": 'A "Quoted" <Title> & More',
    "slug": "unit-1/song-lines",
    "parent": "item-unit-1",
    "indent": 2,
    "order": 7,
    "description": "A description with & ampersand",
    "metadata": {
        "published": True,
        "locked": True,
        "hideInMenu": True,
        "pageType": "lesson",
        "tags": ["week-1", "intro"],
        "relatedItems": ["item-2", "item-3"],
        "image": "files/cover.png",
        "icon": "hax:lesson",
        "accentColor": "purple",
        "theme": {"element": "clean-one", "path": "@haxtheweb/clean-one", "key": "clean-one"},
        "overridePathauto": True,
        "linkUrl": "https://example.com/x",
        "linkTarget": "_blank",
    },
}

MINIMAL_RECORD: dict[str, Any] = {
    "id": "item-1",
    "title": "Home",
    "slug": "home",
    "metadata": {},
}

UNPUBLISHED_RECORD: dict[str, Any] = {
    "id": "item-9",
    "title": "Draft",
    "slug": "draft",
    "metadata": {"published": False},
}


def _page_break_goldens() -> dict[str, str]:
    return {
        "full": build_page_break(Item.from_api(FULL_RECORD)),
        "minimal": build_page_break(Item.from_api(MINIMAL_RECORD)),
        "unpublished": build_page_break(Item.from_api(UNPUBLISHED_RECORD)),
    }


def test_page_break_goldens(request: pytest.FixtureRequest) -> None:
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("page_break", _page_break_goldens(), update=update)


def _serializer_goldens() -> dict[str, str]:
    """parse → serialize for every fixture page (the serializer contract)."""
    return {
        name: serialize(parse_blocks((FIXTURES / f"{name}.html").read_text(encoding="utf-8")))
        for name in FIXTURE_NAMES
    }


def test_serializer_goldens(request: pytest.FixtureRequest) -> None:
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("serializer", _serializer_goldens(), update=update)


def _catalog_goldens() -> dict[str, Any]:
    """Every bundled catalog entry (model_dump) keyed by tag."""
    service = CatalogService()
    return {tag: entry.model_dump() for tag, entry in sorted(service.bundled.items())}


def test_catalog_goldens(request: pytest.FixtureRequest) -> None:
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("catalog", _catalog_goldens(), update=update)
