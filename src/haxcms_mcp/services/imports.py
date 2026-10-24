"""Import composites (PLAN Phase 7 T7.3).

Facts this module relies on (source-verified at ../haxcms-nodejs e969655c and live-probed
in Phase 7; recorded in PROGRESS.md):

* The importers return outline records with `contents` (NOT `content`), server-fresh
  ids and — for method=site — nested child slugs `parent-slug/child-slug`. The `method`
  switch (importUtils.js, mirrored by importDocx): `site` builds a two-level outline
  from the highest heading (H1-H4; children only when the level is < 4), `branch`
  creates FLAT pages from the top-level headings, `page` wraps everything in ONE page.
  All methods set the root records' `parent` to the given parentId themselves.
* createSite loads `build.items` when `build.structure == "import"` (the `build.type`
  string — e.g. "docx import" — is free-form provenance only) and downloads
  `build.files` / `build.siteFiles` maps through extension allow-lists.
* Every import error is HTTP 400 with `data.error` (some remote platform converters
  use 422); the safeFetch SSRF guard refuses loopback/private/link-local repoUrls, so
  a LOCAL html-platform URL can never be fetched — local HTML goes through the
  document importer instead (kind "html").
* Platform dispatcher set (siteImport.js): haxcms, html, pressbooks, gitbook, notion,
  wordpress, elmsln, drupal-book, plone, openstax, vitepress.
"""

from __future__ import annotations

from typing import Any

from haxcms_mcp.client import HaxcmsClient, system_api
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.imports import ImportData, ImportedItem, ImportResult, detect_import_kind
from haxcms_mcp.models.site import SiteDetail
from haxcms_mcp.services import sites as sites_service
from haxcms_mcp.services.files.sources import resolve_source
from haxcms_mcp.services.outline import fetch_all_items, resolve_parent_id
from haxcms_mcp.services.pages import create_pages

IMPORT_METHODS = ("site", "branch", "page")
CONTENT_TYPES = ("", "course", "portfolio")
PLATFORMS = (
    "haxcms",
    "html",
    "pressbooks",
    "gitbook",
    "notion",
    "wordpress",
    "elmsln",
    "drupal-book",
    "plone",
    "openstax",
    "vitepress",
)


def _bulk_entry(item: ImportedItem) -> dict[str, Any]:
    """Map one imported record onto a bulk-create entry (`contents` -> `content`).

    The importers answer with `contents`; the bulk outline route writes page files from
    `content` (Phase 3). Server-fresh ids are kept so parent/child references survive;
    a `"null"` parent string means detached (create_pages leaves it root-level).
    """
    entry = dump_model(item)
    contents = entry.pop("contents", None)
    if contents is not None and entry.get("content") is None:
        entry["content"] = contents
    if entry.get("parent") == "null":
        entry.pop("parent", None)
    entry.pop("location", None)  # assigned when the page materializes
    return entry


def _validate_method(method: str) -> str:
    normalized = (method or "").strip().lower()
    if normalized not in IMPORT_METHODS:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown import method {method!r}",
            hint=f"supported methods: {', '.join(IMPORT_METHODS)}",
        )
    return normalized


def _validate_content_type(content_type: str) -> str:
    normalized = (content_type or "").strip().lower()
    if normalized not in CONTENT_TYPES:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown import content type {content_type!r}",
            hint="supported types: course, portfolio (or empty for lesson-overview fallbacks)",
        )
    return normalized


def _validate_platform(platform: str) -> str:
    normalized = (platform or "").strip().lower()
    if normalized not in PLATFORMS:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unsupported import platform {platform!r}",
            hint=f"supported platforms: {', '.join(PLATFORMS)}",
        )
    return normalized


async def import_document(
    client: HaxcmsClient,
    settings: Settings,
    site: str,
    source: str,
    *,
    parent: str | None = None,
    method: str = "site",
    content_type: str = "",
) -> ImportResult:
    """Import a document into an EXISTING site: resolve -> convert -> bulk-create pages.

    The kind comes from the source's filename extension or mimetype (docx/pptx/html/
    xlsx/pdf). `method` picks the outline shape (site = two-level outline from the
    highest heading, branch = flat pages from the top-level headings, page = ONE page);
    `parent` (page id or slug, pre-resolved) attaches the imported roots under an
    existing page. `content_type` (course/portfolio) only chooses the fallback content
    for headings with no body. Returns the re-fetched created Items.
    """
    normalized_method = _validate_method(method)
    normalized_type = _validate_content_type(content_type)
    source_file = await resolve_source(source, settings)
    kind = detect_import_kind(filename=source_file.filename, mimetype=source_file.mimetype)

    parent_id: str | None = None
    if parent is not None and parent.strip():
        existing = await fetch_all_items(client, site)
        parent_id = resolve_parent_id(existing, parent)

    data = await system_api.import_document(
        client,
        kind,
        filename=source_file.filename,
        content=source_file.data,
        mimetype=source_file.mimetype,
        method=normalized_method,
        content_type=normalized_type or None,
        parent_id=parent_id,
    )
    parsed = ImportData.from_api(data)
    if not parsed.items:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"the {kind} import produced no outline items",
            hint=(
                "check that the document has content (headings become pages with "
                "method=site/branch)"
            ),
        )
    warnings: list[str] = []
    if parsed.files or parsed.site_files:
        warnings.append(
            "the importer returned download maps (files/siteFiles) which import_document "
            "does not apply; use create_site_from_platform for imports with assets"
        )
    created = await create_pages(client, site, [_bulk_entry(item) for item in parsed.items])
    skipped = max(0, len(parsed.items) - len(created))
    if skipped:
        warnings.append(f"{skipped} imported items did not appear in the outline after creation")
    return ImportResult(
        site=site,
        created=created,
        skipped=skipped,
        warnings=warnings or None,
        source_filename=parsed.filename or source_file.filename,
    )


async def _create_from_import(
    client: HaxcmsClient,
    machine: str,
    data: dict[str, Any],
    parsed: ImportData,
    *,
    build_type: str,
    theme: str,
    description: str,
    license: str | None,
) -> SiteDetail:
    """Shared createSite flow: validate the theme, build the import payload, re-read.

    `build.items` passes the importer's raw records through untouched (exactly what the
    HAX UI does): createSite's structure=="import" branch loads them and materializes
    pages — including the inline data-URI images — itself. `build.files`/`build.siteFiles`
    (remote platforms) ride along for the server's download step.
    """
    warnings: list[str] = []
    themes = await sites_service.list_themes(client)
    record = next((entry for entry in themes if entry.machine_name == theme), None)
    if record is None:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown theme {theme!r}",
            hint="call list_themes for the installed theme machine names",
        )
    if record.hidden:
        warnings.append(f"theme {theme!r} is marked hidden in the registry but was accepted")
    if not parsed.items:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"the {build_type.removesuffix(' import')} import produced no outline items",
            hint="check that the source has content",
        )
    raw_items = data.get("items")
    build: dict[str, Any] = {
        "type": build_type,
        "structure": "import",
        "items": raw_items if isinstance(raw_items, list) else [],
    }
    if parsed.files:
        build["files"] = parsed.files
    if parsed.site_files:
        build["siteFiles"] = parsed.site_files
    payload = {
        "site": {
            "name": machine,
            "description": description,
            "theme": theme,
            "license": license or parsed.license or sites_service.DEFAULT_LICENSE,
            "domain": None,
        },
        "build": build,
    }
    created = await system_api.create_site(client, payload)
    actual = sites_service._created_name(created, machine)
    if actual != machine:
        warnings.append(
            f"name {machine!r} was already taken; the server created {actual!r} instead"
        )
    detail = await sites_service.get_site(client, actual)
    if warnings:
        detail.warnings = [*(detail.warnings or []), *warnings]
    return detail


async def create_site_from_document(
    client: HaxcmsClient,
    settings: Settings,
    name: str,
    source: str,
    *,
    theme: str = sites_service.DEFAULT_THEME,
    description: str = "",
    license: str | None = None,
) -> SiteDetail:
    """Create a NEW site from a document: import with method=site, then createSite.

    The importer's records become the site's whole outline via
    `build:{type:"<kind> import", structure:"import", items}` — createSite materializes
    the pages (and the inline data-URI images become site files). `license` defaults to
    the import's own `site.license` when present, else by-sa.
    """
    machine = sites_service.validate_site_name(name)
    source_file = await resolve_source(source, settings)
    kind = detect_import_kind(filename=source_file.filename, mimetype=source_file.mimetype)
    data = await system_api.import_document(
        client,
        kind,
        filename=source_file.filename,
        content=source_file.data,
        mimetype=source_file.mimetype,
        method="site",
    )
    parsed = ImportData.from_api(data)
    return await _create_from_import(
        client,
        machine,
        data,
        parsed,
        build_type=f"{kind} import",
        theme=theme,
        description=description,
        license=license,
    )


async def create_site_from_platform(
    client: HaxcmsClient,
    name: str,
    platform: str,
    url: str,
    *,
    theme: str = sites_service.DEFAULT_THEME,
    description: str = "",
    license: str | None = None,
) -> SiteDetail:
    """Create a NEW site from a remote platform export (POST site/import/{platform}).

    The server fetches `url` itself (repoUrl mode): its SSRF guard refuses loopback,
    private, link-local and metadata addresses, so LOCAL HTML cannot be imported this
    way — use create_site_from_document with the .html file instead. Remote platforms
    return `files`/`siteFiles` download maps which ride along in `build` for createSite
    to fetch; `license` defaults to the import's `site.license`, else by-sa.
    """
    machine = sites_service.validate_site_name(name)
    normalized = _validate_platform(platform)
    repo_url = (url or "").strip()
    if not repo_url:
        raise HaxcmsMcpError(ErrorCode.INVALID_ARGUMENT, "url must not be empty")
    try:
        data = await system_api.import_platform(
            client, normalized, repo_url=repo_url, method="site"
        )
    except HaxcmsMcpError as exc:
        if exc.code is ErrorCode.INVALID_ARGUMENT and (
            "SSRF" in exc.message or "fetch" in exc.message.lower()
        ):
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                exc.message,
                hint=(
                    "the HAXcms server could not fetch this URL (private or unreachable): "
                    "its SSRF guard refuses loopback, private, link-local and metadata "
                    "addresses; import local HTML with create_site_from_document instead"
                ),
                details=exc.details,
            ) from exc
        raise
    parsed = ImportData.from_api(data)
    return await _create_from_import(
        client,
        machine,
        data,
        parsed,
        build_type=f"{normalized} import",
        theme=theme,
        description=description,
        license=license,
    )
