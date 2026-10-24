"""Unit tests for the outline tree builders and fetch (PLAN Phase 3 T3.3).

`build_outline` groups by parent, sorts by order (title tie-break) and recurses; orphans
surface at root level instead of vanishing, and parent cycles are guarded so every item
appears exactly once. `fetch_all_items` paginates `GET items` with page.limit=200 because
items.js clamps the limit to 200 (default 25).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item
from haxcms_mcp.services.outline import (
    PAGE_LIMIT,
    build_outline,
    fetch_all_items,
    flatten,
    get_outline,
    resolve_parent_id,
)

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ITEMS_URL = f"{BASE}/_sites/demo/x/api/v1/items"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)


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


def item(
    item_id: str,
    *,
    title: str = "",
    order: int = 0,
    parent: str | None = None,
    slug: str = "",
) -> Item:
    return Item(
        id=item_id, title=title or item_id, order=order, parent=parent, slug=slug or item_id
    )


def ids(nodes: list[Any]) -> list[str]:
    return [node.item.id for node in nodes]


# --- build_outline: group, sort, recurse --------------------------------------------------


def test_build_outline_groups_and_sorts_roots() -> None:
    tree = build_outline([item("c", order=2), item("a", order=0), item("b", order=1)])
    assert ids(tree) == ["a", "b", "c"]
    assert all(node.children == [] for node in tree)


def test_build_outline_nests_children_under_parents() -> None:
    tree = build_outline(
        [
            item("l2", order=3, parent="u1"),
            item("u1", order=1),
            item("l1", order=2, parent="u1"),
            item("home", order=0),
        ]
    )
    assert ids(tree) == ["home", "u1"]
    unit = tree[1]
    assert ids(unit.children) == ["l1", "l2"]  # sorted by order, not manifest order


def test_build_outline_recurses_deeply() -> None:
    tree = build_outline(
        [
            item("root", order=0),
            item("mid", order=1, parent="root"),
            item("leaf", order=2, parent="mid"),
        ]
    )
    assert ids(tree) == ["root"]
    assert ids(tree[0].children) == ["mid"]
    assert ids(tree[0].children[0].children) == ["leaf"]


def test_build_outline_title_breaks_order_ties() -> None:
    tree = build_outline([item("z", title="Zed", order=0), item("a", title="Alpha", order=0)])
    assert ids(tree) == ["a", "z"]


def test_build_outline_orphan_surfaces_at_root() -> None:
    tree = build_outline([item("home", order=0), item("lost", order=1, parent="item-gone")])
    assert ids(tree) == ["home", "lost"]  # never silently dropped


def test_build_outline_self_cycle_appears_once() -> None:
    tree = build_outline([item("home", order=0), item("loop", order=1, parent="loop")])
    flat = flatten(tree)
    assert sorted(entry.id for entry in flat) == ["home", "loop"]
    by_id = {node.item.id: node for node in tree}
    assert by_id["loop"].children == []


def test_build_outline_two_node_cycle_is_guarded() -> None:
    tree = build_outline(
        [item("home", order=0), item("a", order=1, parent="b"), item("b", order=2, parent="a")]
    )
    flat = flatten(tree)
    assert sorted(entry.id for entry in flat) == ["a", "b", "home"]  # every item exactly once
    assert ids(tree) == ["home", "a"]  # one chain surfaces; b stays nested under a
    assert ids(tree[1].children) == ["b"]


def test_flatten_returns_pre_order() -> None:
    tree = build_outline(
        [
            item("u1", order=1),
            item("l11", order=2, parent="u1"),
            item("deep", order=3, parent="l11"),
            item("l12", order=4, parent="u1"),
            item("home", order=0),
        ]
    )
    assert [entry.id for entry in flatten(tree)] == ["home", "u1", "l11", "deep", "l12"]


# --- resolve_parent_id ---------------------------------------------------------------------


def test_resolve_parent_id_accepts_id_or_slug() -> None:
    items = [item("item-u1", slug="unit-1")]
    assert resolve_parent_id(items, "item-u1") == "item-u1"
    assert resolve_parent_id(items, "unit-1") == "item-u1"


def test_resolve_parent_id_none_and_blank_mean_root() -> None:
    assert resolve_parent_id([], None) is None
    assert resolve_parent_id([], "   ") is None


def test_resolve_parent_id_unknown_raises_not_found() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        resolve_parent_id([item("home")], "nope")
    error = excinfo.value
    assert error.code is ErrorCode.NOT_FOUND
    assert "get_outline" in (error.hint or "")


# --- fetch_all_items / get_outline over respx -----------------------------------------------


def summary(item_id: str, order: int, parent: str | None = None) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": item_id,
        "slug": item_id,
        "parent": parent,
        "order": order,
        "metadata": {},
    }


def items_body(chunk: list[dict[str, Any]], total: int, offset: int) -> dict[str, Any]:
    return {
        "status": 200,
        "data": {
            "count": len(chunk),
            "total": total,
            "page": {"limit": PAGE_LIMIT, "offset": offset, "total": total},
            "items": chunk,
        },
    }


@respx.mock
async def test_fetch_all_items_paginates_with_limit_200() -> None:
    mock_auth()
    first = [summary(f"i{n}", n) for n in range(PAGE_LIMIT)]
    second = [summary(f"i{n}", n) for n in range(PAGE_LIMIT, PAGE_LIMIT + 50)]
    seen: list[tuple[str, str]] = []

    def effect(request: httpx.Request) -> httpx.Response:
        offset = request.url.params.get("page.offset") or "0"
        seen.append((request.url.params.get("page.limit") or "", offset))
        chunk = first if offset == "0" else second
        return httpx.Response(200, json=items_body(chunk, PAGE_LIMIT + 50, int(offset)))

    respx.get(ITEMS_URL).mock(side_effect=effect)

    async with HaxcmsClient(make_settings()) as client:
        items = await fetch_all_items(client, "demo")

    assert seen == [(str(PAGE_LIMIT), "0"), (str(PAGE_LIMIT), str(PAGE_LIMIT))]
    assert len(items) == PAGE_LIMIT + 50
    assert items[0].id == "i0" and items[-1].id == f"i{PAGE_LIMIT + 49}"


@respx.mock
async def test_fetch_all_items_stops_on_empty_page() -> None:
    mock_auth()
    calls: list[str] = []

    def effect(request: httpx.Request) -> httpx.Response:
        offset = request.url.params.get("page.offset") or "0"
        calls.append(offset)
        # server claims a larger total but returns nothing: the loop must still terminate
        return httpx.Response(200, json=items_body([], 999, int(offset)))

    respx.get(ITEMS_URL).mock(side_effect=effect)

    async with HaxcmsClient(make_settings()) as client:
        items = await fetch_all_items(client, "demo")

    assert items == []
    assert calls == ["0"]


@respx.mock
async def test_get_outline_builds_the_tree_from_live_items() -> None:
    mock_auth()
    chunk = [
        summary("home", 0),
        summary("unit-1", 1),
        summary("lesson-1-1", 2, parent="unit-1"),
    ]
    items_route = respx.get(ITEMS_URL).mock(
        return_value=httpx.Response(200, json=items_body(chunk, len(chunk), 0))
    )

    async with HaxcmsClient(make_settings()) as client:
        tree = await get_outline(client, "demo")

    assert ids(tree) == ["home", "unit-1"]
    assert ids(tree[1].children) == ["lesson-1-1"]
    request = items_route.calls.last.request
    assert request.url.params["page.limit"] == str(PAGE_LIMIT)
