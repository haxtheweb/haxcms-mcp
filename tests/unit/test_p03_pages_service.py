"""Unit tests for the pages service with respx (PLAN Phase 3 T3.4).

Focus per PLAN: operation sequencing order (setSlug LAST), the id-chaining that survives a
Pathauto slug change mid-sequence, and the NOT_FOUND "did you mean" suggestions. Response
bodies mirror the 26.8.1 route source shapes recorded in the service module docstring.
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
from haxcms_mcp.models.item import ItemCollection
from haxcms_mcp.models.revision import Revision, RevisionDetail
from haxcms_mcp.services import pages as pages_service

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ITEMS_URL = f"{BASE}/_sites/demo/x/api/v1/items"
ITEM_RE = r".*/_sites/demo/x/api/v1/items/[^/]+$"
# url__regex matches the FULL URL including the query string (the list call paginates)
REVISIONS_RE = r".*/_sites/demo/x/api/v1/items/[^/]+/revisions(\?|$)"
REVISION_RE = r".*/_sites/demo/x/api/v1/items/[^/]+/revisions/[a-fA-F0-9]+$"
RESTORE_RE = r".*/_sites/demo/x/api/v1/items/[^/]+/revisions/[a-fA-F0-9]+/restore$"
SEARCH_URL = f"{BASE}/_sites/demo/x/api/v1/search"
TAGS_URL = f"{BASE}/_sites/demo/x/api/v1/tags"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

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


def record(item_id: str, title: str = "Lesson", slug: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "slug": slug or item_id,
        "parent": None,
        "indent": 0,
        "order": 0,
        "metadata": {},
        **extra,
    }


def items_body(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": 200,
        "data": {
            "count": len(items),
            "total": len(items),
            "page": {"limit": 200, "offset": 0, "total": len(items)},
            "items": items,
        },
    }


def not_found(id_or_slug: str) -> httpx.Response:
    return httpx.Response(
        404,
        json={
            "status": 404,
            "data": {"message": f'Item not found for idOrSlug "{id_or_slug}"'},
        },
    )


# --- update_page_details: sequencing ---------------------------------------------------------


@respx.mock
async def test_update_page_details_sequences_operations_with_slug_last() -> None:
    mock_auth()
    calls: list[tuple[str, dict[str, Any]]] = []

    def patch_effect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path.rsplit("/", 1)[-1], body))
        data = record("item-1", title="Lesson 1", slug="lesson-1")
        if body["operation"] == "setTitle":
            data["title"] = body["title"]
            data["slug"] = "new-title"  # Pathauto regenerated it
        if body["operation"] == "setSlug":
            data["slug"] = body["slug"]
        return httpx.Response(200, json={"status": 200, "data": data})

    respx.patch(url__regex=ITEM_RE).mock(side_effect=patch_effect)

    async with HaxcmsClient(make_settings()) as client:
        item = await pages_service.update_page_details(
            client,
            "demo",
            "lesson-1",
            title="New Title",
            tags=["week-1"],
            published=False,
            slug="new-title",
        )

    assert [body["operation"] for _, body in calls] == [
        "setTitle",
        "setTags",
        "setPublished",
        "setSlug",  # LAST, so setTitle cannot overwrite it under Pathauto
    ]
    # the first PATCH uses the caller's handle; setTitle changed the slug, so the rest
    # chain onto the response id
    assert [target for target, _ in calls] == ["lesson-1", "item-1", "item-1", "item-1"]
    assert calls[0][1]["title"] == "New Title"
    assert calls[1][1]["tags"] == ["week-1"]
    assert calls[2][1]["published"] is False
    assert calls[3][1]["slug"] == "new-title"
    assert item.slug == "new-title"


@respx.mock
async def test_update_page_details_nothing_to_update_is_rejected() -> None:
    mock_auth()
    patch_route = respx.patch(url__regex=ITEM_RE).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-1")})
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.update_page_details(client, "demo", "item-1")

    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "nothing to update" in error.message
    assert "related_pages" in (error.hint or "")
    assert patch_route.call_count == 0


@respx.mock
async def test_update_page_details_rejects_blank_title_and_slug() -> None:
    mock_auth()
    patch_route = respx.patch(url__regex=ITEM_RE).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-1")})
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.update_page_details(client, "demo", "item-1", title="   ")
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.update_page_details(client, "demo", "item-1", slug="")
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert patch_route.call_count == 0


def test_build_detail_operations_full_order() -> None:
    operations = pages_service.build_detail_operations(
        title="T",
        slug="s",
        description="D",
        tags=["a"],
        published=False,
        locked=True,
        hide_in_menu=True,
        icon="hax:lesson",
        image="files/img.png",
        related_pages=["item-2"],
    )
    assert [entry["operation"] for entry in operations] == [
        "setTitle",
        "setDescription",
        "setTags",
        "setIcon",
        "setImage",
        "setRelatedItems",
        "setLocked",
        "setPublished",
        "setHideInMenu",
        "setSlug",
    ]
    by_operation = {entry["operation"]: entry for entry in operations}
    assert by_operation["setRelatedItems"]["relatedItems"] == ["item-2"]
    assert by_operation["setHideInMenu"]["hideInMenu"] is True
    assert by_operation["setPublished"]["published"] is False


# --- create_page / create_pages ---------------------------------------------------------------


@respx.mock
async def test_create_page_sends_the_single_form() -> None:
    mock_auth()
    respx.get(ITEMS_URL).mock(
        return_value=httpx.Response(200, json=items_body([record("item-unit-1", "Unit 1")]))
    )
    post_route = respx.post(ITEMS_URL).mock(
        return_value=httpx.Response(
            200, json={"status": 200, "data": record("item-new", "Lesson", "lesson")}
        )
    )
    patch_route = respx.patch(url__regex=ITEM_RE).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-new")})
    )

    async with HaxcmsClient(make_settings()) as client:
        item = await pages_service.create_page(
            client,
            "demo",
            " Lesson ",
            parent="item-unit-1",
            order=2,
            content_html="<p>Hi</p>",
            description="d",
            tags=["a"],
        )

    sent = json.loads(post_route.calls.last.request.content)
    assert sent["site"] == {"name": "demo"}
    assert sent["node"] == {
        "id": None,
        "title": "Lesson",
        "location": None,
        "duplicate": None,
        "contents": "<p>Hi</p>",
    }
    assert sent["parent"] == "item-unit-1"
    assert sent["order"] == 2
    assert sent["indent"] is None
    assert sent["description"] == "d"
    # itemFromParams REPLACES metadata wholesale, so published/tags ride in the body
    assert sent["metadata"] == {"published": True, "tags": ["a"]}
    assert item.id == "item-new"
    assert patch_route.call_count == 0  # no slug, published default: no follow-ups


@respx.mock
async def test_create_page_computes_the_append_order() -> None:
    """itemFromParams leaves an omitted order at 0 (live-verified tie) — the service
    computes the append position among the future siblings instead."""
    mock_auth()
    respx.get(ITEMS_URL).mock(
        return_value=httpx.Response(
            200,
            json=items_body(
                [
                    record("item-home", "Home", order=0),
                    record("item-a", "A", order=1),
                    record("item-child", "Child", parent="item-a", order=0),
                ]
            ),
        )
    )
    post_route = respx.post(ITEMS_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-new")})
    )

    async with HaxcmsClient(make_settings()) as client:
        # root level: appended after Home(0) and A(1); the nested Child(0) is no sibling
        await pages_service.create_page(client, "demo", "New")
        sent = json.loads(post_route.calls.last.request.content)
        assert sent["parent"] is None
        assert sent["order"] == 2

        # under a parent: appended after that parent's only child (order 0)
        await pages_service.create_page(client, "demo", "New", parent="item-a")
        sent = json.loads(post_route.calls.last.request.content)
        assert sent["parent"] == "item-a"
        assert sent["order"] == 1


@respx.mock
async def test_create_page_explicit_slug_uses_set_slug_followup() -> None:
    mock_auth()
    respx.get(ITEMS_URL).mock(return_value=httpx.Response(200, json=items_body([])))
    respx.post(ITEMS_URL).mock(
        return_value=httpx.Response(
            200, json={"status": 200, "data": record("item-new", "Lesson", "lesson")}
        )
    )

    def patch_effect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        data = record("item-new", "Lesson", body.get("slug", "lesson"))
        data["metadata"] = {"overridePathauto": True}
        return httpx.Response(200, json={"status": 200, "data": data})

    patch_route = respx.patch(url__regex=ITEM_RE).mock(side_effect=patch_effect)

    async with HaxcmsClient(make_settings()) as client:
        item = await pages_service.create_page(client, "demo", "Lesson", slug=" my-page ")

    body = json.loads(patch_route.calls.last.request.content)
    assert body["operation"] == "setSlug"  # the create form ignores slugs (Pathauto)
    assert body["slug"] == "my-page"
    assert patch_route.calls.last.request.url.path.endswith("/items/item-new")
    assert item.slug == "my-page"


@respx.mock
async def test_create_page_unpublished_sends_metadata_and_set_published() -> None:
    mock_auth()
    respx.get(ITEMS_URL).mock(return_value=httpx.Response(200, json=items_body([])))
    post_route = respx.post(ITEMS_URL).mock(
        return_value=httpx.Response(
            200, json={"status": 200, "data": record("item-new", "Draft", "draft")}
        )
    )
    patch_route = respx.patch(url__regex=ITEM_RE).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {**record("item-new", "Draft", "draft"), "published": False},
            },
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        item = await pages_service.create_page(client, "demo", "Draft", published=False)

    sent = json.loads(post_route.calls.last.request.content)
    assert sent["metadata"] == {"published": False}
    body = json.loads(patch_route.calls.last.request.content)
    assert body == {"site": {"name": "demo"}, "operation": "setPublished", "published": False}
    assert item.published is False


@respx.mock
async def test_create_page_empty_title_rejected_before_any_request() -> None:
    mock_auth()
    post_route = respx.post(ITEMS_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-new")})
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.create_page(client, "demo", "   ")

    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert post_route.call_count == 0


@respx.mock
async def test_create_page_resolves_parent_slug_and_rejects_unknown() -> None:
    mock_auth()
    respx.get(ITEMS_URL).mock(
        return_value=httpx.Response(
            200, json=items_body([record("item-unit-1", "Unit 1", "unit-1")])
        )
    )
    post_route = respx.post(ITEMS_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-new")})
    )

    async with HaxcmsClient(make_settings()) as client:
        await pages_service.create_page(client, "demo", "Lesson", parent="unit-1")
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.create_page(client, "demo", "Lesson", parent="nope")

    sent = json.loads(post_route.calls.last.request.content)
    assert sent["parent"] == "item-unit-1"  # slug resolved to the id
    assert excinfo.value.code is ErrorCode.NOT_FOUND
    assert post_route.call_count == 1  # the unknown parent never reached the POST


@respx.mock
async def test_create_pages_fills_ids_and_slugs_then_relists() -> None:
    mock_auth()
    captured: dict[str, Any] = {}

    def post_effect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["items"] = body["items"]
        last = body["items"][-1]  # bulk responds with the LAST created item only
        return httpx.Response(
            200, json={"status": 200, "data": record(str(last["id"]), str(last["title"]))}
        )

    def get_effect(request: httpx.Request) -> httpx.Response:
        records = [
            {
                **record(str(entry["id"]), str(entry["title"]), str(entry.get("slug", ""))),
                "order": index,
                "content": entry.get("content"),
            }
            for index, entry in enumerate(captured.get("items", []))
        ]
        return httpx.Response(200, json=items_body(records))

    respx.post(ITEMS_URL).mock(side_effect=post_effect)
    respx.get(ITEMS_URL).mock(side_effect=get_effect)

    async with HaxcmsClient(make_settings()) as client:
        created = await pages_service.create_pages(
            client,
            "demo",
            [
                {"title": "Lesson A", "id": "item-a", "content": "<p>A</p>"},
                {"title": "Lesson B", "parent": "item-a"},
            ],
        )

    sent = captured["items"]
    assert sent[0]["id"] == "item-a"  # client ids are honoured (addPage)
    assert sent[0]["slug"] == "lesson-a"  # upstream would default to 'welcome'
    assert sent[0]["content"] == "<p>A</p>"
    assert sent[1]["id"].startswith("item-") and sent[1]["id"] != "item-a"
    assert sent[1]["slug"] == "lesson-b"
    assert sent[1]["parent"] == "item-a"
    assert [item.id for item in created] == ["item-a", sent[1]["id"]]  # input order
    assert created[0].title == "Lesson A"


@respx.mock
async def test_create_pages_rejects_empty_and_titleless_entries() -> None:
    mock_auth()
    post_route = respx.post(ITEMS_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-x")})
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.create_pages(client, "demo", [])
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.create_pages(client, "demo", [{"slug": "no-title"}])
        assert "no title" in excinfo.value.message
    assert post_route.call_count == 0


# --- find_page / list_pages / delete_page -------------------------------------------------------


@respx.mock
async def test_find_page_returns_the_record() -> None:
    mock_auth()
    respx.get(url__regex=ITEM_RE).mock(
        return_value=httpx.Response(
            200, json={"status": 200, "data": record("item-1", "Lesson 1", "lesson-1")}
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        item = await pages_service.find_page(client, "demo", "lesson-1")

    assert item.id == "item-1"


@respx.mock
async def test_find_page_suggests_near_slugs_on_a_miss() -> None:
    mock_auth()
    respx.get(url__regex=ITEM_RE).mock(side_effect=lambda request: not_found("unit-1/lesson-12"))
    manifest = [
        record("item-home", "Welcome", "welcome"),
        record("item-u1", "Unit 1", "unit-1"),
        record("item-l11", "Lesson 1.1", "unit-1/lesson-11"),
    ]
    respx.get(ITEMS_URL).mock(return_value=httpx.Response(200, json=items_body(manifest)))

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.find_page(client, "demo", "unit-1/lesson-12")

    error = excinfo.value
    assert error.code is ErrorCode.NOT_FOUND
    assert "unit-1/lesson-11" in (error.hint or "")  # the near miss is suggested


@respx.mock
async def test_list_pages_builds_query_params_and_clamps_limit() -> None:
    mock_auth()
    route = respx.get(ITEMS_URL).mock(
        return_value=httpx.Response(200, json=items_body([record("item-1")]))
    )

    async with HaxcmsClient(make_settings()) as client:
        collection = await pages_service.list_pages(
            client,
            "demo",
            parent="item-unit-1",
            tags=["Week-1"],
            published=False,
            page_type="lesson",
            include_content=True,
            limit=500,
            offset=20,
        )

    params = route.calls.last.request.url.params
    assert params["filter.parent"] == "item-unit-1"
    assert params["filter.tags"] == "Week-1"  # CSV; matched lowercase upstream
    assert params["filter.published"] == "0"  # parseBooleanFromInput accepts 0/false/no/off
    assert params["filter.pageType"] == "lesson"
    assert params["include"] == "content"
    assert params["page.limit"] == "200"  # clamped to the paginateRecords maximum
    assert params["page.offset"] == "20"
    assert isinstance(collection, ItemCollection)
    assert collection.items[0].id == "item-1"


@respx.mock
async def test_list_pages_depth_without_ancestor_is_rejected() -> None:
    mock_auth()
    route = respx.get(ITEMS_URL).mock(return_value=httpx.Response(200, json=items_body([])))

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.list_pages(client, "demo", depth=2)

    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert route.call_count == 0  # upstream would silently ignore the filter


@respx.mock
async def test_delete_page_finds_then_deletes() -> None:
    mock_auth()
    respx.get(url__regex=ITEM_RE).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-l11")})
    )
    delete_route = respx.delete(url__regex=ITEM_RE).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": record("item-l11")})
    )

    async with HaxcmsClient(make_settings()) as client:
        deleted = await pages_service.delete_page(client, "demo", "item-l11")

    assert deleted.id == "item-l11"
    assert delete_route.calls.last.request.url.path.endswith("/items/item-l11")
    assert json.loads(delete_route.calls.last.request.content) == {"site": {"name": "demo"}}


# --- revisions ----------------------------------------------------------------------------------


@respx.mock
async def test_list_page_revisions_maps_records() -> None:
    mock_auth()
    respx.get(url__regex=REVISIONS_RE).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "nodeId": "item-1",
                    "nodeSlug": "lesson-1",
                    "nodeTitle": "Lesson 1",
                    "count": 1,
                    "total": 1,
                    "page": {"limit": 25, "offset": 0, "total": 1},
                    "revisions": [REVISION_RECORD],
                },
            },
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        result = await pages_service.list_page_revisions(client, "demo", "item-1")

    assert result["node_id"] == "item-1"
    assert result["total"] == 1
    revisions = result["revisions"]
    assert isinstance(revisions, list) and isinstance(revisions[0], Revision)
    assert revisions[0].short_hash == "a" * 7


@respx.mock
async def test_revision_routes_reject_non_hashes_before_any_request() -> None:
    mock_auth()
    get_route = respx.get(url__regex=REVISION_RE).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {}})
    )
    restore_route = respx.post(url__regex=RESTORE_RE).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {}})
    )

    async with HaxcmsClient(make_settings()) as client:
        for bad in ("2", "xyz1234", "a" * 65, ""):
            with pytest.raises(HaxcmsMcpError) as excinfo:
                await pages_service.get_page_revision(client, "demo", "item-1", bad)
            assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
            assert "git hash" in (excinfo.value.hint or "")
        with pytest.raises(HaxcmsMcpError):
            await pages_service.restore_page_revision(client, "demo", "item-1", "revision-2")

    assert get_route.call_count == 0
    assert restore_route.call_count == 0


@respx.mock
async def test_get_page_revision_returns_the_detail() -> None:
    mock_auth()
    route = respx.get(url__regex=REVISION_RE).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "nodeId": "item-1",
                    "nodeSlug": "lesson-1",
                    "nodeTitle": "Lesson 1",
                    "revision": REVISION_RECORD,
                    "content": "<p>Old body</p>",
                },
            },
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        detail = await pages_service.get_page_revision(client, "demo", "item-1", "a" * 40)

    assert isinstance(detail, RevisionDetail)
    assert detail.content == "<p>Old body</p>"
    assert route.calls.last.request.url.path.endswith(f"/revisions/{'a' * 40}")


@respx.mock
async def test_restore_page_revision_maps_the_response() -> None:
    mock_auth()
    route = respx.post(url__regex=RESTORE_RE).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "nodeId": "item-1",
                    "nodeSlug": "lesson-1",
                    "nodeTitle": "Lesson 1",
                    "restoredFromHash": "a" * 40,
                    "jsonVariantLocation": "pages/item-1/index.json",
                    "hasItemMetadata": True,
                    "itemMetadataRestored": True,
                },
            },
        )
    )

    async with HaxcmsClient(make_settings()) as client:
        result = await pages_service.restore_page_revision(client, "demo", "item-1", "a" * 40)

    assert result == {
        "node_id": "item-1",
        "node_slug": "lesson-1",
        "node_title": "Lesson 1",
        "restored_from_hash": "a" * 40,
        "json_variant_location": "pages/item-1/index.json",
        "has_item_metadata": True,
        "item_metadata_restored": True,
    }
    assert json.loads(route.calls.last.request.content) == {"site": {"name": "demo"}}


# --- search and tags ------------------------------------------------------------------------------


@respx.mock
async def test_search_site_validates_the_query() -> None:
    mock_auth()
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {}})
    )

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.search_site(client, "demo", "   ")
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await pages_service.search_site(client, "demo", "x" * 257)
        assert "too long" in excinfo.value.message
    assert route.call_count == 0


@respx.mock
async def test_search_site_passes_filters_and_returns_the_collection() -> None:
    mock_auth()
    body = {
        "count": 1,
        "total": 1,
        "page": {"limit": 10, "offset": 0},
        "results": [
            {
                "id": "item-1",
                "title": "Lesson 1",
                "slug": "lesson-1",
                "location": "pages/item-1/index.html",
                "score": 3,
                "snippet": "...design...",
                "matches": [{"field": "title", "index": 0, "length": 6}],
            }
        ],
    }
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": body})
    )

    async with HaxcmsClient(make_settings()) as client:
        result = await pages_service.search_site(
            client,
            "demo",
            " design ",
            tags=["week-1"],
            fields=["title", "content"],
            sort="-score",
            limit=10,
        )

    params = route.calls.last.request.url.params
    assert params["q"] == "design"  # trimmed
    assert params["filter.tags"] == "week-1"
    assert params["fields"] == "title,content"
    assert params["sort"] == "-score"
    assert params["page.limit"] == "10"
    assert result["results"][0]["score"] == 3


@respx.mock
async def test_list_tags_passes_the_collection_through() -> None:
    mock_auth()
    body = {
        "count": 2,
        "total": 2,
        "page": {"limit": 100, "offset": 0},
        "tags": [
            {"tag": "week-1", "count": 3},
            {"tag": "intro", "count": 1},
        ],
    }
    respx.get(TAGS_URL).mock(return_value=httpx.Response(200, json={"status": 200, "data": body}))

    async with HaxcmsClient(make_settings()) as client:
        result = await pages_service.list_tags(client, "demo")

    assert result == body
