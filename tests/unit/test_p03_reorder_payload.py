"""Unit tests for the outline reorder payload and the write operations (PLAN Phase 3 T3.3).

`build_reorder_payload` reassigns only the target parent's order slots and round-trips every
item's slug and metadata (saveOutline regenerates slugs under Pathauto unless
`metadata.overridePathauto`, and it merges metadata — lost keys would corrupt pages).
`reorder_pages` always sends the COMPLETE manifest because omitted items keep stale order
values upstream. `set_page_parent` appends after the new siblings when order is omitted
(upstream would default to 0 and jump the page to the top).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item, OutlineNode
from haxcms_mcp.services.outline import (
    build_reorder_payload,
    move_page,
    normalize_slugs,
    reorder_pages,
    set_page_parent,
)

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ITEMS_URL = f"{BASE}/_sites/demo/x/api/v1/items"
OUTLINE_URL = f"{BASE}/_sites/demo/x/api/v1/site/outline"
NORMALIZE_URL = f"{BASE}/_sites/demo/x/api/v1/site/normalize-slugs"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

# a deterministic six-item course manifest, in the shape GET items returns
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


def fixture_items() -> list[Item]:
    return [Item.from_api(record) for record in RECORDS]


def orders(payload: list[dict[str, Any]]) -> dict[str, int]:
    return {entry["id"]: entry["order"] for entry in payload}


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"status": 200, "jwt": "jwt-1"},
            headers={"set-cookie": "haxcms_refresh_token=r1; Path=/; HttpOnly"},
        )
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def mock_items() -> respx.Route:
    return respx.get(ITEMS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "count": len(RECORDS),
                    "total": len(RECORDS),
                    "page": {"limit": 200, "offset": 0, "total": len(RECORDS)},
                    "items": RECORDS,
                },
            },
        )
    )


# --- build_reorder_payload (pure) ------------------------------------------------------------


def test_reorder_root_reassigns_only_root_slots() -> None:
    payload = build_reorder_payload(
        fixture_items(), None, ["item-unit-2", "item-home", "item-unit-1"]
    )
    assert len(payload) == len(RECORDS)  # the COMPLETE manifest
    # root slots were {0, 1, 4}; the new sequence takes them in ascending order
    assert orders(payload) == {
        "item-unit-2": 0,
        "item-home": 1,
        "item-unit-1": 4,
        "item-l11": 2,  # non-children untouched
        "item-l12": 3,
        "item-l21": 5,
    }


def test_reorder_nested_children_keeps_roots_stable() -> None:
    payload = build_reorder_payload(fixture_items(), "item-unit-1", ["item-l12", "item-l11"])
    assert orders(payload) == {
        "item-l12": 2,
        "item-l11": 3,
        "item-home": 0,
        "item-unit-1": 1,
        "item-unit-2": 4,
        "item-l21": 5,
    }


def test_reorder_payload_round_trips_slug_and_metadata() -> None:
    payload = build_reorder_payload(fixture_items(), "item-unit-1", ["item-l12", "item-l11"])
    by_id = {entry["id"]: entry for entry in payload}
    lesson = by_id["item-l11"]
    assert set(lesson) == {"id", "title", "parent", "indent", "order", "slug", "metadata"}
    assert lesson["slug"] == "unit-1/lesson-11"  # nested slug survives verbatim
    # camelCase wire form; overridePathauto stops saveOutline regenerating the slug
    assert lesson["metadata"] == {"pageType": "lesson", "overridePathauto": True}
    assert by_id["item-l12"]["metadata"] == {"pageType": "lesson", "tags": ["week-1"]}
    # unknown metadata keys are preserved so outline saves never lose data
    assert by_id["item-l21"]["metadata"] == {"someFutureKey": "kept"}
    assert by_id["item-home"]["metadata"] == {"created": 1750000000}


def test_reorder_missing_child_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        build_reorder_payload(fixture_items(), "item-unit-1", ["item-l11"])
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "missing" in error.message and "item-l12" in error.message
    assert "get_outline" in (error.hint or "")


def test_reorder_unknown_id_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        build_reorder_payload(fixture_items(), "item-unit-1", ["item-l11", "item-l12", "nope"])
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "not children of this parent" in error.message and "nope" in error.message


def test_reorder_duplicate_id_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        build_reorder_payload(fixture_items(), "item-unit-1", ["item-l11", "item-l11"])
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


def test_reorder_childless_parent_accepts_empty_list() -> None:
    payload = build_reorder_payload(fixture_items(), "item-home", [])
    assert orders(payload) == {entry["id"]: entry["order"] for entry in RECORDS}


# --- reorder_pages / set_page_parent / move_page / normalize_slugs (respx) -------------------


@respx.mock
async def test_reorder_pages_sends_complete_manifest_and_returns_outline() -> None:
    mock_auth()
    mock_items()

    def outline_effect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # saveOutline responds with the full manifest; echo the payload back as records
        return httpx.Response(200, json={"status": 200, "data": {"items": body["items"]}})

    outline_route = respx.patch(OUTLINE_URL).mock(side_effect=outline_effect)

    async with HaxcmsClient(make_settings()) as client:
        tree = await reorder_pages(
            client,
            "demo",
            "unit-1",
            ["item-l12", "item-l11"],  # parent by slug
        )

    sent = json.loads(outline_route.calls.last.request.content)
    assert sent["site"] == {"name": "demo"}
    assert len(sent["items"]) == len(RECORDS)
    assert orders(sent["items"])["item-l12"] == 2
    assert orders(sent["items"])["item-l11"] == 3
    assert isinstance(tree, list) and all(isinstance(node, OutlineNode) for node in tree)
    assert [node.item.id for node in tree] == ["item-home", "item-unit-1", "item-unit-2"]
    unit_1 = tree[1]
    assert [child.item.id for child in unit_1.children] == ["item-l12", "item-l11"]


@respx.mock
async def test_set_page_parent_appends_after_new_siblings() -> None:
    mock_auth()
    mock_items()
    patch_route = respx.patch(url__regex=r".*/x/api/v1/items/[^/]+$").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "id": "item-home",
                    "title": "Welcome",
                    "slug": "welcome",
                    "parent": "item-unit-1",
                    "order": 4,
                    "metadata": {},
                },
            },
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        moved = await set_page_parent(client, "demo", "item-home", parent="unit-1")

    body = json.loads(patch_route.calls.last.request.content)
    assert body["operation"] == "setParent"
    assert body["parent"] == "item-unit-1"  # slug resolved to the id
    assert body["order"] == 4  # max(l11=2, l12=3) + 1 — upstream would default to 0
    assert moved.parent == "item-unit-1"
    assert moved.order == 4


@respx.mock
async def test_set_page_parent_explicit_order_passthrough() -> None:
    mock_auth()
    mock_items()
    patch_route = respx.patch(url__regex=r".*/x/api/v1/items/[^/]+$").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": RECORDS[0]})
    )

    async with HaxcmsClient(make_settings()) as client:
        await set_page_parent(client, "demo", "item-home", parent="item-unit-1", order=0)

    body = json.loads(patch_route.calls.last.request.content)
    assert body["order"] == 0


@respx.mock
async def test_set_page_parent_none_moves_to_root_end() -> None:
    mock_auth()
    mock_items()
    patch_route = respx.patch(url__regex=r".*/x/api/v1/items/[^/]+$").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": RECORDS[2]})
    )

    async with HaxcmsClient(make_settings()) as client:
        await set_page_parent(client, "demo", "item-l11")

    body = json.loads(patch_route.calls.last.request.content)
    assert body["parent"] is None
    assert body["order"] == 5  # appended after the last root item (order 4)


@respx.mock
async def test_set_page_parent_unknown_parent_raises_before_the_patch() -> None:
    mock_auth()
    mock_items()
    patch_route = respx.patch(url__regex=r".*/x/api/v1/items/[^/]+$").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": RECORDS[0]})
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await set_page_parent(client, "demo", "item-home", parent="nope")

    assert excinfo.value.code is ErrorCode.NOT_FOUND
    assert patch_route.call_count == 0


@respx.mock
async def test_move_page_rejects_unknown_direction_before_any_write() -> None:
    mock_auth()
    patch_route = respx.patch(url__regex=r".*/x/api/v1/items/[^/]+$").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": RECORDS[0]})
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await move_page(client, "demo", "item-home", "sideways")

    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert error.hint == "use up, down, indent or outdent"
    assert patch_route.call_count == 0


@respx.mock
async def test_move_page_maps_every_direction_to_its_operation() -> None:
    with respx.mock:
        mock_auth()
        patch_route = respx.patch(url__regex=r".*/x/api/v1/items/[^/]+$").mock(
            return_value=httpx.Response(200, json={"status": 200, "data": RECORDS[0]})
        )

        async with HaxcmsClient(make_settings()) as client:
            for direction, operation in [
                ("up", "moveUp"),
                ("down", "moveDown"),
                ("indent", "indent"),
                ("outdent", "outdent"),
            ]:
                moved = await move_page(client, "demo", "item-home", f" {direction.upper()} ")
                assert moved.id == "item-home"
                body = json.loads(patch_route.calls.last.request.content)
                assert body["operation"] == operation
                assert body["site"] == {"name": "demo"}


@respx.mock
async def test_normalize_slugs_passes_preview_and_returns_the_report() -> None:
    mock_auth()
    report = {
        "changed": 2,
        "preview": True,
        "changes": [
            {
                "id": "item-l11",
                "title": "Lesson 1.1",
                "oldSlug": "unit-1/lesson-11",
                "newSlug": "unit-1/lesson-1-1",
            }
        ],
        "skipped": [
            {"id": "item-home", "title": "Welcome", "oldSlug": "welcome", "reason": "override"}
        ],
    }
    route = respx.post(NORMALIZE_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": report})
    )

    async with HaxcmsClient(make_settings()) as client:
        result = await normalize_slugs(client, "demo", preview=True)

    body = json.loads(route.calls.last.request.content)
    assert body == {"site": {"name": "demo"}, "preview": True}
    assert result == report
