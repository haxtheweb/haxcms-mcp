"""Import tools (PLAN Phase 7 T7.5).

Import documents into an existing site and create new sites from documents or remote
platform exports. All three are non-read-only (they create pages/sites), non-destructive
and NOT idempotent — importing twice duplicates the content. `source` follows the Sources
convention: a local path under the configured input roots, an http(s) URL, a `data:` URL
or inline `base64:`.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services import imports as imports_service
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def register_import_tools(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register the three Phase 7 import tools on the FastMCP app."""

    @mcp.tool(annotations=tool_annotations("Import document into site", idempotent=False))
    async def import_document(
        source: str,
        parent: str | None = None,
        method: str = "site",
        content_type: str = "",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Import a document into an EXISTING site, creating its pages in bulk.

        `source` is a path / URL / data: / base64: document — supported kinds: .docx
        (Word), .pptx (PowerPoint), .html/.htm, .xlsx (Excel), .pdf. The kind is detected
        from the filename extension (or mimetype). `method` shapes the result: `site`
        builds a two-level outline from the document's highest heading level (children
        only below H4), `branch` creates FLAT pages from the top-level headings, `page`
        wraps everything into ONE page. `parent` (page id or slug) attaches the imported
        pages under an existing page. `content_type` (`course` or `portfolio`) only picks
        the placeholder content for headings with no body. Returns the created pages
        (re-fetched, in outline order) plus `skipped` and `warnings`. NOT idempotent:
        importing twice duplicates the pages.
        """
        name = resolve_site(site, settings.default_site)
        result = await imports_service.import_document(
            client,
            settings,
            name,
            source,
            parent=parent,
            method=method,
            content_type=content_type,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Create site from document", idempotent=False))
    async def create_site_from_document(
        name: str,
        source: str,
        theme: str = "clean-one",
        description: str = "",
        license: str | None = None,
    ) -> dict[str, Any]:
        """Create a NEW site whose whole outline comes from a document import.

        `name` is the machine name (lowercase letters, digits, - and _). `source` is a
        path / URL / data: / base64: document — supported kinds: .docx (Word), .pptx
        (PowerPoint), .html/.htm, .xlsx (Excel), .pdf. The document is imported with
        method=site (two-level outline from the highest heading level); embedded images
        are materialized as site files during creation. `theme` must exist in the live
        registry (list_themes). `license` is a Creative Commons identifier (default
        by-sa). Returns the created site's detail record — read its `name`: on a
        duplicate request the server silently creates `<name>-1`.
        """
        result = await imports_service.create_site_from_document(
            client,
            settings,
            name,
            source,
            theme=theme,
            description=description,
            license=license,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Create site from platform", idempotent=False))
    async def create_site_from_platform(
        name: str,
        platform: str,
        url: str,
        theme: str = "clean-one",
        description: str = "",
        license: str | None = None,
    ) -> dict[str, Any]:
        """Create a NEW site from a remote platform export the SERVER fetches.

        `platform` is one of: haxcms, html, pressbooks, gitbook, notion, wordpress,
        elmsln, drupal-book, plone, openstax, vitepress. `url` is the export's public URL
        (repoUrl) — the HAXcms server downloads it, so it must be publicly reachable: the
        server's SSRF guard refuses loopback, private, link-local and metadata addresses
        (INVALID_ARGUMENT). For LOCAL HTML use create_site_from_document with the .html
        file instead. Remote platforms may bring asset download maps which the server
        applies during creation. `theme` must exist in the live registry; `license`
        defaults to the import's own license, else by-sa. Returns the created site's
        detail record (read its `name` — duplicates become `<name>-1`).
        """
        result = await imports_service.create_site_from_platform(
            client,
            name,
            platform,
            url,
            theme=theme,
            description=description,
            license=license,
        )
        return dump_model(result)
