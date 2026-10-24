"""Phase 4 functional test: rebuild the tutorial page end-to-end through the tools.

PLAN Phase 4 functional list: `test_p04_rebuild_tutorial_page.py` — replays the tutorial
("A Designerly Engagement with the World", Appendix D steps 3-13) verbatim through tools:
create page, rename, paste seven paragraphs, two headings (one via paragraph →
replace_block conversion), the first image via placeholder → replace_block →
update_block, the second image anchored after a paragraph, the lecture video, and
"Watch it here." wrapped in a link twice. The golden is
`tests/fixtures/pages/tutorial_finished.html`: final block sequence, attributes and
texts must match it; the page must render through the public
`GET items/{id}?include=content` path, the page resource and the on-disk file.

Anchors follow the FIXTURE positions (the authoritative final page), not Appendix D's
paragraph ordinals — the script's "paragraph 6 / paragraph 3" heading anchors and its
"first image at the top (prepend)" step describe the original course page's layout,
which the fixture golden reorders (Prairie Spirit above the prairie paragraph, First
Secret above the noticing paragraph, Songline_1 after paragraph three); recorded in
PROGRESS.md as a Phase 4 deviation note. Phase 4 has no upload tool (Phase 5), so the
images carry their `files/...` sources as attributes, exactly like the fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from haxcms_mcp.services.content.parser import parse_blocks
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.functional

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "pages" / "tutorial_finished.html"

TITLE = "A Designerly Engagement with the World"

PARAGRAPHS = [
    "The course title came from a phrase I could not stop turning over.",
    "It began as a note scrawled in the margin of a library book.",
    "Designing, it said, is a way of paying attention.",
    "I kept walking the same path until the path kept me.",
    "The prairie does not announce its design; you have to notice it.",
    "Noticing is the first act of design. Watch it here.",
    "Everything after that is bookkeeping. Watch it here.",
]

LECTURE_LINK = '<a href="https://example.com/lecture">Watch it here.</a>'
# the fixture's second link carries target="_blank" (its authored form); saveNode
# sanitisation strips target on save (live-verified T4.7 fact), so the STORED page —
# and the disk file — hold the link without it
NOTES_LINK_STORED = '<a href="https://example.com/notes">Watch it here.</a>'


async def test_rebuild_tutorial_page(mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime) -> None:
    # 1. add a new page ("page" is the default title in the tutorial) and rename it
    created = await mcp.call("create_page", title="page", site=site)
    page = str(created["id"])
    renamed = await mcp.call("update_page_details", page=page, title=TITLE, site=site)
    assert renamed["title"] == TITLE
    # the rename regenerates the slug from the new title (pathauto) — the resource
    # read at the end must use the FRESH slug, not the creation-time one
    slug = str(renamed["slug"])
    assert slug != str(created["slug"])

    # 2. paste the seven paragraphs and save
    pasted = "".join(f"<p>{text}</p>" for text in PARAGRAPHS)
    await mcp.call("set_page_content", page=page, html=pasted, site=site)
    blocks = await mcp.call("get_page_blocks", page=page, site=site)
    assert blocks["count"] == 7
    assert [block["tag"] for block in blocks["blocks"]] == ["p"] * 7

    # 3. the saved page renders through the public item read
    record = await mcp.call("get_page", page=page, include_content=True, site=site)
    assert record["title"] == TITLE
    assert PARAGRAPHS[0] in str(record["content"])

    # 4. heading above the prairie paragraph
    await mcp.call(
        "add_heading",
        page=page,
        text="Designing in the Prairie Spirit",
        level=2,
        anchor="The prairie does not announce",
        placement="before",
        site=site,
    )

    # 5. the faster-heading method: paragraph, then convert it via replace_block
    await mcp.call(
        "add_paragraph",
        page=page,
        text_or_html="The First Secret is Noticing",
        anchor="Noticing is the first act of design",
        placement="before",
        site=site,
    )
    converted = await mcp.call(
        "replace_block",
        page=page,
        anchor="The First Secret is Noticing",
        html="<h2>The First Secret is Noticing</h2>",
        site=site,
    )
    assert converted["affected"][0]["tag"] == "h2"

    # 6. first image: placeholder -> media-image -> attributes, anchored after the
    # third paragraph (the fixture's position for Songline_1)
    await mcp.call(
        "add_placeholder",
        page=page,
        kind="image",
        text="Songline painting",
        anchor="Designing, it said, is a way of paying attention.",
        placement="after",
        site=site,
    )
    await mcp.call(
        "replace_block",
        page=page,
        anchor="place-holder",
        html='<media-image source="files/Songline_1.png"></media-image>',
        site=site,
    )
    updated = await mcp.call(
        "update_block",
        page=page,
        anchor="media-image",
        set={
            "alt": "Songline pattern across the prairie",
            "caption": "Figure 1. The songline as drawn by the walker.",
            "citation": "Photograph by the author.",
            "size": "wide",
        },
        site=site,
    )
    assert updated["affected"][0]["attributes"]["size"] == "wide"

    # 7. second image after the prairie paragraph
    await mcp.call(
        "add_image",
        page=page,
        source="files/Songline_2.png",
        alt="Second songline panel",
        caption="Figure 2. The return walk.",
        card=True,
        anchor="The prairie does not announce",
        placement="after",
        site=site,
    )

    # 8. the lecture video after the noticing paragraph
    await mcp.call(
        "add_video",
        page=page,
        source="https://www.youtube.com/watch?v=prairie-walk",
        title="Prairie walking lecture",
        accent_color="orange",
        anchor="Noticing is the first act of design",
        placement="after",
        site=site,
    )

    # 9. wrap "Watch it here." in a link twice
    await mcp.call(
        "add_link",
        page=page,
        anchor="Noticing is the first act of design",
        text="Watch it here.",
        url="https://example.com/lecture",
        site=site,
    )
    await mcp.call(
        "add_link",
        page=page,
        anchor="Everything after that is bookkeeping",
        text="Watch it here.",
        url="https://example.com/notes",
        new_tab=True,
        site=site,
    )

    # --- verify: the stored page equals the finished-tutorial golden ------------------
    expected = parse_blocks(FIXTURE.read_text(encoding="utf-8"))
    final = await mcp.call("get_page_content", page=page, site=site)
    live = final["blocks"]
    assert len(live) == len(expected) == 12
    assert [block["tag"] for block in live] == [block.tag for block in expected]
    for got, want in zip(live, expected, strict=True):
        assert got["attributes"] == want.attributes, want.tag
        assert got["text"] == want.text, want.tag
    body = str(final["html"])
    assert LECTURE_LINK in body
    assert NOTES_LINK_STORED in body
    assert 'target="_blank"' not in body  # stripped by saveNode sanitisation

    # --- verify: the page resource renders the same blocks ----------------------------
    resource = await mcp.read_resource(f"haxcms://sites/{site}/pages/{slug}")
    assert resource.startswith("<!-- block 0: p -->")
    assert "<!-- block 3: media-image -->" in resource
    assert "<!-- block 5: h2 -->" in resource
    assert "<!-- block 10: video-player -->" in resource
    assert "<!-- block 11: p -->" in resource

    # --- verify: the on-disk file matches ---------------------------------------------
    disk = haxcms.read_page_html(site, page)
    disk_blocks = parse_blocks(disk)
    assert [block.tag for block in disk_blocks] == [block.tag for block in expected]
    assert 'card="card"' in disk
    assert LECTURE_LINK in disk
    assert NOTES_LINK_STORED in disk

    # --- verify: the public item read renders the finished page ------------------------
    record = await mcp.call("get_page", page=page, include_content=True, site=site)
    assert record["title"] == TITLE
    content = str(record["content"])
    assert PARAGRAPHS[4] in content
    assert LECTURE_LINK in content
    assert '<video-player source="https://www.youtube.com/watch?v=prairie-walk"' in content
