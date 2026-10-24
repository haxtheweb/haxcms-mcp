"""Phase 3 integration tests: outline moves against the real HAXcms instance.

Covers the PLAN Phase 3 integration list: three pages driven through indent, outdent,
move up/down, set parent and a root-level reorder, asserting the outline tree after
every step.
"""

from __future__ import annotations

from typing import Any

import pytest

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.models.item import OutlineNode
from haxcms_mcp.services import outline as outline_service
from haxcms_mcp.services import pages as pages_service

pytestmark = pytest.mark.integration


def _tree(nodes: list[OutlineNode]) -> list[tuple[str, Any]]:
    """The outline as nested `(title, children)` tuples."""
    return [(node.item.title, _tree(node.children)) for node in nodes]


def _titles(nodes: list[OutlineNode]) -> list[str]:
    """Pre-order title walk of the outline."""
    return [item.title for item in outline_service.flatten(nodes)]


async def test_outline_moves(client: HaxcmsClient, site: str) -> None:
    initial = await outline_service.fetch_all_items(client, site)
    assert len(initial) == 1  # the create_site starter page
    first = initial[0]

    alpha = await pages_service.create_page(client, site, "Alpha")
    beta = await pages_service.create_page(client, site, "Beta")
    gamma = await pages_service.create_page(client, site, "Gamma")
    flat = [first.title, "Alpha", "Beta", "Gamma"]
    assert _titles(await outline_service.get_outline(client, site)) == flat

    # indent nests Gamma under its previous sibling Beta
    moved = await outline_service.move_page(client, site, gamma.id, "indent")
    assert moved.parent == beta.id
    assert moved.indent == 1
    nodes = await outline_service.get_outline(client, site)
    assert _tree(nodes) == [
        (first.title, []),
        ("Alpha", []),
        ("Beta", [("Gamma", [])]),
    ]

    # outdent lifts it back to the root, right after its parent
    moved = await outline_service.move_page(client, site, gamma.id, "outdent")
    assert moved.parent is None
    assert moved.indent == 0
    nodes = await outline_service.get_outline(client, site)
    assert _tree(nodes) == [(title, []) for title in flat]

    # move up swaps with the adjacent sibling; move down swaps back
    await outline_service.move_page(client, site, gamma.id, "up")
    assert _titles(await outline_service.get_outline(client, site)) == [
        first.title,
        "Alpha",
        "Gamma",
        "Beta",
    ]
    await outline_service.move_page(client, site, gamma.id, "down")
    assert _titles(await outline_service.get_outline(client, site)) == flat

    # set parent nests Gamma under Alpha (appended after the existing children)
    moved = await outline_service.set_page_parent(client, site, gamma.id, parent=alpha.id)
    assert moved.parent == alpha.id
    nodes = await outline_service.get_outline(client, site)
    assert _tree(nodes) == [
        (first.title, []),
        ("Alpha", [("Gamma", [])]),
        ("Beta", []),
    ]

    # back to the root level: appended at the end, after Beta
    moved = await outline_service.set_page_parent(client, site, gamma.id, parent=None)
    assert moved.parent is None
    assert _titles(await outline_service.get_outline(client, site)) == flat

    # reorder: the COMPLETE root child list in the new sequence
    nodes = await outline_service.reorder_pages(
        client, site, None, [gamma.id, alpha.id, first.id, beta.id]
    )
    assert _titles(nodes) == ["Gamma", "Alpha", first.title, "Beta"]
