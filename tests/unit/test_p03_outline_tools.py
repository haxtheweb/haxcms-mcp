"""Unit tests for the five outline tools through the MCP interface (PLAN Phase 3 T3.5).

The outline service is covered in test_p03_outline_tree.py / test_p03_reorder_payload.py;
these tests drive the REGISTERED tools over an in-memory Client against a stateful respx
fake, so the tool -> service -> wire mapping is pinned end to end: site defaulting and
lowercasing, the COMPLETE `PATCH site/outline` manifest reorder_pages sends (an outline
save is the one write that can rewrite every page, so its body is asserted exactly), the
operation names move_page/set_page_parent send, normalize_slugs' preview flag, error
surfacing as `[CODE] message`, and the read-only gate refusing the destructive tools
before any write.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ITEMS_URL = f"{BASE}/_sites/demo/x/api/v1/items"
ITEM_RE = r".*/_sites/demo/x/api/v1/items/[^/]+$"
OUTLINE_URL = f"{BASE}/_sites/demo/x/api/v1/site/outline"
NORMALIZE_URL = f"{BASE}/_sites/demo/x/api/v1/site/normalize-slugs"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)


def record(
    item_id: str, title: str, *, parent: str | None = None, order: int = 0, **meta: Any
) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "slug": title.lower().replace(" ", "-"),
        "parent": parent,
        "indent": 0 if parent is None else 1,
        "order": order,
        "metadata": dict(meta),
    }


def starting_items() -> list[dict[str, Any]]:
    return [
        record("a", "Intro", order=0),
        record("b", "Unit One", order=1, overridePathauto=True),
        record("b1", "Lesson One", parent="b", order=0),
        record("b2", "Lesson Two", parent="b", order=1),
        record("c", "Wrap Up", order=2, published=False),
    ]


def make_settings(**kwargs: object) -> Settings:
    return Settings(
        base_url=BASE,
        username="test-user",
        password=secrets.token_urlsafe(16),
        **kwargs,  # type: ignore[arg-type]
    )


def ok(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


class FakeOutline:
    """Items list + outline save + per-item operations; records every write body."""

    def __init__(self) -> None:
        self.items = starting_items()
        self.outline_saves: list[dict[str, Any]] = []
        self.item_patches: list[tuple[str, dict[str, Any]]] = []
        self.normalize_bodies: list[dict[str, Any]] = []

    def install(self) -> None:
        respx.post(LOGIN_URL).mock(
            return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
        )
        respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))
        respx.get(ITEMS_URL).mock(side_effect=self._list)
        respx.patch(OUTLINE_URL).mock(side_effect=self._save_outline)
        respx.patch(url__regex=ITEM_RE).mock(side_effect=self._patch_item)
        respx.post(NORMALIZE_URL).mock(side_effect=self._normalize)

    @property
    def writes(self) -> int:
        return len(self.outline_saves) + len(self.item_patches) + len(self.normalize_bodies)

    def _list(self, request: httpx.Request) -> httpx.Response:
        return ok({"count": len(self.items), "total": len(self.items), "items": self.items})

    def _save_outline(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.outline_saves.append(body)
        self.items = [dict(entry) for entry in body["items"]]
        return ok({"items": self.items})

    def _patch_item(self, request: httpx.Request) -> httpx.Response:
        page = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)
        self.item_patches.append((page, body))
        current = next(item for item in self.items if page in (item["id"], item["slug"]))
        updated = dict(current)
        if body.get("operation") == "setParent":
            updated["parent"] = body.get("parent")
            updated["order"] = body.get("order")
        return ok(updated)

    def _normalize(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.normalize_bodies.append(body)
        return ok({"changed": 0, "preview": body["preview"], "changes": [], "skipped": ["b"]})


async def call(settings: Settings, tool: str, **arguments: Any) -> Any:
    async with Client(build_server(settings)) as client:
        result = await client.call_tool(tool, arguments)
    return result.data


async def call_error(settings: Settings, tool: str, **arguments: Any) -> str:
    async with Client(build_server(settings)) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(tool, arguments)
    return str(excinfo.value)


# --- site addressing ------------------------------------------------------------------------


@respx.mock
async def test_get_outline_uses_the_default_site_lowercased() -> None:
    fake = FakeOutline()
    fake.install()
    data = await call(make_settings(default_site="Demo"), "get_outline")
    assert data["site"] == "demo"
    assert data["count"] == 5
    roots = [node["item"]["id"] for node in data["outline"]]
    assert roots == ["a", "b", "c"]
    unit = data["outline"][1]
    assert [child["item"]["id"] for child in unit["children"]] == ["b1", "b2"]


@respx.mock
async def test_outline_tools_without_any_site_fail_before_http() -> None:
    fake = FakeOutline()
    fake.install()
    message = await call_error(make_settings(), "reorder_pages", ordered_ids=["c", "b", "a"])
    assert message.startswith("[INVALID_ARGUMENT] site is required")
    assert not respx.calls  # not even a login
    assert fake.writes == 0


# --- reorder_pages: the complete-manifest outline save --------------------------------------


@respx.mock
async def test_reorder_pages_sends_the_complete_manifest_with_metadata() -> None:
    fake = FakeOutline()
    fake.install()
    data = await call(make_settings(), "reorder_pages", ordered_ids=["c", "a", "b"], site="demo")
    [save] = fake.outline_saves
    assert save["site"] == {"name": "demo"}
    by_id = {entry["id"]: entry for entry in save["items"]}
    # EVERY item is sent (omitted ones would keep stale order and lose Pathauto state)
    assert sorted(by_id) == ["a", "b", "b1", "b2", "c"]
    # the root slots 0,1,2 are reassigned to the new sequence; children keep theirs
    assert {key: by_id[key]["order"] for key in by_id} == {
        "c": 0,
        "a": 1,
        "b": 2,
        "b1": 0,
        "b2": 1,
    }
    # slugs and metadata round-trip so overridePathauto / published survive the save
    assert by_id["b"]["slug"] == "unit-one"
    assert by_id["b"]["metadata"].get("overridePathauto") is True
    assert by_id["c"]["metadata"].get("published") is False
    assert by_id["b1"]["parent"] == "b"
    assert [node["item"]["id"] for node in data["outline"]] == ["c", "a", "b"]


@respx.mock
async def test_reorder_pages_children_by_parent_slug() -> None:
    fake = FakeOutline()
    fake.install()
    await call(
        make_settings(default_site="demo"),
        "reorder_pages",
        ordered_ids=["b2", "b1"],
        parent="unit-one",
    )
    by_id = {entry["id"]: entry for entry in fake.outline_saves[0]["items"]}
    assert (by_id["b2"]["order"], by_id["b1"]["order"]) == (0, 1)
    assert (by_id["a"]["order"], by_id["b"]["order"], by_id["c"]["order"]) == (0, 1, 2)


@pytest.mark.parametrize(
    "ordered_ids",
    [
        ["a", "b"],  # a child missing
        ["a", "b", "c", "b1"],  # a page from another parent
        ["a", "b", "c", "zzz"],  # an unknown id
    ],
)
@respx.mock
async def test_reorder_pages_refuses_a_partial_list_without_saving(
    ordered_ids: list[str],
) -> None:
    fake = FakeOutline()
    fake.install()
    message = await call_error(
        make_settings(default_site="demo"), "reorder_pages", ordered_ids=ordered_ids
    )
    assert message.startswith("[INVALID_ARGUMENT] ordered_ids must list every child")
    assert "call get_outline" in message
    assert fake.outline_saves == []


@respx.mock
async def test_reorder_pages_unknown_parent_is_not_found() -> None:
    fake = FakeOutline()
    fake.install()
    message = await call_error(
        make_settings(default_site="demo"), "reorder_pages", ordered_ids=[], parent="ghost"
    )
    assert message.startswith("[NOT_FOUND] parent page 'ghost'")
    assert fake.outline_saves == []


# --- move_page / set_page_parent / normalize_slugs ------------------------------------------


@pytest.mark.parametrize(
    ("direction", "operation"),
    [("up", "moveUp"), ("DOWN", "moveDown"), (" indent ", "indent"), ("outdent", "outdent")],
)
@respx.mock
async def test_move_page_maps_directions_to_operations(direction: str, operation: str) -> None:
    fake = FakeOutline()
    fake.install()
    data = await call(
        make_settings(default_site="demo"), "move_page", page="b1", direction=direction
    )
    [(page, body)] = fake.item_patches
    assert page == "b1"
    assert body == {"site": {"name": "demo"}, "operation": operation}
    assert data["id"] == "b1"


@respx.mock
async def test_move_page_unknown_direction_never_writes() -> None:
    fake = FakeOutline()
    fake.install()
    message = await call_error(
        make_settings(default_site="demo"), "move_page", page="b1", direction="sideways"
    )
    assert (
        message
        == "[INVALID_ARGUMENT] unknown direction 'sideways'. use up, down, indent or outdent"
    )
    assert fake.item_patches == []


@respx.mock
async def test_set_page_parent_appends_after_new_siblings_by_default() -> None:
    fake = FakeOutline()
    fake.install()
    data = await call(
        make_settings(default_site="demo"), "set_page_parent", page="a", parent="unit-one"
    )
    [(page, body)] = fake.item_patches
    assert page == "a"
    # upstream defaults order to 0 (jump to top); the tool appends after b1(0), b2(1)
    assert body == {"site": {"name": "demo"}, "operation": "setParent", "parent": "b", "order": 2}
    assert data["parent"] == "b"


@respx.mock
async def test_set_page_parent_to_root_with_explicit_order() -> None:
    fake = FakeOutline()
    fake.install()
    await call(make_settings(default_site="demo"), "set_page_parent", page="b2", order=0)
    [(_, body)] = fake.item_patches
    assert body["parent"] is None
    assert body["order"] == 0


@pytest.mark.parametrize("preview", [True, False])
@respx.mock
async def test_normalize_slugs_forwards_preview(preview: bool) -> None:
    fake = FakeOutline()
    fake.install()
    data = await call(make_settings(default_site="demo"), "normalize_slugs", preview=preview)
    assert fake.normalize_bodies == [{"site": {"name": "demo"}, "preview": preview}]
    assert data["preview"] is preview
    assert data["skipped"] == ["b"]


# --- read-only gate -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("reorder_pages", {"ordered_ids": ["c", "b", "a"]}),
        ("move_page", {"page": "a", "direction": "down"}),
        ("set_page_parent", {"page": "a", "parent": "b"}),
        ("normalize_slugs", {"preview": False}),
    ],
)
@respx.mock
async def test_read_only_mode_blocks_outline_writes(tool: str, arguments: dict[str, Any]) -> None:
    fake = FakeOutline()
    fake.install()
    message = await call_error(
        make_settings(default_site="demo", read_only=True), tool, **arguments
    )
    assert message.startswith("[READ_ONLY]")
    assert fake.writes == 0


@respx.mock
async def test_read_only_mode_still_serves_get_outline() -> None:
    fake = FakeOutline()
    fake.install()
    data = await call(make_settings(default_site="demo", read_only=True), "get_outline")
    assert data["count"] == 5
