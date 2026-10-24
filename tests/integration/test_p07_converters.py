"""Live integration tests for the twelve generated converters (PLAN T7.6).

Expected strings are the LIVE 26.8.1 outputs (probed in Phase 7), not the spec's
examples: htmlToMd renders setext headings, xlsxToCsv echoes sheetNames/selectedSheet
as extras, pptxToHtml wraps slides in `<div class="slide" data-slide-number=...>` and
carries the (here empty) extracted-images map in `files`.

The two Chrome operations (htmlToPdf, docxToPdf) need a Chrome/Chromium on the SERVER
(puppeteer-core; PUPPETEER_EXECUTABLE_PATH or a system install). Without one the route
answers 400 "No Chrome/Chromium executable found" — these tests then skip (marker
`needs_chrome`), since the failure is environmental, not a contract break.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import HaxcmsMcpError
from haxcms_mcp.generated import converters as generated
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "import"
SYLLABUS = FIXTURES / "syllabus.docx"
SLIDES = FIXTURES / "slides.pptx"
WORKBOOK = FIXTURES / "workbook.xlsx"
ONEPAGE_PDF = FIXTURES / "onepage.pdf"
PAGE_HTML = FIXTURES / "page.html"

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _output_settings(haxcms: HaxcmsRuntime, tmp_path: Path) -> Settings:
    """Settings whose Output Directory is the test's tmp_path (binaries stay local)."""
    return Settings(
        base_url=haxcms.base_url,
        username=haxcms.username,
        password=haxcms.password,
        output_dir=tmp_path,
    )


# --- text converters (through the tools) ------------------------------------------------------


async def test_md_to_html(mcp: McpTestClient) -> None:
    result = await mcp.call("convert_md_to_html", md="# Title\n\nSome *emphasis*.")
    assert result["mimetype"] == "text/html"
    assert result["text"] == "<h1>Title</h1>\n<p>Some <em>emphasis</em>.</p>\n"


async def test_html_to_md_uses_setext_headings(mcp: McpTestClient) -> None:
    result = await mcp.call(
        "convert_html_to_md", html="<h1>Title</h1><p>Some <em>emphasis</em>.</p>"
    )
    assert result["mimetype"] == "text/markdown"
    assert result["text"] == "Title\n=====\n\nSome _emphasis_."


async def test_pretty_html(mcp: McpTestClient) -> None:
    result = await mcp.call("convert_pretty_html", html="<div><p>x</p></div>")
    assert result["mimetype"] == "text/html"
    assert result["text"] == "<div>\n  <p>x</p>\n</div>"


async def test_json_yaml_roundtrip(mcp: McpTestClient) -> None:
    yaml_result = await mcp.call("convert_json_to_yaml", json='{"a": [1, 2]}')
    assert yaml_result["mimetype"] == "application/yaml"
    assert yaml_result["text"] == "a:\n  - 1\n  - 2\n"
    back = await mcp.call("convert_yaml_to_json", yaml=yaml_result["text"])
    assert back["mimetype"] == "application/json"
    assert json.loads(back["text"]) == {"a": [1, 2]}


async def test_docx_to_html_keeps_the_inline_image_as_a_data_uri(
    mcp: McpTestClient,
) -> None:
    result = await mcp.call("convert_docx_to_html", source=str(SYLLABUS))
    assert result["mimetype"] == "text/html"
    assert "<h1>Biology 101 Syllabus</h1>" in result["text"]
    assert "<h2>Unit One: Cells</h2>" in result["text"]
    assert "data:image/png;base64," in result["text"]


async def test_xlsx_to_csv_default_sheet_and_extras(mcp: McpTestClient) -> None:
    result = await mcp.call("convert_xlsx_to_csv", source=str(WORKBOOK))
    assert result["mimetype"] == "text/csv"
    lines = result["text"].splitlines()
    assert lines[0] == "title,slug,parent,content"
    assert "Course Home,course-home,," in result["text"]
    assert result["sheetNames"] == ["Schedule", "Roster"]
    assert result["selectedSheet"] == "Schedule"
    assert result["originalFilename"] == "workbook.xlsx"


async def test_xlsx_to_csv_selects_the_named_sheet(mcp: McpTestClient) -> None:
    result = await mcp.call("convert_xlsx_to_csv", source=str(WORKBOOK), sheet="Roster")
    assert result["selectedSheet"] == "Roster"
    assert "Ada,ada" in result["text"]
    assert "Course Home" not in result["text"]


async def test_pdf_to_html_extracts_the_text(mcp: McpTestClient) -> None:
    result = await mcp.call("convert_pdf_to_html", source=str(ONEPAGE_PDF))
    assert result["mimetype"] == "text/html"
    assert "<h1>Quantum Field Theory Notes</h1>" in result["text"]
    assert "path integral formulation" in result["text"]


async def test_pptx_to_html_one_section_per_slide(mcp: McpTestClient) -> None:
    result = await mcp.call("convert_pptx_to_html", source=str(SLIDES))
    assert result["mimetype"] == "text/html"
    for number, title in [(1, "Introduction"), (2, "Methods"), (3, "Results")]:
        assert f'data-slide-number="{number}"' in result["text"]
        assert f"<h1>{title}</h1>" in result["text"]
    # the extracted-images map rides along (the fixture's slides carry no images)
    assert result["files"] == {}


# --- binary converters (direct generated calls: the Output Directory is the tmp_path) ---------


async def test_html_to_docx_writes_into_the_output_directory(
    client: HaxcmsClient, haxcms: HaxcmsRuntime, tmp_path: Path
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    result = await generated.convert_html_to_docx(client, settings, str(PAGE_HTML))
    assert result["filename"] == "page.docx"
    assert result["mimetype"] == DOCX_MIME
    path = Path(result["path"])
    assert path.parent == tmp_path
    blob = path.read_bytes()
    assert blob[:2] == b"PK"  # a genuine OOXML zip
    assert result["bytes"] == len(blob)


async def test_html_to_docx_never_overwrites(
    client: HaxcmsClient, haxcms: HaxcmsRuntime, tmp_path: Path
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    first = await generated.convert_html_to_docx(client, settings, str(PAGE_HTML))
    second = await generated.convert_html_to_docx(client, settings, str(PAGE_HTML))
    assert Path(first["path"]).is_file()
    assert Path(second["path"]).is_file()
    assert first["path"] != second["path"]


# --- the Chrome operations (probe-skip when the server has no Chrome) --------------------------


async def _convert_or_skip_chrome(coro: object) -> dict[str, object]:
    """Await a Chrome conversion; skip the test when the server has no Chrome."""
    try:
        result = await coro  # type: ignore[misc]
    except HaxcmsMcpError as exc:
        if "No Chrome" in exc.message:
            pytest.skip(f"the HAXcms server has no Chrome/Chromium: {exc.message}")
        raise
    return result  # type: ignore[return-value]


@pytest.mark.needs_chrome
async def test_html_to_pdf(client: HaxcmsClient, haxcms: HaxcmsRuntime, tmp_path: Path) -> None:
    settings = _output_settings(haxcms, tmp_path)
    result = await _convert_or_skip_chrome(
        generated.convert_html_to_pdf(client, settings, str(PAGE_HTML))
    )
    assert result["mimetype"] == "application/pdf"
    assert Path(str(result["path"])).read_bytes().startswith(b"%PDF")


@pytest.mark.needs_chrome
async def test_docx_to_pdf_names_the_file_after_the_source(
    client: HaxcmsClient, haxcms: HaxcmsRuntime, tmp_path: Path
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    result = await _convert_or_skip_chrome(
        generated.convert_docx_to_pdf(client, settings, str(SYLLABUS))
    )
    assert result["filename"] == "syllabus.pdf"  # source stem + .pdf (raw stream path)
    assert result["mimetype"] == "application/pdf"
    assert Path(str(result["path"])).read_bytes().startswith(b"%PDF")
