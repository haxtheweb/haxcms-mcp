"""Unit tests for the content service and block operations (PLAN Phase 4 T4.3).

A stateful respx fake (GET items?include=content + PATCH content) stores the body each
save sends (envelope stripped, as upstream does), so multi-operation tests read back
what the previous operation wrote — the same read-modify-write loop the tools run.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.content.blocks import (
    insert_block,
    move_block,
    remove_block,
    replace_block,
    set_block_text,
    update_block_attributes,
    wrap_text_with_link,
)
from haxcms_mcp.services.content.service import get_page_blocks, get_page_content, set_page_content
from haxcms_mcp.services.locks import site_lock

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ITEMS_RE = r".*/_sites/demo/x/api/v1/items/[^/]+(\?|$)"
CONTENT_RE = r".*/_sites/demo/x/api/v1/content/[^/]+(\?|$)"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pages"

RECORD: dict[str, Any] = {
    "id": "item-1",
    "title": "Songlines",
    "slug": "songlines",
    "metadata": {"published": True},
}


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def make_client() -> HaxcmsClient:
    return HaxcmsClient(make_settings())


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"status": 200, "jwt": "jwt-1"},
            headers={"set-cookie": "haxcms_refresh_token=r1; Path=/; HttpOnly"},
        )
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


class FakeSite:
    """Stateful item/content endpoints; `body` is the stored page content."""

    def __init__(self, body: str, record: dict[str, Any] | None = None) -> None:
        self.record = dict(record or RECORD)
        self.body = body
        self.patches: list[dict[str, Any]] = []

    def install(self) -> None:
        def get_item(request: httpx.Request) -> httpx.Response:
            data = dict(self.record)
            if "include=content" in str(request.url):
                data["content"] = self.body
            return httpx.Response(200, json={"status": 200, "data": data})

        def patch_content(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.patches.append(payload)
            body = str(payload["body"])
            marker = "></page-break>"
            # upstream pageBreakParser: the stored content is what follows the envelope
            self.body = body.split(marker, 1)[1] if marker in body else body
            return httpx.Response(200, json={"status": 200, "data": dict(self.record)})

        respx.get(url__regex=ITEMS_RE).mock(side_effect=get_item)
        respx.patch(url__regex=CONTENT_RE).mock(side_effect=patch_content)

    @property
    def last_body(self) -> str:
        return str(self.patches[-1]["body"])

    @property
    def last_schema(self) -> Any:
        return self.patches[-1].get("schema")


# --- reads ----------------------------------------------------------------------------------


@respx.mock
async def test_get_page_content_returns_record_html_and_blocks() -> None:
    mock_auth()
    FakeSite("<p>One.</p><p>Two.</p>").install()
    content = await get_page_content(make_client(), "demo", "songlines")
    assert content.item.title == "Songlines"
    assert content.html == "<p>One.</p><p>Two.</p>"
    assert [(block.index, block.tag, block.text) for block in content.blocks] == [
        (0, "p", "One."),
        (1, "p", "Two."),
    ]


@respx.mock
async def test_get_page_blocks_shortcut() -> None:
    mock_auth()
    FakeSite(fixture("tutorial_finished")).install()
    blocks = await get_page_blocks(make_client(), "demo", "songlines")
    assert len(blocks) == 12
    assert blocks[10].tag == "video-player"


# --- set_page_content --------------------------------------------------------------------------


@respx.mock
async def test_set_page_content_envelope_schema_and_reread() -> None:
    mock_auth()
    fake = FakeSite("<p>Old.</p>")
    fake.install()
    result = await set_page_content(
        make_client(),
        "demo",
        "songlines",
        '<media-image source="files/a.png"></media-image><p>New.</p>',
    )
    body = fake.last_body
    assert body.startswith('<page-break item-id="item-1" title="Songlines"')
    assert body.endswith(
        '></page-break><media-image source="files/a.png"></media-image>\n<p>New.</p>'
    )
    # the media schema is recomputed from the very body saved (saveNode resets
    # metadata.images/videos on every save)
    assert fake.last_schema == [{"tag": "media-image", "properties": {"source": "files/a.png"}}]
    # the result is the RE-GET state: the fake serves the stored body back
    assert result.item.id == "item-1"
    assert [block.tag for block in result.blocks] == ["media-image", "p"]


@respx.mock
async def test_set_page_content_strips_user_supplied_page_break() -> None:
    mock_auth()
    fake = FakeSite("<p>Old.</p>")
    fake.install()
    await set_page_content(
        make_client(),
        "demo",
        "songlines",
        '<page-break title="Evil"></page-break><p>Kept.</p>',
    )
    # the envelope save_content prepends must be the ONLY page-break upstream sees
    assert fake.last_body.count("<page-break") == 1
    assert "Evil" not in fake.last_body
    assert "<p>Kept.</p>" in fake.last_body


# --- insert_block -------------------------------------------------------------------------------


@respx.mock
async def test_insert_block_appends_by_default() -> None:
    mock_auth()
    fake = FakeSite("<p>One.</p>")
    fake.install()
    result = await insert_block(make_client(), "demo", "songlines", "<h2>Added</h2>")
    assert result.operation == "insert_block"
    assert result.saved is True
    assert result.block_count == 2
    assert [(block.index, block.tag, block.text) for block in result.affected] == [
        (1, "h2", "Added")
    ]
    assert fake.body == "<p>One.</p>\n<h2>Added</h2>"


@respx.mock
async def test_insert_block_prepend() -> None:
    mock_auth()
    fake = FakeSite("<p>One.</p>")
    fake.install()
    result = await insert_block(
        make_client(), "demo", "songlines", "<h2>Top</h2>", placement="prepend"
    )
    assert [block.index for block in result.affected] == [0]
    assert fake.body == "<h2>Top</h2>\n<p>One.</p>"


@respx.mock
async def test_insert_block_relative_to_anchor() -> None:
    mock_auth()
    fake = FakeSite("<p>Alpha</p><p>Beta</p><p>Alpha</p>")
    fake.install()
    client = make_client()
    # capitalised text is never a selector: auto-detection picks the text kind
    await insert_block(
        client,
        "demo",
        "songlines",
        "<h2>X</h2>",
        anchor="Alpha",
        occurrence="last",
        placement="after",
    )
    assert fake.body == "<p>Alpha</p>\n<p>Beta</p>\n<p>Alpha</p>\n<h2>X</h2>"
    # the next operation reads back what the previous one saved
    await insert_block(client, "demo", "songlines", "<h2>Y</h2>", anchor="Beta", placement="before")
    assert fake.body == "<p>Alpha</p>\n<h2>Y</h2>\n<p>Beta</p>\n<p>Alpha</p>\n<h2>X</h2>"


@respx.mock
async def test_insert_block_multiple_elements() -> None:
    mock_auth()
    fake = FakeSite("<p>One.</p>")
    fake.install()
    result = await insert_block(
        make_client(), "demo", "songlines", "<p>a</p><p>b</p>", placement="prepend"
    )
    assert [block.index for block in result.affected] == [0, 1]
    assert result.block_count == 3
    assert fake.body == "<p>a</p>\n<p>b</p>\n<p>One.</p>"


async def test_insert_block_placement_validation() -> None:
    client = make_client()
    with pytest.raises(HaxcmsMcpError) as info:
        await insert_block(client, "demo", "s", "<p>x</p>", placement="after")
    assert info.value.code is ErrorCode.INVALID_ARGUMENT
    assert "requires an anchor" in info.value.message
    with pytest.raises(HaxcmsMcpError) as info:
        await insert_block(client, "demo", "s", "<p>x</p>", anchor="p", placement="append")
    assert "takes no anchor" in info.value.message
    with pytest.raises(HaxcmsMcpError) as info:
        await insert_block(client, "demo", "s", "<p>x</p>", placement="sideways")
    assert "invalid placement" in info.value.message


async def test_insert_block_empty_html_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as info:
        await insert_block(make_client(), "demo", "s", "   ")
    assert info.value.code is ErrorCode.INVALID_ARGUMENT


# --- replace / remove ----------------------------------------------------------------------------


@respx.mock
async def test_replace_block() -> None:
    mock_auth()
    fake = FakeSite("<p>A</p><h2>Old</h2><p>B</p>")
    fake.install()
    result = await replace_block(
        make_client(),
        "demo",
        "songlines",
        "<media-image source='x.png'></media-image>",
        anchor="h2",
    )
    assert result.operation == "replace_block"
    assert result.block_count == 3
    assert [(block.index, block.tag) for block in result.affected] == [(1, "media-image")]
    assert "<h2>" not in fake.body
    assert fake.last_schema == [{"tag": "media-image", "properties": {"source": "x.png"}}]


@respx.mock
async def test_remove_block_reports_old_index() -> None:
    mock_auth()
    fake = FakeSite("<p>A</p><h2>Gone</h2><p>B</p>")
    fake.install()
    result = await remove_block(make_client(), "demo", "songlines", "Gone")
    assert result.operation == "remove_block"
    assert result.block_count == 2
    assert [(block.index, block.tag, block.text) for block in result.affected] == [
        (1, "h2", "Gone")
    ]
    assert fake.body == "<p>A</p>\n<p>B</p>"


@respx.mock
async def test_anchor_not_found_aborts_before_save() -> None:
    mock_auth()
    fake = FakeSite("<p>A</p>")
    fake.install()
    with pytest.raises(HaxcmsMcpError) as info:
        await remove_block(make_client(), "demo", "songlines", "missing text")
    assert info.value.code is ErrorCode.ANCHOR_NOT_FOUND
    assert fake.patches == []  # nothing was written


# --- move_block -----------------------------------------------------------------------------------


@respx.mock
async def test_move_block_after_target() -> None:
    mock_auth()
    fake = FakeSite("<p>First para</p><p>Second para</p><p>Third para</p>")
    fake.install()
    result = await move_block(
        make_client(),
        "demo",
        "songlines",
        "First para",
        target_anchor="Third para",
        placement="after",
    )
    assert result.operation == "move_block"
    assert fake.body == "<p>Second para</p>\n<p>Third para</p>\n<p>First para</p>"
    assert [(block.index, block.text) for block in result.affected] == [(2, "First para")]


@respx.mock
async def test_move_block_target_resolved_after_removal() -> None:
    mock_auth()
    fake = FakeSite("<h2>one</h2><p>x</p><h2>two</h2>")
    fake.install()
    # the target resolves against the LIFTED list: the source must not match itself
    await move_block(
        make_client(),
        "demo",
        "songlines",
        "h2",
        occurrence="first",
        target_anchor="h2",
        target_occurrence="last",
        placement="after",
    )
    assert fake.body == "<p>x</p>\n<h2>two</h2>\n<h2>one</h2>"


@respx.mock
async def test_move_block_page_level_placements() -> None:
    mock_auth()
    fake = FakeSite("<p>Para a</p><p>Para b</p>")
    fake.install()
    await move_block(make_client(), "demo", "songlines", "Para b", placement="prepend")
    assert fake.body == "<p>Para b</p>\n<p>Para a</p>"
    await move_block(make_client(), "demo", "songlines", "Para b", placement="append")
    assert fake.body == "<p>Para a</p>\n<p>Para b</p>"


async def test_move_block_relative_requires_target() -> None:
    client = make_client()
    with pytest.raises(HaxcmsMcpError) as info:
        await move_block(client, "demo", "s", "a", placement="after")
    assert info.value.code is ErrorCode.INVALID_ARGUMENT
    with pytest.raises(HaxcmsMcpError):
        await move_block(client, "demo", "s", "a", target_anchor="b", placement="append")


# --- attributes and text ----------------------------------------------------------------------


@respx.mock
async def test_update_block_attributes_set_and_unset() -> None:
    mock_auth()
    fake = FakeSite('<media-image source="a.png" size="wide" alt="x"></media-image>')
    fake.install()
    result = await update_block_attributes(
        make_client(),
        "demo",
        "songlines",
        "media-image",
        set={"card": "card", "size": "full"},
        unset=["alt"],
    )
    assert result.affected[0].attributes == {
        "source": "a.png",
        "size": "full",
        "card": "card",
    }
    assert 'card="card"' in fake.body and "alt" not in fake.body


async def test_update_block_attributes_validation() -> None:
    client = make_client()
    with pytest.raises(HaxcmsMcpError) as info:
        await update_block_attributes(client, "demo", "s", "p")
    assert info.value.code is ErrorCode.INVALID_ARGUMENT
    assert "nothing to update" in info.value.message
    with pytest.raises(HaxcmsMcpError):
        await update_block_attributes(client, "demo", "s", "p", set={"bad name": "x"})
    with pytest.raises(HaxcmsMcpError):
        await update_block_attributes(client, "demo", "s", "p", unset=['q"'])


@respx.mock
async def test_set_block_text_keeps_tag_and_attributes() -> None:
    mock_auth()
    FakeSite('<h2 class="x">Old <em>markup</em> text</h2>').install()
    result = await set_block_text(make_client(), "demo", "songlines", "h2", "Plain <new> text")
    assert result.affected[0].html == '<h2 class="x">Plain &lt;new&gt; text</h2>'


@respx.mock
async def test_set_block_text_preserves_slotted_children() -> None:
    mock_auth()
    FakeSite(
        '<self-check title="Check"><p slot="question">Which?</p><p>Old answer</p></self-check>'
    ).install()
    result = await set_block_text(make_client(), "demo", "songlines", "self-check", "New answer")
    html = result.affected[0].html
    assert '<p slot="question">Which?</p>' in html
    assert "Old answer" not in html
    assert html.startswith('<self-check title="Check">New answer')


# --- wrap_text_with_link ------------------------------------------------------------------------


@respx.mock
async def test_wrap_text_with_link() -> None:
    mock_auth()
    FakeSite("<p>Noticing is the first act. Watch it here.</p><p>Other</p>").install()
    result = await wrap_text_with_link(
        make_client(),
        "demo",
        "songlines",
        anchor="Noticing",
        text="Watch it here.",
        url="https://example.com/lecture",
    )
    assert result.operation == "wrap_text_with_link"
    assert result.affected[0].html == (
        '<p>Noticing is the first act. <a href="https://example.com/lecture">Watch it here.</a></p>'
    )


@respx.mock
async def test_wrap_text_with_link_in_tail_and_new_tab() -> None:
    mock_auth()
    FakeSite('<p>Text with <img src="a.png"> inside.</p>').install()
    result = await wrap_text_with_link(
        make_client(),
        "demo",
        "songlines",
        anchor="p",
        text="inside.",
        url="https://x.dev",
        new_tab=True,
    )
    assert result.affected[0].html == (
        '<p>Text with <img src="a.png"> <a href="https://x.dev" target="_blank">inside.</a></p>'
    )


@respx.mock
async def test_wrap_text_with_link_not_found_in_block() -> None:
    mock_auth()
    fake = FakeSite("<p>Something else</p>")
    fake.install()
    with pytest.raises(HaxcmsMcpError) as info:
        await wrap_text_with_link(
            make_client(), "demo", "songlines", anchor="p", text="missing", url="https://x.dev"
        )
    assert info.value.code is ErrorCode.INVALID_ARGUMENT
    assert info.value.details is not None
    assert info.value.details["block"]["tag"] == "p"
    assert fake.patches == []


async def test_wrap_text_with_link_validation() -> None:
    client = make_client()
    with pytest.raises(HaxcmsMcpError):
        await wrap_text_with_link(client, "demo", "s", anchor="p", text="  ", url="https://x")
    with pytest.raises(HaxcmsMcpError):
        await wrap_text_with_link(client, "demo", "s", anchor="p", text="x", url="")


# --- result shape and locks ---------------------------------------------------------------------


@respx.mock
async def test_block_op_result_carries_page_identity() -> None:
    mock_auth()
    FakeSite("<p>A</p>").install()
    result = await insert_block(make_client(), "demo", "songlines", "<p>B</p>")
    assert result.site == "demo"
    assert result.page_id == "item-1"
    assert result.page_slug == "songlines"
    assert result.saved is True


@respx.mock
async def test_operations_on_tutorial_fixture() -> None:
    mock_auth()
    fake = FakeSite(fixture("tutorial_finished"))
    fake.install()
    client = make_client()
    await insert_block(
        client,
        "demo",
        "songlines",
        '<stop-note title="Pause"></stop-note>',
        anchor="The prairie does not announce",
        placement="after",
    )
    blocks = await get_page_blocks(client, "demo", "songlines")
    assert [block.tag for block in blocks][5:8] == ["h2", "p", "stop-note"]
    # the schema still carries every media block of the body
    assert fake.last_schema == [
        {"tag": "media-image", "properties": {"source": "files/Songline_1.png"}},
        {"tag": "media-image", "properties": {"source": "files/Songline_2.png"}},
        {
            "tag": "video-player",
            "properties": {"source": "https://www.youtube.com/watch?v=prairie-walk"},
        },
    ]


async def test_site_lock_serialises_writers() -> None:
    order: list[str] = []

    async def writer(name: str) -> None:
        async with site_lock("lock-test-site"):
            order.append(f"{name}-start")
            await asyncio.sleep(0.01)
            order.append(f"{name}-end")

    await asyncio.gather(writer("a"), writer("b"))
    assert order == ["a-start", "a-end", "b-start", "b-end"]
