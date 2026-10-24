"""Unit tests for the block catalog (PLAN Phase 4 T4.4, §2.3).

Covers: the bundled catalog invariants (Appendix B coverage, categories, every
example_html passing its own validate contract), the haxProperties extraction helpers
(flat + legacy shapes, itemsList enums, unsetAttributes stripping), get/list/validate
semantics, and the best-effort live merge (blocks route, schemas fallback, wc-registry
last resort, 10-minute cache, silent degradation) via respx.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from lxml import html as lhtml

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.catalog.hax_properties import (
    attributes_from_settings,
    entry_from_hax_properties,
    example_from_demo_schema,
    kebab,
)
from haxcms_mcp.services.catalog.service import CatalogEntry, CatalogService

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
BLOCKS_RE = r".*/_sites/demo/x/api/v1/blocks/[a-z0-9-]+(\?|$)"
SCHEMAS_RE = r".*/_sites/demo/x/api/v1/schemas(\?|$)"
CE_RE = r".*/_sites/demo/x/api/v1/custom-elements/[a-z0-9-]+$"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

# PLAN Appendix B: the 31 custom Core Block tags the bundled catalog must cover
APPENDIX_B_TAGS = (
    "a11y-collapse",
    "accent-card",
    "audio-player",
    "block-quote",
    "citation-element",
    "code-sample",
    "fill-in-the-blanks",
    "flash-card",
    "grid-plate",
    "image-compare-slider",
    "image-gallery",
    "learning-component",
    "license-element",
    "lrndesign-timeline",
    "mark-the-words",
    "matching-question",
    "md-block",
    "media-image",
    "multiple-choice",
    "page-section",
    "place-holder",
    "self-check",
    "short-answer-question",
    "simple-cta",
    "sorting-question",
    "stop-note",
    "tagging-question",
    "true-false-question",
    "vocab-term",
    "video-player",
    "wikipedia-query",
)
CATEGORIES = {"text", "media", "layout", "assessment", "education", "reference", "embed"}


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


def envelope(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


def not_found(message: str = "Not found") -> httpx.Response:
    return httpx.Response(404, json={"status": 404, "data": {"message": message}})


# a flat-shape live schema with NO demoSchema (the merge must keep the bundled example)
LIVE_PROPS: dict[str, Any] = {
    "gizmo": {"title": "Live Self Check", "description": "Live description"},
    "settings": {
        "configure": [
            {"property": "liveAttr", "title": "Live attribute", "inputMethod": "textfield"},
            {
                "property": "mode",
                "title": "Mode",
                "inputMethod": "select",
                "options": {"a": "A", "b": "B"},
            },
            {"slot": "", "title": "Live body"},
        ]
    },
}


def example_root(example_html: str) -> Any:
    return lhtml.fragment_fromstring(example_html, create_parent="div")[0]


# --- bundled catalog invariants ---------------------------------------------------------------


def test_bundled_catalog_covers_appendix_b() -> None:
    service = CatalogService()
    assert set(service.bundled) == set(APPENDIX_B_TAGS)
    assert len(service.bundled) == 31


def test_bundled_entries_have_core_fields() -> None:
    for entry in CatalogService().bundled.values():
        assert entry.title, entry.tag
        assert entry.description, entry.tag
        assert entry.category in CATEGORIES, entry.tag
        assert entry.example_html, entry.tag


def test_bundled_category_assignments() -> None:
    bundled = CatalogService().bundled
    expected = {
        "media-image": "media",
        "video-player": "media",
        "grid-plate": "layout",
        "accent-card": "layout",
        "code-sample": "text",
        "self-check": "assessment",
        "multiple-choice": "assessment",
        "vocab-term": "education",
        "learning-component": "education",
        "citation-element": "reference",
        "block-quote": "reference",
        "wikipedia-query": "embed",
    }
    for tag, category in expected.items():
        assert bundled[tag].category == category


async def test_every_bundled_example_passes_validate() -> None:
    """The catalog's own contract: each example_html validates against its entry."""
    service = CatalogService()
    for entry in service.bundled.values():
        root = example_root(entry.example_html)
        assert root.tag == entry.tag, entry.tag
        result = await service.validate(root.tag, dict(root.attrib))
        assert result is not None, entry.tag


async def test_list_blocks_summaries() -> None:
    summaries = await CatalogService().list_blocks()
    assert [row["tag"] for row in summaries] == sorted(APPENDIX_B_TAGS)
    for row in summaries:
        assert set(row) == {"tag", "title", "description", "category"}


# --- get / validate semantics -----------------------------------------------------------------


async def test_get_returns_bundled_entry() -> None:
    entry = await CatalogService().get("media-image")
    assert entry.tag == "media-image"
    assert entry.title == "Enhanced Image"
    names = {attribute.name for attribute in entry.attributes}
    assert {"source", "alt", "caption", "citation", "size"} <= names


async def test_get_strips_and_lowercases_tag() -> None:
    entry = await CatalogService().get("  Media-Image ")
    assert entry.tag == "media-image"


async def test_get_native_tag_synthesizes_entry() -> None:
    entry = await CatalogService().get("p")
    assert entry.tag == "p"
    assert entry.category == "text"
    assert entry.description == "native HTML element"
    assert await CatalogService().get("H2") == await CatalogService().get("h2")


async def test_get_empty_tag_rejected() -> None:
    for bad in ("", "   "):
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await CatalogService().get(bad)
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


async def test_get_unknown_tag_lists_closest_matches() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await CatalogService().get("media-img")
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "media-image" in error.details["closest"]
    assert "media-image" in (error.hint or "")
    assert "list_blocks" in (error.hint or "")


async def test_get_block_schema_alias() -> None:
    service = CatalogService()
    assert await service.get_block_schema("grid-plate") == await service.get("grid-plate")


async def test_validate_native_tag_returns_none() -> None:
    assert await CatalogService().validate("p", {"anything": "goes"}) is None


async def test_validate_known_attributes_pass() -> None:
    service = CatalogService()
    entry = await service.validate(
        "media-image",
        {"source": "files/a.png", "alt": "A", "size": "small", "card": "card"},
    )
    assert isinstance(entry, CatalogEntry)
    assert entry.tag == "media-image"


async def test_validate_allows_universal_and_data_attributes() -> None:
    service = CatalogService()
    entry = await service.validate(
        "grid-plate", {"data-foo": "1", "slot": "col-1", "class": "c", "id": "i"}
    )
    assert entry is not None


async def test_validate_unknown_attribute_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await CatalogService().validate("media-image", {"sourc": "files/a.png"})
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "sourc" in error.message
    assert "source" in error.details["known"]


async def test_validate_enum_violation_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await CatalogService().validate("media-image", {"size": "huge"})
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert error.details["allowed"] == ["small", "wide"]
    assert "small" in (error.hint or "")


async def test_validate_kebab_normalizes_camel_case_names() -> None:
    service = CatalogService()
    entry = await service.validate("accent-card", {"accentColor": "red", "imageAlign": "left"})
    assert entry is not None
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await service.validate("accent-card", {"imageAlign": "sideways"})
    assert excinfo.value.details["attribute"] == "image-align"


async def test_validate_required_not_enforced() -> None:
    """`required` is documentation — the typed tools fill those; validate must not."""
    entry = await CatalogService().validate("media-image", {"alt": "only alt"})
    assert entry is not None


async def test_validate_skips_omitted_values() -> None:
    """None/False are omitted from the rendered block (build_block_html), so they carry
    nothing to check — the typed tools pass every parameter through as a dict."""
    service = CatalogService()
    entry = await service.validate(
        "media-image", {"source": "files/a.png", "size": None, "card": False, "sourc": None}
    )
    assert entry is not None and entry.tag == "media-image"


async def test_validate_without_attributes_returns_entry() -> None:
    entry = await CatalogService().validate("self-check")
    assert isinstance(entry, CatalogEntry)


# --- haxProperties extraction helpers ----------------------------------------------------------


def test_kebab() -> None:
    assert kebab("accentColor") == "accent-color"
    assert kebab("figureLabelTitle") == "figure-label-title"
    assert kebab("source") == "source"
    assert kebab("already-kebab") == "already-kebab"


def test_attributes_from_settings_flat_shape() -> None:
    props = {
        "saveOptions": {"unsetAttributes": ["stripped-me"]},
        "settings": {
            "configure": [
                {
                    "property": "accentColor",
                    "title": "Color",
                    "description": "Pick a color",
                    "inputMethod": "select",
                    "options": {"red": "Red", "blue": "Blue"},
                    "required": True,
                },
                {"property": "accentColor", "title": "dup", "inputMethod": "textfield"},
                {"property": "_internal", "title": "nope", "inputMethod": "textfield"},
                {"property": "strippedMe", "title": "nope", "inputMethod": "textfield"},
                {"slot": "question", "title": "Question"},
                {"slot": "", "title": "Answer"},
            ],
            "advanced": [
                {"property": "zoom", "title": "Zoom", "inputMethod": "boolean"},
            ],
        },
    }
    attributes, slots = attributes_from_settings(props)
    assert [attribute["name"] for attribute in attributes] == ["accent-color", "zoom"]
    assert attributes[0]["enum"] == ["red", "blue"]
    assert attributes[0]["required"] is True
    assert attributes[0]["description"] == "Pick a color"
    assert attributes[1]["type"] == "boolean"
    assert slots == [
        {"name": "question", "description": "Question"},
        {"name": "default", "description": "Answer"},
    ]


def test_attributes_from_settings_legacy_shape() -> None:
    props = {
        "configure": {
            "settings": {
                "quick": [
                    {
                        "attribute": "title",
                        "title": "Title",
                        "inputMethod": "textfield",
                        "required": True,
                    }
                ],
                "advanced": [],
            }
        }
    }
    attributes, slots = attributes_from_settings(props)
    assert attributes == [
        {
            "name": "title",
            "type": "string",
            "required": True,
            "description": "Title",
        }
    ]
    assert slots == []


def test_attributes_from_settings_items_list_enum() -> None:
    props = {
        "settings": {
            "configure": [
                {
                    "property": "level",
                    "title": "Level",
                    "inputMethod": "radio",
                    "itemsList": [
                        {"value": "easy", "text": "Easy"},
                        {"value": "hard", "text": "Hard"},
                    ],
                }
            ]
        }
    }
    attributes, _ = attributes_from_settings(props)
    assert attributes[0]["enum"] == ["easy", "hard"]


def test_example_from_demo_schema() -> None:
    demo = [
        {
            "tag": "x-card",
            "properties": {
                "card": True,
                "off": False,
                "nothing": None,
                "structured": {"a": 1},
                "citation": 'Say "hi" & bye',
            },
            "content": "<p>Body</p>",
        }
    ]
    assert example_from_demo_schema("x-card", demo) == (
        '<x-card card="card" citation="Say &quot;hi&quot; &amp; bye"><p>Body</p></x-card>'
    )
    assert example_from_demo_schema("x-card", []) == ""
    assert example_from_demo_schema("x-card", "nope") == ""


def test_entry_from_hax_properties_rejects_non_dict() -> None:
    assert entry_from_hax_properties("x", None) is None
    assert entry_from_hax_properties("x", "nope") is None


# --- live merge ---------------------------------------------------------------------------------


@respx.mock
async def test_live_merge_blocks_route() -> None:
    mock_auth()
    blocks_route = respx.get(url__regex=BLOCKS_RE).mock(
        return_value=envelope({"tag": "self-check", "haxProperties": LIVE_PROPS})
    )
    schemas_route = respx.get(url__regex=SCHEMAS_RE).mock(return_value=envelope({}))

    bundled = CatalogService().bundled["self-check"]
    async with HaxcmsClient(make_settings()) as client:
        entry = await CatalogService(client).get("self-check", site="demo")

    assert blocks_route.call_count == 1
    assert schemas_route.call_count == 0  # blocks route answered; no fallback
    # live definitions win per name, bundled-only names survive the union ...
    names = [attribute.name for attribute in entry.attributes]
    bundled_names = {attribute.name for attribute in bundled.attributes}
    assert names[:2] == ["live-attr", "mode"]
    assert set(names) == {"live-attr", "mode"} | bundled_names
    assert entry.attributes[1].enum == ["a", "b"]
    slots = {slot.name: slot.description for slot in entry.slots}
    assert slots["default"] == "Live body"  # the live definition of a shared slot wins
    assert set(slots) == {"default", "question"}  # the bundled-only slot survives
    # ... but curated text fields and the bundled example stay (live has no demoSchema)
    assert entry.title == bundled.title == "Self Check"
    assert entry.description == bundled.description
    assert entry.category == "assessment"
    assert entry.agent_notes == bundled.agent_notes
    assert entry.example_html == bundled.example_html


@respx.mock
async def test_live_fallback_to_schemas_route() -> None:
    mock_auth()
    respx.get(url__regex=BLOCKS_RE).mock(return_value=envelope({"tag": "self-check"}))
    schemas_route = respx.get(url__regex=SCHEMAS_RE).mock(
        return_value=envelope({"schemas": [{"haxProperties": LIVE_PROPS}]})
    )

    async with HaxcmsClient(make_settings()) as client:
        entry = await CatalogService(client).get("self-check", site="demo")

    assert schemas_route.call_count == 1
    assert [attribute.name for attribute in entry.attributes][:2] == ["live-attr", "mode"]


@respx.mock
async def test_live_failure_degrades_to_bundled() -> None:
    mock_auth()
    respx.get(url__regex=BLOCKS_RE).mock(
        return_value=httpx.Response(500, json={"status": 500, "data": {"message": "boom"}})
    )
    respx.get(url__regex=SCHEMAS_RE).mock(return_value=not_found("no schemas route"))

    async with HaxcmsClient(make_settings()) as client:
        entry = await CatalogService(client).get("self-check", site="demo")

    assert entry == CatalogService().bundled["self-check"]


@respx.mock
async def test_live_results_cached_for_ten_minutes() -> None:
    mock_auth()
    blocks_route = respx.get(url__regex=BLOCKS_RE).mock(
        return_value=envelope({"tag": "self-check", "haxProperties": LIVE_PROPS})
    )
    respx.get(url__regex=SCHEMAS_RE).mock(return_value=envelope({}))

    async with HaxcmsClient(make_settings()) as client:
        service = CatalogService(client)
        first = await service.get("self-check", site="demo")
        second = await service.get("self-check", site="demo")

    assert first == second
    assert blocks_route.call_count == 1  # second call served from cache


@respx.mock
async def test_wc_registry_last_resort_for_unknown_tag() -> None:
    mock_auth()
    respx.get(url__regex=r".*/api/v1/blocks/my-widget(\?|$)").mock(
        return_value=not_found("unknown block")
    )
    respx.get(url__regex=SCHEMAS_RE).mock(return_value=not_found("no schemas route"))
    ce_route = respx.get(url__regex=CE_RE).mock(
        return_value=envelope({"tag": "my-widget", "url": "https://cdn.invalid/my-widget.js"})
    )

    async with HaxcmsClient(make_settings()) as client:
        service = CatalogService(client)
        entry = await service.get("my-widget", site="demo")
        assert await service.validate("my-widget", {"anything": "x"}, site="demo") is None

    assert ce_route.call_count == 1
    assert entry.category == "embed"
    assert entry.description == "custom element from the live wc-registry"


@respx.mock
async def test_unknown_tag_still_rejected_with_live_client() -> None:
    mock_auth()
    respx.get(url__regex=BLOCKS_RE).mock(return_value=not_found("unknown block"))
    respx.get(url__regex=SCHEMAS_RE).mock(return_value=not_found("no schemas route"))
    respx.get(url__regex=CE_RE).mock(return_value=not_found("not in registry"))

    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await CatalogService(client).get("nowhere-tag", site="demo")

    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
