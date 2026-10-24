"""Phase 4 integration tests: content save/read round-trips against the live instance.

PLAN Phase 4 integration list: `test_p04_content_roundtrip.py` (set content → get content
equals modulo sanitisation; page title unchanged after save; unpublished page stays
unpublished after save; disk file matches) plus the T4.7 verify items that belong to the
write path, live-probed: a raw PATCH without the Page Break envelope is a silent no-op
(still 200, body untouched), an envelope WITHOUT `published` clears the flag, and
`card="card"` is stored byte-identical (no sanitisation rewrite).
"""

from __future__ import annotations

import pytest

from haxcms_mcp.client import HaxcmsClient, site_api
from haxcms_mcp.models.item import Item
from haxcms_mcp.services.content.page_break import build_page_break
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

SEED_HTML = (
    "<h2>Round Trip</h2>"
    "<p>Body & more <em>emphasis</em>.</p>"
    '<media-image source="files/a.png" alt="A path" caption="Cap" card="card"></media-image>'
)


async def test_set_then_get_roundtrip(mcp: McpTestClient, site: str, page: Item) -> None:
    result = await mcp.call("set_page_content", page=page.id, html=SEED_HTML, site=site)
    assert [block["tag"] for block in result["blocks"]] == ["h2", "p", "media-image"]

    got = await mcp.call("get_page_content", page=page.id, site=site)
    # the stored body equals what the save returned (no server-side rewrite)
    assert got["html"] == result["html"]
    assert [block["tag"] for block in got["blocks"]] == ["h2", "p", "media-image"]
    # modulo sanitisation: the raw & is stored escaped, inline markup survives
    assert "<p>Body &amp; more <em>emphasis</em>.</p>" in got["html"]
    assert got["blocks"][0]["text"] == "Round Trip"
    assert got["blocks"][1]["text"] == "Body & more emphasis."
    # T4.7: card="card" survives sanitisation byte-identical
    assert 'card="card"' in got["html"]
    # no envelope leaks into the stored body
    assert "page-break" not in got["html"]


async def test_title_and_published_unchanged_after_save(
    mcp: McpTestClient, site: str, page: Item
) -> None:
    await mcp.call("set_page_content", page=page.id, html=SEED_HTML, site=site)
    record = await mcp.call("get_page", page=page.id, site=site)
    assert record["id"] == page.id
    assert record["title"] == page.title  # the content save never touches details
    assert record["slug"] == page.slug
    assert record["published"] is True


async def test_unpublished_page_stays_unpublished_after_save(
    mcp: McpTestClient, site: str, page: Item
) -> None:
    await mcp.call("update_page_details", page=page.id, published=False, site=site)
    await mcp.call("set_page_content", page=page.id, html=SEED_HTML, site=site)
    record = await mcp.call("get_page", page=page.id, site=site)
    assert record["published"] is False
    # and the save carried the body through
    got = await mcp.call("get_page_content", page=page.id, site=site)
    assert got["blocks"][0]["tag"] == "h2"


async def test_disk_file_matches_saved_body(
    mcp: McpTestClient, site: str, page: Item, haxcms: HaxcmsRuntime
) -> None:
    await mcp.call("set_page_content", page=page.id, html=SEED_HTML, site=site)
    got = await mcp.call("get_page_content", page=page.id, site=site)
    disk = haxcms.read_page_html(site, page.id)
    assert disk.strip() == str(got["html"]).strip()
    assert 'card="card"' in disk


SANITISATION_INPUT = (
    '<p>Link <a href="https://example.com/notes" target="_blank">Watch it here.</a></p>'
    '<code-sample type="javascript" copy-clipboard-button="copy-clipboard-button">'
    '<template preserve-content="preserve-content">const a = 1 &lt; 2;</template></code-sample>'
    '<vocab-term term="T" information="I" links=\'[{"title": "S", "href": "https://x"}]\'>'
    "</vocab-term>"
    '<multiple-choice question="Q?">'
    '<input type="checkbox" value="A" correct>\n'
    '<input type="checkbox" value="B"></multiple-choice>'
)

# the live saveNode rewrite of SANITISATION_INPUT (T4.7, byte-exact from the instance):
# target="_blank" dropped, <template preserve-content> dropped, the bare boolean
# `correct` on assessment inputs dropped, single-quoted JSON attributes re-quoted.
SANITISED_STORED = (
    '<p>Link <a href="https://example.com/notes">Watch it here.</a></p>\n'
    '<code-sample type="javascript" copy-clipboard-button="copy-clipboard-button">'
    "<template>const a = 1 &lt; 2;</template></code-sample>\n"
    '<vocab-term term="T" information="I"'
    ' links="[{&quot;title&quot;: &quot;S&quot;, &quot;href&quot;: &quot;https://x&quot;}]">'
    "</vocab-term>\n"
    '<multiple-choice question="Q?"><input type="checkbox" value="A">\n'
    '<input type="checkbox" value="B"></multiple-choice>'
)


async def test_sanitisation_rewrites_are_exactly_the_documented_ones(
    mcp: McpTestClient, site: str, page: Item
) -> None:
    """T4.7 verify: which parts of a save survive sanitisation unchanged.

    Every TAG survives; four attribute forms are rewritten (golden captured live —
    GET body and the on-disk pages/<id>/index.html agree byte-for-byte).
    """
    result = await mcp.call("set_page_content", page=page.id, html=SANITISATION_INPUT, site=site)
    assert result["html"] == SANITISED_STORED
    got = await mcp.call("get_page_content", page=page.id, site=site)
    assert got["html"] == SANITISED_STORED


async def test_raw_patch_without_envelope_is_silent_noop(
    client: HaxcmsClient, site: str, page: Item
) -> None:
    """T4.7 verify: a content PATCH whose body lacks `<page-break>` writes NOTHING
    (still 200) — the fact that justifies the envelope guard in set_page_content."""
    record = await site_api.get_item(client, site, page.id, include_content=True)
    item = Item.from_api(record)
    await site_api.patch_content(client, site, page.id, build_page_break(item) + "<p>Seeded.</p>")
    before = await site_api.get_content(client, site, page.id)
    assert before["body"] == "<p>Seeded.</p>"

    # the silent no-op: no envelope, still a 200 item record
    response = await site_api.patch_content(client, site, page.id, "<p>Ignored.</p>")
    assert response.get("id") == page.id

    after = await site_api.get_content(client, site, page.id)
    assert after["body"] == "<p>Seeded.</p>"  # unchanged, NOT the ignored body


async def test_envelope_without_published_clears_flag(
    client: HaxcmsClient, site: str, page: Item
) -> None:
    """T4.7 verify: `published` absent from the envelope means FALSE upstream — the
    envelope builder must replay the flag or a content save would unpublish the page."""
    record = await site_api.get_item(client, site, page.id)
    item = Item.from_api(record)
    assert item.published is True

    item.published = False  # build_page_break then omits the attribute entirely
    envelope = build_page_break(item)
    assert "published" not in envelope
    await site_api.patch_content(client, site, page.id, envelope + "<p>x</p>")

    fresh = Item.from_api(await site_api.get_item(client, site, page.id))
    assert fresh.metadata.published is False
