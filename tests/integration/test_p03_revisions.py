"""Phase 3 integration tests: git-backed page revisions against the real instance.

Covers the PLAN Phase 3 integration list: two content saves via raw `PATCH content` with a
minimal Page Break body (API-REF §5.2 — without the `<page-break>` prefix the parser writes
nothing and still returns 200), the revision list showing both commits, reading one
revision's content, and restoring the first save (the restore lands as a new commit).
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.client.envelope import unwrap_dict
from haxcms_mcp.models.item import Item
from haxcms_mcp.services import pages as pages_service

pytestmark = pytest.mark.integration

FIRST = "<p>First version text.</p>"
SECOND = "<p>Second version text.</p>"


def _page_break(item: Item) -> str:
    """The minimal Page Break the saveNode parser requires; boolean flags need values."""
    return (
        f'<page-break item-id="{item.id}" title="{item.title}" slug="{item.slug}"'
        ' published="published"></page-break>'
    )


async def _save_content(client: HaxcmsClient, site: str, item: Item, body: str) -> None:
    await client.request(
        "PATCH",
        client.site_path(site, f"content/{quote(item.id, safe='')}"),
        json={"site": {"name": site}, "body": _page_break(item) + body},
        auth="bearer+site",
        site=site,
    )


async def _read_content(client: HaxcmsClient, site: str, item_id: str) -> str:
    # format=json: the route wraps `format=html` responses in a <pre> envelope (live run)
    response = await client.request(
        "GET",
        client.site_path(site, f"content/{quote(item_id, safe='')}"),
        params={"format": "json"},
        auth="bearer",
    )
    return str(unwrap_dict(response)["body"])


async def test_revisions_list_get_restore(client: HaxcmsClient, site: str, page: Item) -> None:
    await _save_content(client, site, page, FIRST)
    await _save_content(client, site, page, SECOND)
    assert "Second version text." in await _read_content(client, site, page.id)

    result = await pages_service.list_page_revisions(client, site, page.id)
    assert result["node_id"] == page.id
    revisions = result["revisions"]
    assert len(revisions) == result["count"]
    assert len(revisions) >= 2  # the two saves (the create may add a third commit)

    # newest first: walk down to the revision holding the FIRST save
    first_hash: str | None = None
    for revision in revisions:
        detail = await pages_service.get_page_revision(client, site, page.id, revision.hash)
        assert detail.node_id == page.id
        if "First version text." in detail.content:
            first_hash = revision.hash
            break
    assert first_hash is not None, "the first content save produced no revision"

    restored = await pages_service.restore_page_revision(client, site, page.id, first_hash)
    assert restored["node_id"] == page.id
    assert restored["restored_from_hash"] == first_hash

    body = await _read_content(client, site, page.id)
    assert "First version text." in body
    assert "Second version text." not in body
