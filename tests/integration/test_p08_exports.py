"""Live integration tests for the Phase 8 export service (PLAN T8.4/T8.5 test plan).

Expected values are the LIVE 26.8.1 outputs (probed in Phase 8): the zip carries the
whole site folder (75+ entries incl. site.json), markdown is the concat-mode dump of
every page under `# {title}` headings, html is a single-file rendering, docx and epub
are zip containers that need NO Chrome, and pdf fails on a Chrome-less server with
"No Chrome/Chromium executable found..." — which the service re-maps to UNSUPPORTED
with the PLAN T8.3 hint. The save-as-template skeleton lands in the server's user
skeletons directory and shows up in list_skeletons immediately.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item
from haxcms_mcp.services import sites as sites_service
from haxcms_mcp.services.exports import service
from tests.harness.haxcms_runtime import HaxcmsRuntime

pytestmark = pytest.mark.integration


def _output_settings(haxcms: HaxcmsRuntime, tmp_path: Path) -> Settings:
    """Settings whose Output Directory is the test's tmp_path (artifacts stay local)."""
    return Settings(
        base_url=haxcms.base_url,
        username=haxcms.username,
        password=haxcms.password,
        output_dir=tmp_path,
    )


async def test_site_zip_has_pk_magic_and_contains_site_json(
    client: HaxcmsClient, haxcms: HaxcmsRuntime, site: str, tmp_path: Path
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    artifact = await service.export_site(client, settings, site, "zip")
    blob = artifact.path.read_bytes()
    assert blob[:2] == b"PK"  # zip magic
    assert artifact.bytes == len(blob)
    assert artifact.mimetype == "application/zip"
    assert artifact.format == "zip"
    # PLAN §2.3: <output>/<site>/<timestamp>-<name>.<ext>
    assert artifact.path.parent == tmp_path / site
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert any(name.endswith("site.json") for name in names)
    assert len(names) > 10  # the whole site folder: boilerplate, assets, pages


async def test_site_markdown_and_html_exports_are_non_empty(
    client: HaxcmsClient, haxcms: HaxcmsRuntime, site: str, tmp_path: Path
) -> None:
    settings = _output_settings(haxcms, tmp_path)

    markdown = await service.export_site(client, settings, site, "markdown")
    text = markdown.path.read_text(encoding="utf-8")
    assert text.strip()
    assert "# Home" in text  # concat mode renders every page under its title heading
    assert markdown.mimetype == "text/markdown"

    html = await service.export_site(client, settings, site, "html")
    raw = html.path.read_bytes()
    assert raw
    assert b"<html" in raw
    assert html.mimetype == "text/html"


async def test_page_text_exports_contain_the_title(
    client: HaxcmsClient,
    haxcms: HaxcmsRuntime,
    site: str,
    page: Item,
    tmp_path: Path,
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    for fmt in ("md", "html", "json", "yaml", "xml"):
        artifact = await service.export_page(client, settings, site, page.id, fmt)
        content = artifact.path.read_bytes()
        assert b"Test Page" in content, fmt
        assert artifact.page_id == page.id, fmt
        assert artifact.bytes == len(content), fmt
        assert artifact.path.parent == tmp_path / site, fmt


async def test_site_docx_and_epub_need_no_chrome(
    client: HaxcmsClient, haxcms: HaxcmsRuntime, site: str, tmp_path: Path
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    for fmt in ("docx", "epub"):
        artifact = await service.export_site(client, settings, site, fmt)
        assert artifact.path.read_bytes()[:2] == b"PK", fmt  # both are zip containers
        assert artifact.path.suffix == f".{fmt}", fmt


async def test_site_pdf_needs_chrome_or_fails_unsupported(
    client: HaxcmsClient, haxcms: HaxcmsRuntime, site: str, tmp_path: Path
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    try:
        pdf = await service.export_site(client, settings, site, "pdf")
    except HaxcmsMcpError as exc:
        # the live Chrome-less failure: 502 "No Chrome..." re-mapped to UNSUPPORTED
        assert exc.code is ErrorCode.UNSUPPORTED
        assert "No Chrome" in exc.message
        assert "no Chrome for PDF rendering" in (exc.hint or "")
    else:
        assert pdf.path.read_bytes().startswith(b"%PDF")


async def test_page_pdf_needs_chrome_or_fails_unsupported(
    client: HaxcmsClient,
    haxcms: HaxcmsRuntime,
    site: str,
    page: Item,
    tmp_path: Path,
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    try:
        pdf = await service.export_page(client, settings, site, page.id, "pdf")
    except HaxcmsMcpError as exc:
        assert exc.code is ErrorCode.UNSUPPORTED
        assert "No Chrome" in exc.message
    else:
        assert pdf.path.read_bytes().startswith(b"%PDF")
        assert pdf.page_id == page.id


async def test_save_as_template_shows_up_in_the_skeletons_list(
    client: HaxcmsClient, site: str
) -> None:
    result = await service.save_site_as_template(client, site)
    assert result.saved is True
    assert result.name == site  # the machine name is the template name
    assert result.filename == f"{site}.json"
    assert result.link.endswith(f"skeletons/{site}")

    skeletons = await sites_service.list_skeletons(client)
    assert site in [entry.machine_name for entry in skeletons]

    # and the stored skeleton is readable through the skeletons route
    detail = await sites_service.get_skeleton(client, site)
    assert detail.meta.machine_name == site


async def test_skeleton_download_parses_with_build_items(
    client: HaxcmsClient, haxcms: HaxcmsRuntime, site: str, tmp_path: Path
) -> None:
    settings = _output_settings(haxcms, tmp_path)
    artifact = await service.download_site_skeleton(client, settings, site)
    assert artifact.format == "skeleton"
    assert artifact.mimetype == "application/json"

    skeleton = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert {"meta", "site", "build", "theme"} <= set(skeleton)
    assert skeleton["build"]["type"] == "skeleton"
    items = skeleton["build"]["items"]
    assert isinstance(items, list) and items
    assert items[0]["title"] == "Home"
    assert {"id", "title", "slug", "content"} <= set(items[0])
