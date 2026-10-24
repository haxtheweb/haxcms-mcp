"""Typed Site API endpoint helpers (PLAN Phase 2 T2.2, Phase 3 T3.2).

Auth per `specs/site-spec.yaml` `security:` blocks (source of truth — API-REF §2.6 was wrong
once already):

* PUBLIC reads (`security: []` global, line 47): `GET site`, `GET themes`, `GET themes/active`,
  `GET items`, `GET items/{idOrSlug}`, `GET search`, `GET tags` — confirmed anonymous 200s in
  the Phase 2 probe. The item/search/tags reads are sent with `auth="bearer"` anyway: the
  routes upgrade visibility for authenticated callers (unpublished items; verified in
  siteRouteUtils.filterItemsForAnonymousAccess).
* bearer + SITE token: `POST items`, `PATCH items/{idOrSlug}`, `DELETE items/{idOrSlug}`,
  `PATCH site/outline`, `POST site/normalize-slugs`, all three revision routes, and all
  five Phase 5 files routes (`GET/POST files`, `GET/PATCH/DELETE files/{uuid}`).

Live facts these helpers encode (Phase 3 source reads, recorded in PROGRESS.md):

* `GET items` paginates: default `page.limit` 25, max 200 — callers must paginate.
* `{idOrSlug}` routes are single-segment Express params and the server `decodeURIComponent`s
  them, so nested slugs (which contain `/`) travel percent-encoded (`quote(..., safe="")`).
* `PATCH items/{idOrSlug}` takes `{site:{name}, operation, ...fields}`, ONE operation per
  request; the response `data` is the updated item (summary shape).
* `POST items` single form: `{site:{name}, node:{id,title,location,duplicate,contents},
  parent, order, indent, description, metadata}`; bulk form: `{site:{name}, items:[...]}`
  (response `data` is the LAST created item — createNode.js).
* revisions `{revisionId}` must be a 7-64 hex git hash; restore needs no body.
* `POST site/normalize-slugs` accepts `preview: true` in the body (no writes, returns the
  planned changes); response `data = {changed, preview, changes, skipped}`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.client.envelope import error_from_response, unwrap_dict, unwrap_full

# --- Phase 2: public site-level reads -------------------------------------------------


async def site_summary(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """GET site -> public SiteSummary `{id, name, title, ..., counts, links}`."""
    response = await client.request("GET", client.site_path(site, "site"), auth="none")
    return unwrap_dict(response)


async def list_site_themes(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """GET themes -> ThemeCollection `{count, total, page, themes: [...]}` (public)."""
    response = await client.request("GET", client.site_path(site, "themes"), auth="none")
    return unwrap_dict(response)


async def active_theme(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """GET themes/active -> the site's active theme record (public)."""
    response = await client.request("GET", client.site_path(site, "themes/active"), auth="none")
    return unwrap_dict(response)


# --- Phase 3: items / outline ----------------------------------------------------------


def _item_path(client: HaxcmsClient, site: str, id_or_slug: str, suffix: str = "") -> str:
    """`items/{quoted}` (+suffix) — slugs may contain `/`, so percent-encode the segment."""
    segment = quote(id_or_slug, safe="")
    tail = f"/{suffix.lstrip('/')}" if suffix else ""
    return client.site_path(site, f"items/{segment}{tail}")


async def list_items(
    client: HaxcmsClient, site: str, *, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET items -> ItemCollection `{count, total, page, items}`.

    `params` carries the raw query keys (`filter.parent`, `page.limit`, `include`, ...).
    Bearer-authenticated: unpublished items are included.
    """
    response = await client.request(
        "GET", client.site_path(site, "items"), params=params, auth="bearer"
    )
    return unwrap_dict(response)


async def get_item(
    client: HaxcmsClient, site: str, id_or_slug: str, *, include_content: bool = False
) -> dict[str, Any]:
    """GET items/{idOrSlug} -> one item record (404 -> NOT_FOUND; bearer sees unpublished)."""
    params = {"include": "content"} if include_content else None
    response = await client.request(
        "GET", _item_path(client, site, id_or_slug), params=params, auth="bearer"
    )
    return unwrap_dict(response)


async def create_item(client: HaxcmsClient, site: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST items (single `node` form or bulk `items` form) -> the created item (bulk: the
    LAST created item — read createNode.js; callers that need every id supply their own)."""
    response = await client.request(
        "POST", client.site_path(site, "items"), json=payload, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def update_item(
    client: HaxcmsClient, site: str, id_or_slug: str, operation: str, **fields: Any
) -> dict[str, Any]:
    """PATCH items/{idOrSlug} with ONE nodeDetailOperation -> the updated item record."""
    body: dict[str, Any] = {"site": {"name": site}, "operation": operation, **fields}
    response = await client.request(
        "PATCH", _item_path(client, site, id_or_slug), json=body, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def delete_item(client: HaxcmsClient, site: str, id_or_slug: str) -> dict[str, Any]:
    """DELETE items/{idOrSlug} -> the deleted item record (children re-parent to the root)."""
    response = await client.request(
        "DELETE",
        _item_path(client, site, id_or_slug),
        json={"site": {"name": site}},
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


async def save_outline(
    client: HaxcmsClient, site: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """PATCH site/outline -> `{items: [...]}` (the FULL manifest after the save).

    Items omitted from `items` are NOT deleted (saveOutline.js: only an explicit
    `delete: true` entry removes a page) but they also keep their old order — send the
    complete list. Unknown ids are created with server-assigned ids.
    """
    response = await client.request(
        "PATCH",
        client.site_path(site, "site/outline"),
        json={"site": {"name": site}, "items": items},
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


async def normalize_slugs(
    client: HaxcmsClient, site: str, *, preview: bool = False
) -> dict[str, Any]:
    """POST site/normalize-slugs -> `{changed, preview, changes, skipped}`.

    Regenerates every slug from its title per Pathauto; items with
    `metadata.overridePathauto` land in `skipped`. `preview=True` plans without writing.
    """
    response = await client.request(
        "POST",
        client.site_path(site, "site/normalize-slugs"),
        json={"site": {"name": site}, "preview": preview},
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


# --- Phase 3: revisions -----------------------------------------------------------------


async def list_revisions(
    client: HaxcmsClient, site: str, id_or_slug: str, *, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """GET items/{idOrSlug}/revisions -> `{nodeId, ..., count, total, revisions: [...]}`."""
    response = await client.request(
        "GET",
        _item_path(client, site, id_or_slug, "revisions"),
        params={"page.limit": limit, "page.offset": offset},
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


async def get_revision(
    client: HaxcmsClient, site: str, id_or_slug: str, revision_id: str
) -> dict[str, Any]:
    """GET items/{idOrSlug}/revisions/{hash} -> `{nodeId, ..., revision, content}`."""
    response = await client.request(
        "GET",
        _item_path(client, site, id_or_slug, f"revisions/{quote(revision_id, safe='')}"),
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


async def restore_revision(
    client: HaxcmsClient, site: str, id_or_slug: str, revision_id: str
) -> dict[str, Any]:
    """POST items/{idOrSlug}/revisions/{hash}/restore -> `{nodeId, restoredFromHash, ...}`."""
    response = await client.request(
        "POST",
        _item_path(client, site, id_or_slug, f"revisions/{quote(revision_id, safe='')}/restore"),
        json={"site": {"name": site}},
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


# --- Phase 3: search and tags --------------------------------------------------------------


async def search(
    client: HaxcmsClient, site: str, q: str, *, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET search?q=... -> `{count, total, page, results: [...]}` (400 when q is empty)."""
    query: dict[str, Any] = {"q": q, **(params or {})}
    response = await client.request(
        "GET", client.site_path(site, "search"), params=query, auth="bearer"
    )
    return unwrap_dict(response)


async def list_tags(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """GET tags -> `{count, total, page, tags: [{tag, count}]}` sorted by -count."""
    response = await client.request("GET", client.site_path(site, "tags"), auth="bearer")
    return unwrap_dict(response)


# --- Phase 4: content ---------------------------------------------------------------------


def _content_path(client: HaxcmsClient, site: str, id_or_slug: str) -> str:
    segment = quote(id_or_slug, safe="")  # nested slugs contain `/`
    return client.site_path(site, f"content/{segment}")


async def get_content(
    client: HaxcmsClient, site: str, id_or_slug: str, *, fmt: str = "json"
) -> dict[str, Any]:
    """GET content/{idOrSlug}?format=json -> `{id, slug, title, format, mode, body, links}`.

    Always read with `fmt="json"`: for a single page the route wraps non-JSON-format
    responses in a `<pre>` envelope (live-verified Phase 3). Bearer so unpublished pages
    are readable. `body` never contains the `<page-break>` (stripped on save).
    """
    response = await client.request(
        "GET", _content_path(client, site, id_or_slug), params={"format": fmt}, auth="bearer"
    )
    return unwrap_dict(response)


async def patch_content(
    client: HaxcmsClient,
    site: str,
    id_or_slug: str,
    body: str,
    *,
    schema: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PATCH content/{idOrSlug} -> the updated item record (updateContent → saveNode).

    `body` MUST start with the `<page-break>` envelope — without it saveNode parses zero
    segments and silently writes nothing (still 200). `schema` fills metadata.images/videos;
    `details` merges node details (configure/advanced shapes).
    """
    payload: dict[str, Any] = {"site": {"name": site}, "body": body}
    if schema is not None:
        payload["schema"] = schema
    if details is not None:
        payload["details"] = details
    response = await client.request(
        "PATCH",
        _content_path(client, site, id_or_slug),
        json=payload,
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


# --- Phase 4: read-only catalogs (API-REF §8) -------------------------------------------------
#
# Bearer-authenticated (optional upstream, consistent with the other reads); the catalog
# service treats every failure here as "live data unavailable" and stays bundled-only.


async def list_blocks(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """GET blocks -> block records + usage counts."""
    response = await client.request("GET", client.site_path(site, "blocks"), auth="bearer")
    return unwrap_dict(response)


async def get_block(
    client: HaxcmsClient, site: str, tag: str, *, include: str | None = None
) -> dict[str, Any]:
    """GET blocks/{tag}[?include=haxProperties,haxSchema,haxElementSchema] -> one record."""
    params = {"include": include} if include else None
    response = await client.request(
        "GET",
        client.site_path(site, f"blocks/{quote(tag, safe='')}"),
        params=params,
        auth="bearer",
    )
    return unwrap_dict(response)


async def list_schemas(
    client: HaxcmsClient, site: str, *, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET schemas?filter.kind=haxProperties&filter.webcomponentName={tag} -> records.

    Served when the instance can find `<pkg>/lib/<tag>.haxProperties.json` in its build.
    """
    response = await client.request(
        "GET", client.site_path(site, "schemas"), params=params, auth="bearer"
    )
    return unwrap_dict(response)


async def get_custom_element(client: HaxcmsClient, site: str, tag: str) -> dict[str, Any]:
    """GET custom-elements/{tag} -> the wc-registry entry (404 when the tag is unknown)."""
    response = await client.request(
        "GET", client.site_path(site, f"custom-elements/{quote(tag, safe='')}"), auth="bearer"
    )
    return unwrap_dict(response)


# --- Phase 5: files (API-REF §6) ----------------------------------------------------------
#
# All five routes are bearer + SITE token per specs/site-spec.yaml (listFiles, createFile,
# getFileByUuid, updateFileByUuid, deleteFileByUuid — each `security: [bearerAuth,
# siteTokenHeader]`). Mutations are limited upstream to 500 per 5 minutes per user:site,
# then 429 with Retry-After (the envelope mapper already surfaces RATE_LIMITED with the
# retry-after appended).


def _file_path(client: HaxcmsClient, site: str, uuid: str) -> str:
    return client.site_path(site, f"files/{quote(uuid, safe='')}")


async def list_files(
    client: HaxcmsClient, site: str, *, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET files -> FileCollection `{count, total, page, files, orphans}`.

    `params` carries the raw query keys (`filter.type`, `filter.extension`,
    `filter.startsWith`, `filter.nameContains`, `filename`, `page.limit`, `page.offset`,
    `sort`, `fields`). The route auto-indexes on-disk files missing from files.json
    before returning, and flags records whose disk file is gone in `orphans`.
    """
    response = await client.request(
        "GET", client.site_path(site, "files"), params=params, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def upload_file(
    client: HaxcmsClient,
    site: str,
    *,
    filename: str,
    content: bytes,
    mimetype: str,
    node_id: str | None = None,
) -> dict[str, Any]:
    """POST files (multipart) -> `{file: {path, fullUrl, url, type, name, size, uuid, ...}}`.

    The multipart field is `file-upload` (the server also accepts `upload`, `file` or
    `files[]` via multer `.any()`, in that preferred order); `nodeId` optionally associates
    the upload with a page. Upload limit defaults to 50mb (`HAXCMS_UPLOAD_LIMIT`); a
    disallowed extension is refused with HTTP 500 'File type not allowed' (-> UPSTREAM_ERROR).
    """
    files = {"file-upload": (filename, content, mimetype)}
    data = {"nodeId": node_id} if node_id else None
    response = await client.request(
        "POST",
        client.site_path(site, "files"),
        data=data,
        files=files,
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


async def get_file(client: HaxcmsClient, site: str, uuid: str) -> dict[str, Any]:
    """GET files/{uuid} -> one FileRecord (404 -> NOT_FOUND)."""
    response = await client.request(
        "GET", _file_path(client, site, uuid), auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def update_file(
    client: HaxcmsClient, site: str, uuid: str, operation: str, **args: Any
) -> dict[str, Any]:
    """PATCH files/{uuid} `{operation, newName?, size?, level?}` -> the operation result.

    Operations: rename, convert-jpg, scale, sepia, black-and-white, rotate-90, compress
    (`level`: light|medium|heavy|maximum), duplicate. Delete uses its own route.
    """
    body: dict[str, Any] = {"operation": operation, **args}
    response = await client.request(
        "PATCH", _file_path(client, site, uuid), json=body, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def delete_file(client: HaxcmsClient, site: str, uuid: str) -> dict[str, Any]:
    """DELETE files/{uuid} -> the deletion result (no request body)."""
    response = await client.request(
        "DELETE", _file_path(client, site, uuid), auth="bearer+site", site=site
    )
    return unwrap_dict(response)


# --- Phase 6: site settings -----------------------------------------------------------------
#
# All settings routes are bearer + SITE token ('authenticated-site' — the OpenAPI security
# block `[bearerAuth, siteTokenHeader]` read by validateSiteApiRouteAccess) and resolve the
# site from the URL path; site.js `delegateToLegacySiteWrite` requires the site-token header
# and auto-fills body.site.name. Live contract source-verified against ../haxcms-nodejs
# (e969655c), recorded in PROGRESS.md:
#
# * PATCH site (saveManifest): only the SCOPED-DETAILS path is reachable — the full form path
#   needs a haxcms_form_token that only HAXCMS.loadForm mints and NO route exposes loadForm.
#   Scoped detection requires body.manifest to be an OBJECT plus at least one of
#   manifest.site['manifest-title'], manifest.site['manifest-metadata-site-homePageId'],
#   manifest.seo['manifest-metadata-site-settings-sw'|'-forceUpgrade'] (flat body.title/
#   homePageId/sw/forceUpgrade alternates also count) and no haxcms_form_id/token keys.
#   Writes ONLY title (HTML-tag-stripped), homePageId (must match a manifest.items[].id
#   EXACTLY or the key is silently DELETED), settings.sw, settings.forceUpgrade + a version
#   stamp. Response data = the FULL manifest. Gate: siteManifest -> 403.
# * PATCH site/appearance: strict allow-lists — top {site, manifest}, site {name}, manifest
#   {theme}, theme = the 14 manifest-metadata-theme-* keys; ANY extra key -> 400 'Invalid
#   request'. cssVariable is normalized to --simple-colors-default-theme-<color>-7; a new
#   element REPLACES the whole metadata.theme with the registry theme. Response data =
#   {saved: true, appearance: {theme: true}} (NOT the manifest). Gate: themeManifest -> 403.
# * PATCH site/seo: short wrapper keys author.{license,image,name,email,phone,location,
#   website,website2,socialLink,socialLink2} / seo.{description,domain,logo,lang,gaID,
#   private,canonical,pathauto,publishPagesOn}; only PRESENT keys are written; response
#   data = the FULL manifest. Gate: seoManifest -> 403.
# * PATCH site/editor: platform.audience 'novice'|'expert' (400 otherwise); response data =
#   the FULL manifest. Gate: siteManifest -> 403 'Editor settings are disabled...'.
# * PATCH site/blocks: platform.allowedBlocks null (unrestricted) | array; each tag must
#   match /^[a-z][a-z0-9]*$/ or exist in the WC registry, else a GENERIC 400 'Invalid
#   request'; stored deduped + sorted; response data = the FULL manifest. Gate: siteManifest.
# * PATCH site/platform: platform.features — keys from the 21 validFeatureKeys or the legacy
#   aliases, values STRICT JSON booleans; REPLACE semantics (features = {} then only the
#   payload keys are stored), so callers MUST send the full merged set. Response data = the
#   FULL manifest. Gate: siteManifest -> 403 'Platform settings are disabled...'.
# * POST site/updateAlternativeFormats: {format?} in rss|sitemap|search|llms|service-worker
#   (absent/null -> all); response data = {updated: true, site: {name}, format}.
# * GET /_sites/{site}/site.json: PUBLIC static manifest, raw JSON (no {status,data}
#   envelope) — the only complete settings view (SiteSummary has no metadata block).


async def fetch_site_manifest(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """GET /_sites/{site}/site.json -> the raw public manifest (no envelope to unwrap)."""
    response = await client.request("GET", f"/_sites/{quote(site, safe='')}/site.json", auth="none")
    return unwrap_full(response)


async def update_manifest(
    client: HaxcmsClient, site: str, details: dict[str, Any]
) -> dict[str, Any]:
    """PATCH site (scoped-details path) -> the FULL manifest.

    `details` must carry the `manifest` object (scoped detection requires it) with any of
    manifest.site['manifest-title'], manifest.site['manifest-metadata-site-homePageId'],
    manifest.seo['manifest-metadata-site-settings-sw'|'-forceUpgrade'] — and NO
    haxcms_form_id/haxcms_form_token keys (those select the unreachable form path).
    """
    body = {"site": {"name": site}, **details}
    response = await client.request(
        "PATCH", client.site_path(site, "site"), json=body, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def update_appearance(
    client: HaxcmsClient, site: str, theme: dict[str, Any]
) -> dict[str, Any]:
    """PATCH site/appearance -> {saved, appearance}.

    `theme` holds ONLY manifest-metadata-theme-* keys (element, variables-image/-imageAlt/
    -imageLink/-cssVariable/-palette/-icon, regions-header/-sidebarFirst/-sidebarSecond/
    -contentTop/-contentBottom/-footerPrimary/-footerSecondary); any other key is a 400.
    Region values are arrays of page ids; variables are strings ('' deletes the key).
    """
    body = {"site": {"name": site}, "manifest": {"theme": theme}}
    response = await client.request(
        "PATCH", client.site_path(site, "site/appearance"), json=body, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def update_seo(
    client: HaxcmsClient,
    site: str,
    *,
    seo: dict[str, Any] | None = None,
    author: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PATCH site/seo -> the FULL manifest.

    `seo` / `author` use the SHORT wrapper keys (seo.description/domain/logo/lang/gaID/
    private/canonical/pathauto/publishPagesOn; author.license/image/name/email/phone/
    location/website/website2/socialLink/socialLink2); only present keys are written.
    """
    body: dict[str, Any] = {"site": {"name": site}}
    if seo is not None:
        body["seo"] = seo
    if author is not None:
        body["author"] = author
    response = await client.request(
        "PATCH", client.site_path(site, "site/seo"), json=body, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def update_editor(client: HaxcmsClient, site: str, audience: str) -> dict[str, Any]:
    """PATCH site/editor -> the FULL manifest (audience: 'novice' | 'expert')."""
    body = {"site": {"name": site}, "platform": {"audience": audience}}
    response = await client.request(
        "PATCH", client.site_path(site, "site/editor"), json=body, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def update_allowed_blocks(
    client: HaxcmsClient, site: str, allowed_blocks: list[str] | None
) -> dict[str, Any]:
    """PATCH site/blocks -> the FULL manifest (null = unrestricted; else the tag list)."""
    body = {"site": {"name": site}, "platform": {"allowedBlocks": allowed_blocks}}
    response = await client.request(
        "PATCH", client.site_path(site, "site/blocks"), json=body, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def update_platform(
    client: HaxcmsClient, site: str, features: dict[str, bool]
) -> dict[str, Any]:
    """PATCH site/platform -> the FULL manifest.

    REPLACE semantics upstream: `features` must be the FULL merged flag set (strict JSON
    booleans), not just the changed keys — a partial payload wipes every unlisted flag.
    """
    body = {"site": {"name": site}, "platform": {"features": features}}
    response = await client.request(
        "PATCH", client.site_path(site, "site/platform"), json=body, auth="bearer+site", site=site
    )
    return unwrap_dict(response)


async def update_alternative_formats(
    client: HaxcmsClient, site: str, fmt: str | None = None
) -> dict[str, Any]:
    """POST site/updateAlternativeFormats -> {updated, site, format} (None = all formats)."""
    body: dict[str, Any] = {"site": {"name": site}}
    if fmt is not None:
        body["format"] = fmt
    response = await client.request(
        "POST",
        client.site_path(site, "site/updateAlternativeFormats"),
        json=body,
        auth="bearer+site",
        site=site,
    )
    return unwrap_dict(response)


# --- Phase 8: exports (T8.2) -------------------------------------------------------------------
# Source-verified in ../haxcms-nodejs/src/siteRoutes/v1/exports.js + SiteRoutesMap.js:
# GET site/export/{format} sends a Content-Disposition attachment (RAW bytes, no envelope)
# for pdf/docx/epub/html and a DESCRIPTOR JSON for zip/markdown/skeleton; unsupported formats
# are 400 {data: {message, supportedFormats}}; conversion failures (pdf/docx — e.g. no Chrome
# for pdf) are JSON {status, data.message} at 502. GET items/{idOrSlug}/export/{format} is a
# binary download for ALL eight item formats. Both use the export timeout (rendering a whole
# site through Puppeteer/epub-gen is slow).


async def site_export(client: HaxcmsClient, site: str, format: str) -> bytes | dict[str, Any]:
    """GET site/export/{format} -> BYTES (pdf/docx/epub/html) or a DESCRIPTOR dict.

    The descriptor (zip/markdown/skeleton) is `{format, supportedFormats, export: {rel,
    mediaType, href, ...}, links}` — `export.href` names the route that really produces
    the bytes (system `download`/`download-skeleton` POSTs, or `content?mode=concat&
    format=md`). Discriminator: the Content-Type the server set (application/json vs the
    format's binary media type).
    """
    response = await client.request(
        "GET",
        client.site_path(site, f"site/export/{format}"),
        auth="bearer",
        timeout=client.settings.export_timeout_s,
    )
    if response.status_code >= 400:
        raise error_from_response(response)
    if response.headers.get("content-type", "").startswith("application/json"):
        return unwrap_dict(response)
    return response.content


async def item_export(client: HaxcmsClient, site: str, id_or_slug: str, format: str) -> bytes:
    """GET items/{idOrSlug}/export/{format} -> RAW bytes for EVERY format.

    Formats: pdf|docx|html|md|json|yaml|xml|epub. json/yaml/xml serialize the item summary
    PLUS its `content`; md is turndown markdown under a `# {title}` heading; the
    Content-Disposition filename is the sanitized slug. Anonymous callers 404 on
    unpublished items — we send bearer, so unpublished items export too.
    """
    response = await client.request(
        "GET",
        _item_path(client, site, id_or_slug, f"export/{format}"),
        auth="bearer",
        timeout=client.settings.export_timeout_s,
    )
    if response.status_code >= 400:
        raise error_from_response(response)
    return response.content


async def site_markdown(client: HaxcmsClient, site: str) -> str:
    """GET content?mode=concat&format=md -> the whole site as concatenated markdown.

    This is the href the `site/export/markdown` descriptor points at; `format=md` selects
    the raw text/markdown representation (sendFormattedResponse's rawByFormat), NOT the
    JSON envelope.
    """
    response = await client.request(
        "GET",
        client.site_path(site, "content"),
        params={"mode": "concat", "format": "md"},
        auth="bearer",
        timeout=client.settings.export_timeout_s,
    )
    if response.status_code >= 400:
        raise error_from_response(response)
    return response.text
