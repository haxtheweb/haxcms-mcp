"""Phase 4 integration tests: the block operations against the live instance.

PLAN Phase 4 integration list: `test_p04_block_ops_live.py` (insert after text anchor,
replace by selector, remove, move, update attributes; revisions grow by one per op).
Every write goes through the real saveNode path — one git commit per operation, asserted
via `list_page_revisions` totals.
"""

from __future__ import annotations

import pytest

from haxcms_mcp.models.item import Item
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

SEED = "<p>Alpha paragraph.</p><p>Beta paragraph.</p><p>Gamma paragraph.</p>"
IMAGE_SEED = (
    '<p>Intro.</p><media-image source="files/a.png" alt="prairie path" caption="Cap"></media-image>'
)


async def _revision_total(mcp: McpTestClient, site: str, page: Item) -> int:
    result = await mcp.call("list_page_revisions", page=page.id, site=site)
    return int(result["total"])


async def _blocks(mcp: McpTestClient, site: str, page: Item) -> list[dict[str, object]]:
    result = await mcp.call("get_page_blocks", page=page.id, site=site)
    blocks: list[dict[str, object]] = result["blocks"]
    return blocks


async def test_insert_after_text_anchor(mcp: McpTestClient, site: str, page: Item) -> None:
    await mcp.call("set_page_content", page=page.id, html=SEED, site=site)
    before = await _revision_total(mcp, site, page)

    result = await mcp.call(
        "add_paragraph",
        page=page.id,
        text_or_html="Delta paragraph.",
        anchor="Beta paragraph",
        placement="after",
        site=site,
    )
    assert result["saved"] is True
    assert result["operation"] == "insert_block"
    assert result["affected"][0]["index"] == 2
    assert result["block_count"] == 4

    blocks = await _blocks(mcp, site, page)
    assert [block["text"] for block in blocks] == [
        "Alpha paragraph.",
        "Beta paragraph.",
        "Delta paragraph.",
        "Gamma paragraph.",
    ]
    assert await _revision_total(mcp, site, page) == before + 1


async def test_replace_by_selector(mcp: McpTestClient, site: str, page: Item) -> None:
    await mcp.call("set_page_content", page=page.id, html=IMAGE_SEED, site=site)
    before = await _revision_total(mcp, site, page)

    result = await mcp.call(
        "replace_block",
        page=page.id,
        anchor="media-image[alt*=prairie]",
        html="<h3>Replaced heading</h3>",
        site=site,
    )
    assert result["operation"] == "replace_block"
    assert result["affected"][0]["tag"] == "h3"
    assert result["affected"][0]["index"] == 1

    blocks = await _blocks(mcp, site, page)
    assert [block["tag"] for block in blocks] == ["p", "h3"]
    assert blocks[1]["text"] == "Replaced heading"
    assert await _revision_total(mcp, site, page) == before + 1


async def test_remove_block(mcp: McpTestClient, site: str, page: Item) -> None:
    await mcp.call("set_page_content", page=page.id, html=SEED, site=site)
    before = await _revision_total(mcp, site, page)

    result = await mcp.call("remove_block", page=page.id, anchor="Beta paragraph", site=site)
    assert result["operation"] == "remove_block"
    assert result["affected"][0]["index"] == 1  # the OLD index
    assert result["block_count"] == 2

    blocks = await _blocks(mcp, site, page)
    assert [block["text"] for block in blocks] == ["Alpha paragraph.", "Gamma paragraph."]
    assert await _revision_total(mcp, site, page) == before + 1


async def test_move_block(mcp: McpTestClient, site: str, page: Item) -> None:
    await mcp.call("set_page_content", page=page.id, html=SEED, site=site)
    before = await _revision_total(mcp, site, page)

    result = await mcp.call(
        "move_block",
        page=page.id,
        anchor="Alpha paragraph",
        target_anchor="Gamma paragraph",
        placement="after",
        site=site,
    )
    assert result["operation"] == "move_block"
    assert result["block_count"] == 3

    blocks = await _blocks(mcp, site, page)
    assert [block["text"] for block in blocks] == [
        "Beta paragraph.",
        "Gamma paragraph.",
        "Alpha paragraph.",
    ]
    assert await _revision_total(mcp, site, page) == before + 1


async def test_update_attributes_set_and_unset(mcp: McpTestClient, site: str, page: Item) -> None:
    await mcp.call("set_page_content", page=page.id, html=IMAGE_SEED, site=site)
    before = await _revision_total(mcp, site, page)

    result = await mcp.call(
        "update_block",
        page=page.id,
        anchor="media-image",
        set={"alt": "New alt", "size": "wide"},
        unset=["caption"],
        site=site,
    )
    assert result["operation"] == "update_block_attributes"
    attributes = result["affected"][0]["attributes"]
    assert attributes["alt"] == "New alt"
    assert attributes["size"] == "wide"
    assert "caption" not in attributes
    assert attributes["source"] == "files/a.png"  # untouched attributes survive

    got = await mcp.call("get_page_content", page=page.id, site=site)
    assert 'alt="New alt"' in got["html"]
    assert "caption" not in got["html"]
    assert await _revision_total(mcp, site, page) == before + 1
