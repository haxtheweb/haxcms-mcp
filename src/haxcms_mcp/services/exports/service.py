"""Site and page export service (PLAN Phase 8 T8.3).

Per-format routes, source-verified in ../haxcms-nodejs (e969655c) exports.js and the
system download routes:

* `zip`      — POST `sites/{name}/download` then GET the returned `_published` link.
* `markdown` — the `site/export/markdown` DESCRIPTOR validates the route server-side,
  then `content?mode=concat&format=md` (the descriptor's `export.href`) fetches the text.
* `skeleton` — POST `sites/{name}/download-skeleton`; the skeleton arrives INLINE and is
  serialized to pretty JSON.
* `pdf/docx/epub/html` — GET `site/export/{format}` streams the bytes directly.
* pages — GET `items/{idOrSlug}/export/{format}` streams bytes for all eight formats.

A Chrome-less instance fails PDF conversion with 502 "No Chrome/Chromium executable
found" (PLAN T8.3 guessed 500); the UPSTREAM_ERROR is re-mapped to UNSUPPORTED with the
"instance has no Chrome for PDF rendering" hint.
"""

from __future__ import annotations

import json
from typing import Any

from haxcms_mcp.client import HaxcmsClient, site_api, system_api
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.export import (
    EXPORT_MEDIA_TYPES,
    ITEM_EXPORT_FORMATS,
    SITE_EXPORT_FORMATS,
    ExportArtifact,
    TemplateResult,
)
from haxcms_mcp.services.conversion import safe_filename
from haxcms_mcp.services.exports import output

_CHROME_HINT = (
    "the instance has no Chrome for PDF rendering; export as html, docx or epub "
    "instead, or install Chrome on the server (PUPPETEER_EXECUTABLE_PATH)"
)


def _validate_format(format: str, allowed: tuple[str, ...], *, what: str) -> str:
    """Normalize + allow-list the format locally (the server enforces the same list)."""
    normalized = format.strip().lower()
    if normalized not in allowed:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unsupported {what} export format {format!r}",
            hint=f"supported formats: {', '.join(allowed)}",
        )
    return normalized


def _chrome_reraise(exc: HaxcmsMcpError) -> HaxcmsMcpError:
    """Re-map the Chrome-less conversion failure (502 'No Chrome...') to UNSUPPORTED."""
    if "No Chrome" in exc.message:
        return HaxcmsMcpError(
            ErrorCode.UNSUPPORTED,
            exc.message,
            hint=_CHROME_HINT,
            details=exc.details,
        )
    return exc


async def export_site(
    client: HaxcmsClient, settings: Settings, site: str, format: str
) -> ExportArtifact:
    """Export a whole site into the Output Directory (PLAN T8.3).

    zip -> POST sites/{site}/download then GET {link}; markdown/skeleton go through the
    descriptor routes; pdf/docx/epub/html are direct binary downloads.
    """
    normalized = _validate_format(format, SITE_EXPORT_FORMATS, what="site")
    if normalized == "skeleton":
        return await download_site_skeleton(client, settings, site)
    if normalized == "zip":
        data = await system_api.download_site(client, site)
        link = data.get("link")
        if not isinstance(link, str) or not link:
            raise HaxcmsMcpError(
                ErrorCode.UPSTREAM_ERROR,
                f"the download response for site {site!r} carried no link",
                details={"keys": sorted(str(key) for key in data)},
            )
        raw = await system_api.fetch_published(client, link)
        name = safe_filename(data.get("name"), f"{site}.zip")
    elif normalized == "markdown":
        # the descriptor GET validates the route/format server-side; the bytes come from
        # its export.href target (content?mode=concat&format=md)
        await site_api.site_export(client, site, "markdown")
        raw = (await site_api.site_markdown(client, site)).encode("utf-8")
        name = f"{site}.md"
    else:  # pdf / docx / epub / html — straight binary downloads
        try:
            result = await site_api.site_export(client, site, normalized)
        except HaxcmsMcpError as exc:
            raise _chrome_reraise(exc) from exc
        if not isinstance(result, bytes):
            raise HaxcmsMcpError(
                ErrorCode.UPSTREAM_ERROR,
                f"site export {normalized!r} answered a descriptor, expected binary bytes",
                details={"descriptor_keys": sorted(str(key) for key in result)},
            )
        raw = result
        name = f"{site}.{normalized}"
    return output.write_export(
        raw,
        settings=settings,
        site=site,
        name=name,
        mimetype=EXPORT_MEDIA_TYPES[normalized],
        format=normalized,
    )


async def export_page(
    client: HaxcmsClient, settings: Settings, site: str, page: str, format: str
) -> ExportArtifact:
    """Export one page (id or slug) into the Output Directory (PLAN T8.3).

    The item GET resolves the canonical page_id (and 404s unknown pages early); all
    eight item formats are raw binary downloads server-side.
    """
    normalized = _validate_format(format, ITEM_EXPORT_FORMATS, what="page")
    item = await site_api.get_item(client, site, page)
    page_id = str(item.get("id") or page)
    try:
        raw = await site_api.item_export(client, site, page, normalized)
    except HaxcmsMcpError as exc:
        raise _chrome_reraise(exc) from exc
    # the server names the file after the sanitized slug (then title, then id); nested
    # slugs keep only their last segment locally
    slug = str(item.get("slug") or page_id)
    name = f"{safe_filename(slug, 'page')}.{normalized}"
    return output.write_export(
        raw,
        settings=settings,
        site=site,
        name=name,
        mimetype=EXPORT_MEDIA_TYPES[normalized],
        format=normalized,
        page_id=page_id,
    )


async def save_site_as_template(client: HaxcmsClient, site: str) -> TemplateResult:
    """POST sites/{site}/save-as-template — the server keeps the skeleton as a user
    template under `<configDirectory>/user/skeletons/`, which `list_skeletons` scans."""
    data = await system_api.save_site_as_template(client, site)
    return TemplateResult.from_api(data)


async def download_site_skeleton(
    client: HaxcmsClient, settings: Settings, site: str
) -> ExportArtifact:
    """POST sites/{site}/download-skeleton -> the INLINE skeleton as pretty JSON on disk."""
    data: dict[str, Any] = await system_api.download_site_skeleton(client, site)
    skeleton = data.get("skeleton")
    if not isinstance(skeleton, dict):
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            "download-skeleton returned no skeleton object",
            details={"keys": sorted(str(key) for key in data)},
        )
    raw = json.dumps(skeleton, indent=2, ensure_ascii=False).encode("utf-8")
    name = safe_filename(data.get("filename"), f"{site}.json")
    return output.write_export(
        raw,
        settings=settings,
        site=site,
        name=name,
        mimetype=EXPORT_MEDIA_TYPES["skeleton"],
        format="skeleton",
    )
