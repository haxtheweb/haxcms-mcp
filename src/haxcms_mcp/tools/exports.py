"""Export tools (PLAN Phase 8 T8.4).

Five tools over the export service: whole-site exports in every server format, single-page
exports, the zip convenience alias, server-side template saving, and the skeleton download.
All are read_only-hint FALSE (they produce files / write a server-side template) and
non-destructive. Results are Output Directory artifacts `{path, bytes, mimetype, ...}` —
never the bytes and never a URL (PLAN §2.3): the `path` lives on the MCP server host.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services.exports import service as exports_service
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def register_export_tools(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register the five Phase 8 export tools on the FastMCP app."""

    @mcp.tool(annotations=tool_annotations("Export site"))
    async def export_site(format: str = "zip", site: str | None = None) -> dict[str, Any]:
        """Export a whole site into the Output Directory and return the file record.

        `format`: `zip` (the full site folder as an archive — pages, files, settings),
        `markdown` (every page concatenated into ONE .md, outline order), `skeleton`
        (the reusable HAX skeleton JSON: outline + all page content inline), `html`
        (single-file rendering), and `pdf`/`docx`/`epub` (document conversions — these
        need Chrome on the HAXcms server; without it the call fails as UNSUPPORTED with
        a hint). `site` defaults to the configured Default Site. Returns
        `{site, format, path, bytes, mimetype, created_at}` — `path` is a file on the
        MCP SERVER host, not a URL and not the bytes.
        """
        name = resolve_site(site, settings.default_site)
        artifact = await exports_service.export_site(client, settings, name, format)
        return dump_model(artifact)

    @mcp.tool(annotations=tool_annotations("Export page"))
    async def export_page(page: str, format: str = "md", site: str | None = None) -> dict[str, Any]:
        """Export ONE page into the Output Directory and return the file record.

        `page` is a page id or slug (nested slugs like `unit-one/lesson-one` work).
        `format`: `md` (markdown), `html`, `json` / `yaml` / `xml` (the page record —
        metadata plus content — serialized), and `pdf` / `docx` / `epub` (document
        conversions; `pdf` needs Chrome on the HAXcms server, else UNSUPPORTED).
        `site` defaults to the configured Default Site. Returns
        `{site, page_id, format, path, bytes, mimetype, created_at}`.
        """
        name = resolve_site(site, settings.default_site)
        artifact = await exports_service.export_page(client, settings, name, page, format)
        return dump_model(artifact)

    @mcp.tool(annotations=tool_annotations("Download site zip"))
    async def download_site_zip(site: str | None = None) -> dict[str, Any]:
        """Download the whole site as a .zip archive into the Output Directory.

        Convenience alias for `export_site(format="zip")`, kept for discoverability.
        The archive holds the site folder as stored on the server (pages, files,
        site.json settings; node_modules and .git excluded). `site` defaults to the
        configured Default Site. Returns `{site, format: "zip", path, bytes, mimetype,
        created_at}`.
        """
        name = resolve_site(site, settings.default_site)
        artifact = await exports_service.export_site(client, settings, name, "zip")
        return dump_model(artifact)

    @mcp.tool(annotations=tool_annotations("Save site as template"))
    async def save_site_as_template(site: str | None = None) -> dict[str, Any]:
        """Save the site SERVER-SIDE as a reusable skeleton template.

        Generates the site's skeleton (outline + page content) and stores it in the
        server's user skeleton directory — nothing is written to the Output Directory.
        The template immediately shows up in `list_skeletons` and can seed new sites
        via `create_site_from_skeleton`. `site` defaults to the configured Default
        Site. Returns `{saved, name, filename, path, link}` (`path` is the SERVER's
        filesystem path; `link` is its skeletons API route). Re-running overwrites the
        same template file.
        """
        name = resolve_site(site, settings.default_site)
        result = await exports_service.save_site_as_template(client, name)
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Download site skeleton"))
    async def download_site_skeleton(site: str | None = None) -> dict[str, Any]:
        """Download the site's skeleton JSON into the Output Directory.

        The skeleton is the site as a reusable template document: `{meta, site, build
        {items: [{id, title, slug, order, parent, indent, content, metadata}]}, theme}`
        — every page's CONTENT is inline. Same artifact as `export_site(format=
        "skeleton")` without going through the descriptor route. `site` defaults to
        the configured Default Site. Returns `{site, format: "skeleton", path, bytes,
        mimetype, created_at}`.
        """
        name = resolve_site(site, settings.default_site)
        artifact = await exports_service.download_site_skeleton(client, settings, name)
        return dump_model(artifact)
