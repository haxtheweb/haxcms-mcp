"""Unit tests for the Phase 9 prompts (PLAN T9.1 + test plan).

Each prompt renders with sample args, carries the PLAN-mandated content, and mentions
ONLY tools that exist in the live registry (checked by extracting every snake_case token
from the rendered text — the prompt module keeps tool names backticked and avoids
non-tool underscores so no whitelist is needed).
"""

from __future__ import annotations

import re

import pytest
from fastmcp import Client, FastMCP

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server
from tests.harness.prompt_samples import PROMPT_NAMES, render_args

pytestmark = pytest.mark.unit

# any lowercase snake_case token — in the prompt texts, these are exactly tool names
TOOL_TOKEN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _server() -> FastMCP:
    return build_server(Settings(base_url="http://prompt.invalid"))


async def _render(client: Client, name: str) -> str:
    result = await client.get_prompt(name, render_args(name))
    return result.messages[0].content.text


async def test_all_four_prompts_are_registered() -> None:
    async with Client(_server()) as client:
        prompts = await client.list_prompts()
    assert sorted(prompt.name for prompt in prompts) == PROMPT_NAMES


async def test_prompt_argument_metadata() -> None:
    async with Client(_server()) as client:
        prompts = {prompt.name: prompt for prompt in await client.list_prompts()}

    assert not (prompts["hax_author"].arguments or [])

    brief = {arg.name: arg for arg in prompts["build_page_from_brief"].arguments or []}
    assert set(brief) == {"site", "page_title", "brief", "media"}
    assert brief["site"].required is True
    assert brief["media"].required is False

    scaffold = {arg.name: arg for arg in prompts["scaffold_course_from_outline"].arguments or []}
    assert set(scaffold) == {"site_name", "outline_text", "theme"}
    assert scaffold["theme"].required is False

    polish = {arg.name: arg for arg in prompts["import_and_polish_document"].arguments or []}
    assert set(polish) == {"site_name", "source"}
    assert polish["source"].required is True


async def test_prompts_only_mention_existing_tools() -> None:
    async with Client(_server()) as client:
        registry = {tool.name for tool in await client.list_tools()}
        for name in PROMPT_NAMES:
            text = await _render(client, name)
            unknown = set(TOOL_TOKEN.findall(text)) - registry
            assert not unknown, f"{name} mentions non-existent tools: {sorted(unknown)}"


async def test_hax_author_covers_the_plan_topics() -> None:
    async with Client(_server()) as client:
        text = await _render(client, "hax_author")

    # save discipline: no autosave, every block tool saves, one revision per call
    assert "no autosave" in text
    assert "one call is one save and one git revision" in text
    # block discovery: the two catalog tools and the catalog resources
    assert "`list_blocks`" in text
    assert "`get_block_schema`" in text
    assert "haxcms://catalog/blocks" in text
    # anchor rules: the four placements and the occurrence tie-breaker
    for placement in ("append", "prepend", "after", "before"):
        assert placement in text
    assert "occurrence" in text
    # accessibility duties: alt/caption/citation on images, titles on video+audio
    assert "alt" in text and "caption" in text and "citation" in text
    assert "video" in text and "audio" in text and "title" in text
    # the reserved x/ route
    assert "`x/`" in text
    # artifacts: Output Directory records, never bytes/URLs
    assert "{path, bytes, mimetype}" in text


async def test_build_page_from_brief_mirrors_the_tutorial_order() -> None:
    async with Client(_server()) as client:
        text = await _render(client, "build_page_from_brief")

    # the sample args are interpolated
    assert '"Lesson One"' in text
    assert "prairie design" in text
    assert "files/songline.png" in text and "https://video.example/lecture" in text

    # the tutorial sequence, in order (PLAN T9.1)
    steps = [
        "`create_page`",
        "`update_page_details`",
        "`add_paragraph`",
        "`add_heading`",
        "`add_link`",
        "`get_page_blocks`",
    ]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)

    # the media tools are named, with the accessibility trio
    assert "`add_image_from_file`" in text and "`add_image`" in text
    assert "`add_video`" in text


async def test_build_page_from_brief_renders_without_media() -> None:
    async with Client(_server()) as client:
        args = render_args("build_page_from_brief")
        args.pop("media")
        result = await client.get_prompt("build_page_from_brief", args)
        text = result.messages[0].content.text
    assert "MEDIA (use in order" not in text
    assert "`create_page`" in text


async def test_scaffold_course_from_outline_lists_the_plan_sequence() -> None:
    async with Client(_server()) as client:
        text = await _render(client, "scaffold_course_from_outline")

    assert "demo-course" in text and "clean-one" in text
    assert "- Home" in text and "Lesson Two" in text  # the outline rides along verbatim

    steps = [
        "`create_pages`",
        "`get_outline`",
        "`reorder_pages`",
        "`set_site_theme`",
    ]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "`list_skeletons`" in text and "`create_site_from_skeleton`" in text
    assert "`create_site`" in text and "`list_themes`" in text
    # reorder_pages is flagged as the destructive full-manifest rewrite
    assert "full-manifest rewrite" in text


async def test_import_and_polish_document_lists_the_plan_sequence() -> None:
    async with Client(_server()) as client:
        text = await _render(client, "import_and_polish_document")

    assert "bio-101" in text and "files/syllabus.docx" in text

    steps = [
        "`create_site_from_document`",
        "`get_outline`",
        "`get_page_blocks`",
        "`update_block`",
        "`update_seo_settings`",
        "`export_site`",
    ]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "`replace_block`" in text and "`update_site_info`" in text
    assert "`save_site_as_template`" in text and "`list_skeletons`" in text
    # the zip hand-off and the Chrome caveat
    assert "zip" in text
    assert "UNSUPPORTED" in text
