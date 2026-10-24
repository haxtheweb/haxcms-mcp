"""Phase 4 integration tests: read every resource against the live instance.

PLAN Phase 4 integration list: `test_p04_resources.py` (read each resource) — the six
Phase 4 URIs (PLAN L1211): the catalog list, one merged catalog record (bundled-only and
live-merged through a Default Site), the sites list, one site summary, the outline as
indented text + JSON, and a page's content HTML with block-index comments.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from mcp.shared.exceptions import MCPError

from haxcms_mcp.config import Settings
from haxcms_mcp.models.item import Item
from haxcms_mcp.server import build_server
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

CATALOG_TEMPLATES = {
    "haxcms://catalog/blocks/{tag}",
    "haxcms://sites/{site}",
    "haxcms://sites/{site}/outline",
    "haxcms://sites/{site}/pages/{id_or_slug}",
}


async def test_resources_and_templates_are_listed(mcp: McpTestClient) -> None:
    resources = await mcp.client.list_resources()
    uris = {str(resource.uri) for resource in resources}
    assert {"haxcms://catalog/blocks", "haxcms://sites"} <= uris
    templates = await mcp.client.list_resource_templates()
    assert {str(t.uri_template) for t in templates} >= CATALOG_TEMPLATES


async def test_catalog_blocks_resource(mcp: McpTestClient) -> None:
    rows = json.loads(await mcp.read_resource("haxcms://catalog/blocks"))
    assert len(rows) == 31  # the bundled Appendix B catalog
    assert set(rows[0]) == {"tag", "title", "description", "category"}
    tags = [row["tag"] for row in rows]
    assert tags == sorted(tags)
    assert "media-image" in tags and "self-check" in tags


async def test_catalog_block_resource_merged_record(mcp: McpTestClient) -> None:
    entry = json.loads(await mcp.read_resource("haxcms://catalog/blocks/self-check"))
    assert entry["tag"] == "self-check"
    assert entry["category"] == "assessment"
    names = {attribute["name"] for attribute in entry["attributes"]}
    assert {"accent-color", "image", "alt"} <= names
    assert entry["example_html"].startswith("<self-check")


async def test_catalog_block_resource_unknown_tag(mcp: McpTestClient) -> None:
    # a failed resource read surfaces as a wire MCPError whose message keeps the
    # HaxcmsMcpError formatted form ([CODE] message. hint)
    with pytest.raises(MCPError, match="unknown block tag"):
        await mcp.read_resource("haxcms://catalog/blocks/nope-not-a-tag")


async def test_catalog_block_resource_live_merge_with_default_site(
    haxcms: HaxcmsRuntime, site: str
) -> None:
    """With a Default Site the record goes through the live merge (or its silent
    degradation) on the real instance — the entry must stay complete either way."""
    settings = Settings(
        base_url=haxcms.base_url,
        username=haxcms.username,
        password=haxcms.password,
        default_site=site,
    )
    server = build_server(settings)
    async with Client(server) as client:
        contents = await client.read_resource("haxcms://catalog/blocks/media-image")
    first = contents[0] if isinstance(contents, list | tuple) else contents
    entry = json.loads(first.text)
    assert entry["tag"] == "media-image"
    assert {"source", "alt"} <= {attribute["name"] for attribute in entry["attributes"]}
    assert entry["example_html"].startswith("<media-image")


async def test_sites_list_resource(mcp: McpTestClient, site: str) -> None:
    rows = json.loads(await mcp.read_resource("haxcms://sites"))
    names = {row["name"] for row in rows}
    assert site in names


async def test_site_summary_resource(mcp: McpTestClient, site: str) -> None:
    detail = json.loads(await mcp.read_resource(f"haxcms://sites/{site}"))
    assert detail["name"] == site


async def test_outline_resource_text_and_json(mcp: McpTestClient, site: str, page: Item) -> None:
    # the starter page plus the fixture page; take the fixture page offline so the
    # unpublished marker is exercised too
    await mcp.call("update_page_details", page=page.id, published=False, site=site)
    payload = json.loads(await mcp.read_resource(f"haxcms://sites/{site}/outline"))
    assert payload["site"] == site
    assert payload["count"] == 2

    text = payload["text"]
    lines = text.splitlines()
    assert len(lines) == 2  # both pages at root level
    assert lines[0].startswith("- Home (") and "[unpublished]" not in lines[0]
    assert f"- {page.title} ({page.slug}) [{page.id}] [unpublished]" in lines[1]

    titles = [node["item"]["title"] for node in payload["outline"]]
    assert titles == ["Home", page.title]
    assert payload["outline"][0]["children"] == []


async def test_page_resource_block_index_comments(
    mcp: McpTestClient, site: str, page: Item
) -> None:
    result = await mcp.call(
        "set_page_content",
        page=page.id,
        html="<h2>Heading</h2><p>Body & more.</p>",
        site=site,
    )
    assert [block["tag"] for block in result["blocks"]] == ["h2", "p"]
    golden = "<!-- block 0: h2 -->\n<h2>Heading</h2>\n<!-- block 1: p -->\n<p>Body &amp; more.</p>"
    assert await mcp.read_resource(f"haxcms://sites/{site}/pages/{page.slug}") == golden
    # the same page resolves by id
    assert await mcp.read_resource(f"haxcms://sites/{site}/pages/{page.id}") == golden


async def test_page_resource_unknown_page(mcp: McpTestClient, site: str) -> None:
    with pytest.raises(MCPError, match="NOT_FOUND"):
        await mcp.read_resource(f"haxcms://sites/{site}/pages/no-such-page")
