"""Phase 3 integration tests: search and tags against the real HAXcms instance.

Search is a live case-insensitive substring scan over title/slug/description/tags/content
(search.js, read Phase 3 — no index lag). Note the `fields` quirk verified here: the CSV
both narrows the scanned fields AND projects the result records down to those keys
(`projectCollection`), so assertions on projected results only use requested keys.
"""

from __future__ import annotations

import pytest

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.services import pages as pages_service

pytestmark = pytest.mark.integration


async def test_search_and_tags(client: HaxcmsClient, site: str) -> None:
    quantum = await pages_service.create_page(
        client,
        site,
        "Quantum Widgets",
        description="An introduction to quantum widgetry",
        tags=["physics", "demo"],
        content_html="<p>The gizmo hums with zerptron energy.</p>",
    )
    await pages_service.create_page(client, site, "Cooking Recipes", tags=["demo"])

    # title/slug substring match, case-insensitive
    found = await pages_service.search_site(client, site, "QUANTUM")
    assert found["total"] == 1
    top = found["results"][0]
    assert top["id"] == quantum.id
    assert top["title"] == "Quantum Widgets"
    assert top["score"] >= 1
    assert top["matches"]
    assert top["snippet"]

    # a content-only word matches through the stored page body
    body_hits = await pages_service.search_site(client, site, "zerptron")
    assert [entry["title"] for entry in body_hits["results"]] == ["Quantum Widgets"]

    # fields narrows the scan: "widgetry" lives only in the description
    title_only = await pages_service.search_site(client, site, "widgetry", fields=["title"])
    assert title_only["total"] == 0
    described = await pages_service.search_site(
        client, site, "widgetry", fields=["title", "description"]
    )
    assert [entry["title"] for entry in described["results"]] == ["Quantum Widgets"]

    # the tags filter narrows the item set before matching
    tagged = await pages_service.search_site(client, site, "recipes", tags=["demo"])
    assert [entry["title"] for entry in tagged["results"]] == ["Cooking Recipes"]
    missed = await pages_service.search_site(client, site, "recipes", tags=["physics"])
    assert missed["total"] == 0

    # tag frequencies, most used first
    listing = await pages_service.list_tags(client, site)
    frequencies = {entry["tag"]: entry["count"] for entry in listing["tags"]}
    assert frequencies["demo"] == 2
    assert frequencies["physics"] == 1
    assert listing["tags"][0]["tag"] == "demo"
    assert listing["total"] == len(listing["tags"])
