"""T9.5 end-to-end smoke: the whole tutorial journey over the real transports.

Spawns HAXcms (session harness) and `python -m haxcms_mcp` as a **subprocess over stdio**
with env pointing at it, connects with a fastmcp Client, and replays Appendix D step by
step using only tool calls and resources — no in-memory shortcuts, no direct service
calls. After every step the tool result is asserted; at the end the disk is:

* `site.json` holds the two pages with the right titles and slugs,
* `pages/<id>/index.html` holds the exact finished-tutorial block sequence (7 `p`,
  2 `h2`, 2 `media-image` with alt/caption/citation, 1 `video-player`, 2 links),
* the two uploaded Files exist under `files/`,
* the zip export exists in the Output Directory.

Plus the short HTTP-transport variant T9.5 asks for: `--transport http`, `whoami` and
`list_sites`.

Two recorded deviations ride along (both already in PROGRESS.md):

* Anchors follow the `tutorial_finished.html` golden, not Appendix D's paragraph
  ordinals — the fixture is the authoritative finished page (the Phase 4 deviation
  note); the final block-for-block golden comparison is the strongest assertion.
* The site name carries a random suffix so a leaked site from a failed run can never
  turn into a `<name>-1` collision; the `create_site("First")` spaces-hint rejection
  uses the tutorial's literal name.

The images use the Phase 5 real upload path (`add_image_from_file` with absolute
fixture paths contained by INPUT_ROOTS), so the two Files land on disk for real.
"""

from __future__ import annotations

import contextlib
import secrets
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from haxcms_mcp.services.content.parser import parse_blocks
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_process import HttpMcpProcess, server_env, stdio_client

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN = FIXTURES / "pages" / "tutorial_finished.html"
SONGLINE_1 = FIXTURES / "images" / "Songline_1.png"
SONGLINE_2 = FIXTURES / "images" / "Songline_2.png"

SITE = f"first-underscore-course-{secrets.token_hex(2)}"
TITLE = "A Designerly Engagement with the World"
SLUG = "a-designerly-engagement-with-the-world"

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
# saveNode sanitisation strips target="_blank" on save (live-verified T4.7 fact), so the
# STORED page — and the disk file — hold the second link without it
NOTES_LINK_STORED = '<a href="https://example.com/notes">Watch it here.</a>'


@pytest.fixture(scope="module")
async def stdio(
    haxcms: HaxcmsRuntime, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[tuple[Client, Path]]:
    """One stdio subprocess (full tutorial env) + its Output Directory."""
    tmp = tmp_path_factory.mktemp("p09-e2e")
    output = tmp / "output"
    env = server_env(
        haxcms.base_url,
        haxcms.username,
        haxcms.password,
        HAXCMS_MCP_INPUT_ROOTS=str(FIXTURES),
        HAXCMS_MCP_OUTPUT_DIR=str(output),
    )
    async with stdio_client(env, cwd=ROOT, log_file=tmp / "mcp-stdio.log") as client:
        yield client, output


async def test_tutorial_smoke_over_stdio(stdio: tuple[Client, Path], haxcms: HaxcmsRuntime) -> None:
    client, output_dir = stdio

    async def call(name: str, /, **arguments: Any) -> Any:
        result = await client.call_tool(name, arguments)
        return result.data

    # --- 1. login (env credentials) -> whoami shows the user ---------------------------
    me = await call("whoami")
    assert me["authenticated"] is True
    assert me["user"] == haxcms.username
    assert me["read_only"] is False

    # --- 2. name the course: "First" fails with the spaces hint -------------------------
    with pytest.raises(ToolError) as excinfo:
        await call("create_site", name="First")
    error = str(excinfo.value)
    assert "[INVALID_ARGUMENT]" in error
    assert "cannot contain spaces" in error

    created_site = None
    try:
        record = await call("create_site", name=SITE, theme="clean-one")
        created_site = str(record["name"])
        assert created_site == SITE  # no <name>-1 collision: always read the name back

        outline = await call("get_outline", site=SITE)
        assert outline["site"] == SITE
        assert outline["count"] == 1
        starter = outline["outline"][0]["item"]
        assert starter["title"] == "Home"
        assert starter["slug"] == "home"

        # --- 3. add a new page: it appears below the starter page -----------------------
        created = await call("create_page", title="page", site=SITE)
        page = str(created["id"])
        assert created["title"] == "page"
        outline = await call("get_outline", site=SITE)
        assert outline["count"] == 2
        assert [node["item"]["title"] for node in outline["outline"]] == ["Home", "page"]

        # --- 4. rename: Pathauto regenerates the slug from the new title -----------------
        renamed = await call("update_page_details", page=page, title=TITLE, site=SITE)
        assert renamed["title"] == TITLE
        slug = str(renamed["slug"])
        assert slug == SLUG
        assert slug != str(created["slug"])

        # --- 5. paste the seven paragraphs (one save) -> seven p blocks ------------------
        pasted = "".join(f"<p>{text}</p>" for text in PARAGRAPHS)
        saved = await call("set_page_content", page=page, html=pasted, site=SITE)
        assert len(saved["blocks"]) == 7
        blocks = await call("get_page_blocks", page=page, site=SITE)
        assert blocks["count"] == 7
        assert [block["tag"] for block in blocks["blocks"]] == ["p"] * 7
        assert [block["text"] for block in blocks["blocks"]] == PARAGRAPHS

        # --- 6. save and view: the public content read returns the paragraphs ------------
        content = await call("get_page_content", page=page, site=SITE)
        assert content["item"]["title"] == TITLE
        for text in PARAGRAPHS:
            assert text in content["html"]

        # --- 7. heading above the prairie paragraph (golden position) --------------------
        heading = await call(
            "add_heading",
            page=page,
            text="Designing in the Prairie Spirit",
            level=2,
            anchor="The prairie does not announce",
            placement="before",
            site=SITE,
        )
        assert heading["affected"][0]["tag"] == "h2"

        # --- 8. faster heading: paragraph, then convert it via replace_block -------------
        await call(
            "add_paragraph",
            page=page,
            text_or_html="The First Secret is Noticing",
            anchor="Noticing is the first act of design",
            placement="before",
            site=SITE,
        )
        converted = await call(
            "replace_block",
            page=page,
            anchor="The First Secret is Noticing",
            html="<h2>The First Secret is Noticing</h2>",
            site=SITE,
        )
        assert converted["affected"][0]["tag"] == "h2"

        # --- 9. first image: real upload, anchored after paragraph three -----------------
        first_image = await call(
            "add_image_from_file",
            page=page,
            source=str(SONGLINE_1),
            alt="Songline pattern across the prairie",
            caption="Figure 1. The songline as drawn by the walker.",
            citation="Photograph by the author.",
            size="wide",
            anchor="Designing, it said, is a way of paying attention.",
            placement="after",
            site=SITE,
        )
        assert first_image["file"]["url"] == "files/Songline_1.png"

        # --- 10. second image after the prairie paragraph --------------------------------
        second_image = await call(
            "add_image_from_file",
            page=page,
            source=str(SONGLINE_2),
            alt="Second songline panel",
            caption="Figure 2. The return walk.",
            card=True,
            anchor="The prairie does not announce",
            placement="after",
            site=SITE,
        )
        assert second_image["file"]["url"] == "files/Songline_2.png"

        # --- 11. lecture video after the noticing paragraph ------------------------------
        video = await call(
            "add_video",
            page=page,
            source="https://www.youtube.com/watch?v=prairie-walk",
            title="Prairie walking lecture",
            accent_color="orange",
            anchor="Noticing is the first act of design",
            placement="after",
            site=SITE,
        )
        assert video["affected"][0]["tag"] == "video-player"

        # --- 12. two external links wrapping "Watch it here." ----------------------------
        lecture = await call(
            "add_link",
            page=page,
            anchor="Noticing is the first act of design",
            text="Watch it here.",
            url="https://example.com/lecture",
            site=SITE,
        )
        assert lecture["affected"][0]["tag"] == "p"
        notes = await call(
            "add_link",
            page=page,
            anchor="Everything after that is bookkeeping",
            text="Watch it here.",
            url="https://example.com/notes",
            new_tab=True,
            site=SITE,
        )
        assert notes["affected"][0]["tag"] == "p"

        # --- 13. verify: stored page, resource and disk equal the golden -----------------
        expected = parse_blocks(GOLDEN.read_text(encoding="utf-8"))
        final = await call("get_page_content", page=page, site=SITE)
        live = final["blocks"]
        assert len(live) == len(expected) == 12
        assert [block["tag"] for block in live] == [block.tag for block in expected]
        for got, want in zip(live, expected, strict=True):
            assert got["attributes"] == want.attributes, want.tag
            assert got["text"] == want.text, want.tag
        tags = [block["tag"] for block in live]
        assert tags.count("p") == 7 and tags.count("h2") == 2
        assert tags.count("media-image") == 2 and tags.count("video-player") == 1
        body = str(final["html"])
        assert LECTURE_LINK in body
        assert NOTES_LINK_STORED in body
        assert 'target="_blank"' not in body  # stripped by saveNode sanitisation

        contents = await client.read_resource(f"haxcms://sites/{SITE}/pages/{slug}")
        first = contents[0] if isinstance(contents, list | tuple) else contents
        resource = getattr(first, "text", first)
        assert resource.startswith("<!-- block 0: p -->")
        assert "<!-- block 3: media-image -->" in resource
        assert "<!-- block 8: h2 -->" in resource
        assert "<!-- block 10: video-player -->" in resource

        disk = haxcms.read_page_html(SITE, page)
        assert [block.tag for block in parse_blocks(disk)] == [block.tag for block in expected]
        assert LECTURE_LINK in disk
        assert NOTES_LINK_STORED in disk
        assert 'card="card"' in disk

        manifest = haxcms.read_site_json(SITE)
        by_title = {str(item["title"]): str(item["slug"]) for item in manifest["items"]}
        assert by_title == {"Home": "home", TITLE: SLUG}

        files_dir = haxcms.site_dir(SITE) / "files"
        assert (files_dir / "Songline_1.png").is_file()
        assert (files_dir / "Songline_2.png").is_file()

        # --- 14. share: the zip export lands in the Output Directory ----------------------
        export = await call("export_site", format="zip", site=SITE)
        assert export["site"] == SITE
        assert export["format"] == "zip"
        assert export["bytes"] > 0
        artifact = Path(str(export["path"]))
        assert artifact.is_file()
        assert artifact.resolve().is_relative_to(output_dir.resolve())
        assert artifact.read_bytes()[:2] == b"PK"
        assert any(name.endswith("site.json") for name in zipfile.ZipFile(artifact).namelist())
    finally:
        if created_site is not None:
            with contextlib.suppress(Exception):
                await client.call_tool("archive_site", {"site": SITE})


async def test_http_transport_variant(
    haxcms: HaxcmsRuntime, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The short T9.5 HTTP variant: --transport http answers whoami and list_sites."""
    tmp = tmp_path_factory.mktemp("p09-e2e-http")
    env = server_env(
        haxcms.base_url,
        haxcms.username,
        haxcms.password,
        HAXCMS_MCP_OUTPUT_DIR=str(tmp / "output"),
    )
    async with HttpMcpProcess(env, log_dir=tmp) as proc, Client(proc.url) as client:
        me = await client.call_tool("whoami", {})
        assert me.data["authenticated"] is True
        assert me.data["user"] == haxcms.username
        sites = await client.call_tool("list_sites", {})
        assert isinstance(sites.data["sites"], list)
