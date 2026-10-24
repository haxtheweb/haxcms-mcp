"""Unit tests for the Phase 3 models (PLAN T3.1).

Records mirror the live shapes read from the 26.8.1 route source (itemToSummary in
siteRouteUtils.js, revisions.js) — see the models' module docstrings.
"""

from __future__ import annotations

from typing import Any

import pytest

from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.item import Item, ItemCollection, ItemMetadata, OutlineNode
from haxcms_mcp.models.revision import Revision, RevisionDetail

pytestmark = pytest.mark.unit

SUMMARY_RECORD: dict[str, Any] = {
    "id": "item-11111111-2222-3333-4444-555555555555",
    "title": "Lesson 1",
    "slug": "unit-1/lesson-1",
    "parent": "item-unit-1",
    "indent": 1,
    "order": 3,
    "location": "pages/item-11111111-2222-3333-4444-555555555555/index.html",
    "description": "The first lesson",
    "metadata": {
        "created": 1750000000,
        "updated": 1750000100,
        "published": True,
        "locked": False,
        "hideInMenu": False,
        "pageType": "lesson",
        "tags": ["week-1", "intro"],
        "relatedItems": [],
        "image": "",
        "icon": "hax:lesson",
        "files": ["abc-123"],
        "images": [],
        "videos": [],
        "overridePathauto": True,
        "someFutureKey": "kept",
    },
    "region": None,
    "tags": ["week-1", "intro"],
    "published": True,
    "links": {"self": "/x/api/v1/items/unit-1%2Flesson-1", "content": "/x/api/v1/content/x"},
    "related": [{"rel": "entity", "type": "item", "href": "/x/api/v1/entities#item"}],
    "jsonld": {"@context": "https://schema.org"},
    "exports": {"pdf": "/export/pdf"},
}


def test_item_maps_the_summary_record() -> None:
    item = Item.from_api(SUMMARY_RECORD)
    assert item.id == "item-11111111-2222-3333-4444-555555555555"
    assert item.title == "Lesson 1"
    assert item.slug == "unit-1/lesson-1"
    assert item.parent == "item-unit-1"
    assert item.indent == 1
    assert item.order == 3
    assert item.description == "The first lesson"
    assert item.tags == ["week-1", "intro"]
    assert item.published is True
    assert item.links is not None and item.links["content"].endswith("/content/x")


def test_item_metadata_typed_fields_and_extra() -> None:
    item = Item.from_api(SUMMARY_RECORD)
    meta = item.metadata
    assert meta.page_type == "lesson"
    assert meta.icon == "hax:lesson"
    assert meta.override_pathauto is True
    assert meta.files == ["abc-123"]
    assert meta.created == 1750000000
    # unknown metadata keys are preserved (PLAN T3.1)
    assert meta.extra == {"someFutureKey": "kept"}


def test_item_metadata_round_trips_through_to_api() -> None:
    meta = ItemMetadata.from_api(SUMMARY_RECORD["metadata"])
    restored = meta.to_api()
    assert restored["pageType"] == "lesson"
    assert restored["hideInMenu"] is False
    assert restored["overridePathauto"] is True
    assert restored["someFutureKey"] == "kept"
    # absent optional keys are not fabricated
    assert "accentColor" not in restored
    assert "theme" not in restored


def test_item_drops_heavy_sections_but_keeps_unknown_scalars() -> None:
    item = Item.from_api(SUMMARY_RECORD)
    dumped = dump_model(item)
    assert "jsonld" not in dumped
    assert "exports" not in dumped
    assert "related" not in dumped
    assert "haxElementSchema" not in dumped
    # metadata survives the dump in the model's snake_case shape; unknown keys stay in extra
    # (outbound payloads use ItemMetadata.to_api() for the camelCase wire form instead)
    assert dumped["metadata"]["page_type"] == "lesson"
    assert dumped["metadata"]["extra"] == {"someFutureKey": "kept"}


def test_item_published_falls_back_to_metadata_then_true() -> None:
    bare = Item.from_api({"id": "item-x", "title": "X", "metadata": {"published": False}})
    assert bare.published is False
    no_flag = Item.from_api({"id": "item-y", "title": "Y", "metadata": {}})
    assert no_flag.published is True  # itemToSummary: metadata.published !== false


def test_item_tags_string_form_is_normalised() -> None:
    item = Item.from_api({"id": "i", "metadata": {"tags": "a, b,c"}})
    assert item.tags == ["a", "b", "c"]


def test_item_metadata_legacy_files_object_goes_to_extra() -> None:
    meta = ItemMetadata.from_api({"files": {"uuid-1": {"alt": "x"}}})
    assert meta.files is None
    assert meta.extra == {"files": {"uuid-1": {"alt": "x"}}}


def test_item_collection_from_api() -> None:
    data = {
        "count": 2,
        "total": 5,
        "page": {"limit": 2, "offset": 0, "total": 5},
        "items": [
            {"id": "item-a", "title": "A", "metadata": {}},
            {"id": "item-b", "title": "B", "metadata": {}},
        ],
        "links": {"self": "/x/api/v1/items"},
    }
    collection = ItemCollection.from_api(data)
    assert collection.count == 2
    assert collection.total == 5
    assert [item.id for item in collection.items] == ["item-a", "item-b"]
    assert collection.page["limit"] == 2


def test_outline_node_nests_and_serialises() -> None:
    child = OutlineNode(item=Item.from_api({"id": "c", "title": "Child", "metadata": {}}))
    root = OutlineNode(
        item=Item.from_api({"id": "r", "title": "Root", "metadata": {}}), children=[child]
    )
    dumped = dump_model(root)
    assert dumped["item"]["id"] == "r"
    assert dumped["children"][0]["item"]["title"] == "Child"
    assert dumped["children"][0]["children"] == []


REVISION_RECORD = {
    "revisionNumber": 2,
    "hash": "a" * 40,
    "shortHash": "a" * 7,
    "author": "admin",
    "authorEmail": "admin@example.com",
    "timestamp": 1750000200,
    "date": "2026-06-15T12:00:00+00:00",
    "message": "Page details updated: Lesson 1 (item-1)",
}


def test_revision_from_api() -> None:
    revision = Revision.from_api(REVISION_RECORD)
    assert revision.revision_number == 2
    assert revision.short_hash == "a" * 7
    assert revision.author_email == "admin@example.com"
    assert revision.message.startswith("Page details updated")


def test_revision_detail_from_api() -> None:
    detail = RevisionDetail.from_api(
        {
            "nodeId": "item-1",
            "nodeSlug": "lesson-1",
            "nodeTitle": "Lesson 1",
            "revision": REVISION_RECORD,
            "content": "<p>Old body</p>",
            "jsonVariantLocation": "pages/item-1/index.json",
            "links": {"self": "/revisions/aaa"},
        }
    )
    assert detail.node_id == "item-1"
    assert detail.revision.revision_number == 2
    assert detail.content == "<p>Old body</p>"
    dumped = dump_model(detail)
    assert dumped["revision"]["hash"] == "a" * 40
