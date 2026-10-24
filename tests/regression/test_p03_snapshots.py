"""Phase 3 regression snapshots (PLAN §6.4, T3.5).

* `reorder_payload`: the contract with saveOutline.js — complete manifest, camelCase
  metadata round-tripped (overridePathauto and unknown keys included), reassigned order
  slots.
* `detail_operations`: the PATCH sequence contract with nodeDetailOperations.js — one
  operation per request, PLAN T3.4's order, setSlug LAST so setTitle cannot overwrite an
  explicit slug under Pathauto.

Update deliberately with `pytest --snapshot-update`.
"""

from __future__ import annotations

from typing import Any

import pytest

from haxcms_mcp.models.item import Item
from haxcms_mcp.services.outline import build_reorder_payload
from haxcms_mcp.services.pages import build_detail_operations
from tests.harness.snapshots import assert_or_update_snapshot

pytestmark = pytest.mark.regression

# deterministic six-item manifest (the same fixture the unit tests use, frozen here)
RECORDS: list[dict[str, Any]] = [
    {
        "id": "item-home",
        "title": "Welcome",
        "slug": "welcome",
        "parent": None,
        "indent": 0,
        "order": 0,
        "location": "pages/item-home/index.html",
        "metadata": {"created": 1750000000},
    },
    {
        "id": "item-unit-1",
        "title": "Unit 1",
        "slug": "unit-1",
        "parent": None,
        "indent": 0,
        "order": 1,
        "metadata": {"created": 1750000010},
    },
    {
        "id": "item-l11",
        "title": "Lesson 1.1",
        "slug": "unit-1/lesson-11",
        "parent": "item-unit-1",
        "indent": 1,
        "order": 2,
        "metadata": {"pageType": "lesson", "overridePathauto": True},
    },
    {
        "id": "item-l12",
        "title": "Lesson 1.2",
        "slug": "unit-1/lesson-12",
        "parent": "item-unit-1",
        "indent": 1,
        "order": 3,
        "metadata": {"pageType": "lesson", "tags": ["week-1"]},
    },
    {
        "id": "item-unit-2",
        "title": "Unit 2",
        "slug": "unit-2",
        "parent": None,
        "indent": 0,
        "order": 4,
        "metadata": {},
    },
    {
        "id": "item-l21",
        "title": "Lesson 2.1",
        "slug": "unit-2/lesson-21",
        "parent": "item-unit-2",
        "indent": 1,
        "order": 5,
        "metadata": {"someFutureKey": "kept"},
    },
]


def _goldens() -> dict[str, Any]:
    items = [Item.from_api(record) for record in RECORDS]
    return {
        "reorder_root": build_reorder_payload(
            items, None, ["item-unit-2", "item-home", "item-unit-1"]
        ),
        "reorder_nested": build_reorder_payload(items, "item-unit-1", ["item-l12", "item-l11"]),
    }


def test_reorder_payload(request: pytest.FixtureRequest) -> None:
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("reorder_payload", _goldens(), update=update)


def _detail_goldens() -> list[dict[str, Any]]:
    """Every field at once: the emitted order is the regression contract."""
    return build_detail_operations(
        title="New Title",
        slug="new-title",
        description="A description",
        tags=["week-1", "intro"],
        published=False,
        locked=True,
        hide_in_menu=True,
        icon="hax:lesson",
        image="files/cover.png",
        related_pages=["item-2"],
    )


def test_detail_operation_order(request: pytest.FixtureRequest) -> None:
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("detail_operations", _detail_goldens(), update=update)
