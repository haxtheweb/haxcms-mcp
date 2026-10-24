"""Unit tests for the Phase 0 server: boot, tool registry, middleware behaviour."""

from __future__ import annotations

import mcp_types
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.server import build_server

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    return Settings(base_url="http://localhost:3000", **overrides)  # type: ignore[arg-type]


def _add_fake_write_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=mcp_types.ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    async def fake_write(x: int) -> int:
        return x + 1


def _add_fake_error_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=mcp_types.ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    async def fake_error() -> str:
        raise HaxcmsMcpError(
            ErrorCode.NOT_FOUND, "page 'x' does not exist", hint="call list_pages first"
        )


async def test_server_lists_the_registered_tools() -> None:
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}
    # Phase 1 registers the four session tools (PLAN T1.7); Phase 2 the nine site tools
    # (T2.4); Phase 3 the sixteen outline and page tools (T3.5); Phase 4 the twelve
    # content tools and the 37 typed block tools (T4.5); Phase 5 the eight files tools
    # (T5.6); Phase 6 the eleven settings tools (T6.4); Phase 7 the three import tools
    # and the twelve generated converters (T7.4/T7.5); Phase 8 the five export tools
    # (T8.4) — 117 in total.
    assert sorted(by_name) == [
        "add_accent_card",
        "add_audio",
        "add_block",
        "add_blockquote",
        "add_citation",
        "add_code_sample",
        "add_collapse",
        "add_cta",
        "add_divider",
        "add_fill_in_the_blanks",
        "add_flash_card",
        "add_grid",
        "add_heading",
        "add_image",
        "add_image_compare",
        "add_image_from_file",
        "add_image_gallery",
        "add_learning_component",
        "add_license",
        "add_link",
        "add_list",
        "add_mark_the_words",
        "add_markdown_block",
        "add_matching_question",
        "add_multiple_choice",
        "add_page_section",
        "add_paragraph",
        "add_placeholder",
        "add_self_check",
        "add_short_answer",
        "add_sorting_question",
        "add_stop_note",
        "add_styled_quote",
        "add_table",
        "add_tagging_question",
        "add_timeline",
        "add_true_false",
        "add_video",
        "add_vocab_term",
        "add_wikipedia_query",
        "archive_site",
        "clone_site",
        "configure_site_git",
        "convert_docx_to_html",
        "convert_docx_to_pdf",
        "convert_html_to_docx",
        "convert_html_to_md",
        "convert_html_to_pdf",
        "convert_json_to_yaml",
        "convert_md_to_html",
        "convert_pdf_to_html",
        "convert_pptx_to_html",
        "convert_pretty_html",
        "convert_xlsx_to_csv",
        "convert_yaml_to_json",
        "create_page",
        "create_pages",
        "create_site",
        "create_site_from_document",
        "create_site_from_platform",
        "create_site_from_skeleton",
        "delete_file",
        "delete_page",
        "download_site_skeleton",
        "download_site_zip",
        "duplicate_file",
        "export_page",
        "export_site",
        "get_block_schema",
        "get_file",
        "get_outline",
        "get_page",
        "get_page_blocks",
        "get_page_content",
        "get_page_revision",
        "get_server_info",
        "get_site",
        "get_site_settings",
        "get_skeleton",
        "import_document",
        "list_blocks",
        "list_files",
        "list_page_revisions",
        "list_pages",
        "list_sites",
        "list_skeletons",
        "list_tags",
        "list_themes",
        "login",
        "logout",
        "move_block",
        "move_page",
        "normalize_slugs",
        "regenerate_alternate_formats",
        "remove_block",
        "rename_file",
        "reorder_pages",
        "replace_block",
        "restore_page_revision",
        "save_site_as_template",
        "search_site",
        "set_allowed_blocks",
        "set_block_text",
        "set_editor_audience",
        "set_page_content",
        "set_page_parent",
        "set_platform_features",
        "set_site_theme",
        "set_theme_regions",
        "transform_file",
        "update_author_info",
        "update_block",
        "update_page_details",
        "update_seo_settings",
        "update_site_info",
        "upload_file",
        "whoami",
    ]

    ann = by_name["get_server_info"].annotations
    assert ann is not None
    assert ann.read_only_hint is True
    assert ann.destructive_hint is False
    assert ann.idempotent_hint is True
    assert ann.open_world_hint is False

    # login/logout are writes to session state but not destructive; whoami is read-only
    for name, read_only in [("login", False), ("logout", False), ("whoami", True)]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is read_only, name
        assert tool_ann.destructive_hint is False, name


async def test_site_tool_annotations() -> None:
    """Phase 2 annotation matrix (PLAN §5 + tool inventory): reads, writes, destructive."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}

    read_only = ["get_site", "list_sites", "list_themes", "list_skeletons", "get_skeleton"]
    for name in read_only:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is True, name
        assert tool_ann.destructive_hint is False, name

    # creating/cloning repeats produce new sites -> not idempotent
    for name in ["create_site", "create_site_from_skeleton", "clone_site"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is False, name
        assert tool_ann.idempotent_hint is False, name

    archive_ann = by_name["archive_site"].annotations
    assert archive_ann is not None
    assert archive_ann.read_only_hint is False
    assert archive_ann.destructive_hint is True


async def test_page_tool_annotations() -> None:
    """Phase 3 annotation matrix (PLAN T3.5): reads, repeats-differ writes, destructive."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}

    read_only = [
        "get_outline",
        "list_pages",
        "get_page",
        "list_page_revisions",
        "get_page_revision",
        "search_site",
        "list_tags",
    ]
    for name in read_only:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is True, name
        assert tool_ann.destructive_hint is False, name

    # repeating a create makes another page; repeating a move moves again -> not idempotent
    for name in ["create_page", "create_pages", "move_page"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is False, name
        assert tool_ann.idempotent_hint is False, name

    # same arguments twice -> same end state, no loss
    for name in ["update_page_details", "set_page_parent", "normalize_slugs"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is False, name
        assert tool_ann.idempotent_hint is True, name

    # full-manifest rewrite, page removal and history rollback -> destructive
    for name in ["reorder_pages", "delete_page", "restore_page_revision"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is True, name


async def test_content_tool_annotations() -> None:
    """Phase 4 annotation matrix (PLAN T4.5): reads, appends, edits, destructive writes."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}

    for name in ["get_page_content", "get_page_blocks", "list_blocks", "get_block_schema"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is True, name
        assert tool_ann.destructive_hint is False, name

    # repeating an append adds another block; repeating a link wraps the text again
    for name in ["add_block", "add_link"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is False, name
        assert tool_ann.idempotent_hint is False, name

    # same arguments twice -> same end state (re-moved, re-set, re-written)
    for name in ["move_block", "update_block", "set_block_text"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is False, name
        assert tool_ann.idempotent_hint is True, name

    # whole-body rewrite, block swap and block removal -> destructive
    for name in ["set_page_content", "replace_block", "remove_block"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is True, name


async def test_typed_block_tool_annotations() -> None:
    """Phase 4 typed add_<block> tools (PLAN annotation matrix): every call appends a new
    block — not read-only, not destructive, and repeating it is NOT idempotent.
    `add_image_from_file` is excluded: it is the Phase 5 files composite, tested below."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    typed = [
        tool
        for tool in tools
        if tool.name.startswith("add_")
        and tool.name not in {"add_block", "add_link", "add_image_from_file"}
    ]
    assert len(typed) == 37
    for tool in typed:
        ann = tool.annotations
        assert ann is not None, tool.name
        assert ann.read_only_hint is False, tool.name
        assert ann.destructive_hint is False, tool.name
        assert ann.idempotent_hint is False, tool.name


async def test_files_tool_annotations() -> None:
    """Phase 5 annotation matrix (PLAN T5.6): reads, repeat-differs uploads/transforms,
    a destructive delete, and the idempotent rename."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}

    for name in ["list_files", "get_file"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is True, name
        assert tool_ann.destructive_hint is False, name

    # uploads/transforms/duplicates/composite repeat to new state -> not idempotent
    for name in ["upload_file", "transform_file", "duplicate_file", "add_image_from_file"]:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is False, name
        assert tool_ann.idempotent_hint is False, name

    # renaming to the same name twice leaves the same end state -> idempotent
    rename_ann = by_name["rename_file"].annotations
    assert rename_ann is not None
    assert rename_ann.read_only_hint is False
    assert rename_ann.destructive_hint is False
    assert rename_ann.idempotent_hint is True

    delete_ann = by_name["delete_file"].annotations
    assert delete_ann is not None
    assert delete_ann.read_only_hint is False
    assert delete_ann.destructive_hint is True


async def test_settings_tool_annotations() -> None:
    """Phase 6 annotation matrix (PLAN T6.4): one read, converging idempotent writes."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}

    read_ann = by_name["get_site_settings"].annotations
    assert read_ann is not None
    assert read_ann.read_only_hint is True
    assert read_ann.destructive_hint is False

    # every settings write converges to the same end state when repeated -> idempotent
    idempotent_writes = [
        "update_site_info",
        "update_author_info",
        "set_site_theme",
        "set_theme_regions",
        "update_seo_settings",
        "set_editor_audience",
        "set_allowed_blocks",
        "set_platform_features",
        "configure_site_git",
        "regenerate_alternate_formats",
    ]
    for name in idempotent_writes:
        tool_ann = by_name[name].annotations
        assert tool_ann is not None, name
        assert tool_ann.read_only_hint is False, name
        assert tool_ann.destructive_hint is False, name
        assert tool_ann.idempotent_hint is True, name


async def test_converter_tool_annotations() -> None:
    """Phase 7 annotation matrix (PLAN T7.5): converters are read-only — they mutate
    nothing on the Instance; binary results land in the LOCAL Output Directory."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    converters = [tool for tool in tools if tool.name.startswith("convert_")]
    assert len(converters) == 12
    for tool in converters:
        ann = tool.annotations
        assert ann is not None, tool.name
        assert ann.read_only_hint is True, tool.name
        assert ann.destructive_hint is False, tool.name
        assert ann.idempotent_hint is True, tool.name


async def test_export_tool_annotations() -> None:
    """Phase 8 annotation matrix (PLAN T8.4): exports are read-only-hint FALSE (they
    produce Output Directory files; save-as-template writes server-side) but never
    destructive, and repeats are safe (collisions take a new -<n> filename slot)."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}
    for name in [
        "export_site",
        "export_page",
        "download_site_zip",
        "save_site_as_template",
        "download_site_skeleton",
    ]:
        ann = by_name[name].annotations
        assert ann is not None, name
        assert ann.read_only_hint is False, name
        assert ann.destructive_hint is False, name
        assert ann.idempotent_hint is True, name


async def test_converter_tool_schemas_hide_bound_params() -> None:
    """The partial-bound client/settings never reach the schema; the spec-derived
    parameters and their defaults do (ADR-0002)."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
    by_name = {t.name: t for t in tools}

    md_schema = by_name["convert_md_to_html"].input_schema
    assert set(md_schema["properties"]) == {"md", "type"}
    assert md_schema["required"] == ["md"]

    pdf_schema = by_name["convert_html_to_pdf"].input_schema
    assert set(pdf_schema["properties"]) == {"source", "base"}

    docx_schema = by_name["convert_docx_to_html"].input_schema
    assert set(docx_schema["properties"]) == {"source"}

    # the generated docstrings become the tool descriptions, deviations included
    assert "DEVIATION" in (by_name["convert_html_to_docx"].description or "")
    assert "NEEDS CHROME" in (by_name["convert_docx_to_pdf"].description or "")


async def test_configure_site_git_tool_raises_unsupported() -> None:
    """The git tool fails UNSUPPORTED before any network use (no route persists git)."""
    mcp = build_server(_settings())
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "configure_site_git", {"site": "demo", "branch": "gh-pages", "auto_push": True}
            )
    text = str(excinfo.value)
    assert "[UNSUPPORTED]" in text
    assert "git publishing settings" in text
    assert "site.json" in text


async def test_get_server_info_payload() -> None:
    mcp = build_server(_settings(read_only=True))
    async with Client(mcp) as client:
        result = await client.call_tool("get_server_info", {})
    data = result.data
    assert isinstance(data, dict)
    assert data["name"] == "haxcms-mcp"
    assert data["base_url"] == "http://localhost:3000"
    assert data["read_only"] is True
    assert data["transport"] == "stdio"
    assert isinstance(data["version"], str)
    # no credentials configured: the live probe degrades gracefully into *_error fields
    haxcms_info = data["haxcms"]
    assert isinstance(haxcms_info, dict)
    assert haxcms_info["version_error"].startswith("[AUTH_REQUIRED]")
    assert haxcms_info["status_error"].startswith("[AUTH_REQUIRED]")


async def test_read_only_mode_blocks_write_tool() -> None:
    mcp = build_server(_settings(read_only=True))
    _add_fake_write_tool(mcp)
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("fake_write", {"x": 1})
    assert "[READ_ONLY]" in str(excinfo.value)
    # read-only tool still works
    async with Client(mcp) as client:
        result = await client.call_tool("get_server_info", {})
    assert result.data is not None


async def test_write_tool_allowed_when_not_read_only() -> None:
    mcp = build_server(_settings(read_only=False))
    _add_fake_write_tool(mcp)
    async with Client(mcp) as client:
        result = await client.call_tool("fake_write", {"x": 1})
    assert result.data == 2


async def test_error_middleware_formats_codes() -> None:
    mcp = build_server(_settings())
    _add_fake_error_tool(mcp)
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("fake_error", {})
    assert str(excinfo.value) == "[NOT_FOUND] page 'x' does not exist. call list_pages first"
