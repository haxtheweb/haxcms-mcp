"""File tools: the eight Phase 5 files tools (PLAN T5.6).

Upload/list/inspect/transform/rename/duplicate/delete site Files, plus the composite
`add_image_from_file` (upload then place a `media-image` block). All routes are bearer +
site token; mutations ride the upstream file-ops limiter (500 per 5 minutes per
user:site, then RATE_LIMITED with the Retry-After in the message).

`source` (upload_file, add_image_from_file) accepts four forms — an http(s) URL, a
`data:` URL, `base64:<name>:<payload>`, or a local path inside HAXCMS_MCP_INPUT_ROOTS.
Uploaded files are referenced from page bodies by their site-relative `url`
(`files/<name>`), which add_image_from_file wires up automatically.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services.catalog.service import CatalogService
from haxcms_mcp.services.files import service as files_service
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def register_files_tools(
    mcp: FastMCP, settings: Settings, client: HaxcmsClient, catalog: CatalogService
) -> None:
    """Register the eight files tools on the FastMCP app (catalog for the composite)."""

    @mcp.tool(annotations=tool_annotations("List files", read_only=True))
    async def list_files(
        type: str | None = None,
        extension: str | None = None,
        name_contains: str | None = None,
        limit: int = 25,
        offset: int = 0,
        site: str | None = None,
    ) -> dict[str, Any]:
        """List the site's Files: `{count, total, page, files, orphans}`.

        Each record carries `uuid` (the stable id for get/rename/transform/delete),
        `name`, `url` (site-relative, e.g. `files/Songline_1.png` — use it as a
        media-image `source`), `mimetype`, `size`, and pixel `width`/`height` for
        images. Filters combine: `type` (image|video|audio|document), `extension`
        (e.g. `png`, with or without the dot), `name_contains`. Paginated with
        `limit`/`offset`. `orphans` lists records whose file vanished from disk —
        reporting only, nothing is deleted. The route auto-indexes on-disk files
        missing from the file store before answering.
        """
        name = resolve_site(site, settings.default_site)
        collection = await files_service.list_files(
            client,
            name,
            type=type,
            extension=extension,
            name_contains=name_contains,
            limit=limit,
            offset=offset,
        )
        return dump_model(collection)

    @mcp.tool(annotations=tool_annotations("Upload file", idempotent=False))
    async def upload_file(
        source: str,
        filename: str | None = None,
        page: str | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file to the site: `{file: {uuid, name, url, mimetype, size, ...}}`.

        `source` is an http(s) URL (fetched by this MCP server), a `data:` URL,
        `base64:<filename>:<payload>`, or a local path — relative paths
        resolve inside HAXCMS_MCP_INPUT_ROOTS and anything outside is rejected
        (FILE_SOURCE_ERROR). MIME is sniffed from the bytes. `filename` overrides the
        stored name (a plain name, no directories); `page` (id or slug) associates the
        upload with that page. Uploading the same source twice creates TWO files —
        check list_files first. Max 50mb (the instance's HAXCMS_UPLOAD_LIMIT); the
        server rejects extensions outside its allow-list. To place an image on a page
        in one step, use add_image_from_file.
        """
        name = resolve_site(site, settings.default_site)
        result = await files_service.upload_file(
            client, settings, name, source, filename=filename, page=page
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Get file", read_only=True))
    async def get_file(uuid: str, site: str | None = None) -> dict[str, Any]:
        """Get one file record by `uuid` (from list_files / upload_file).

        Returns the full record: `path` (on-disk), `fullUrl` (absolute), `url`
        (site-relative `files/<name>`), `mimetype`, `name`, `size`, `dateCreated`,
        and pixel `width`/`height` for images. Unknown uuids fail with NOT_FOUND.
        """
        name = resolve_site(site, settings.default_site)
        record = await files_service.get_file(client, name, uuid)
        return dump_model(record)

    @mcp.tool(annotations=tool_annotations("Rename file"))
    async def rename_file(uuid: str, new_name: str, site: str | None = None) -> dict[str, Any]:
        """Rename a file (changes its stored name and `files/<name>` URL).

        WARNING: pages referencing the OLD url keep pointing at it — HAXcms does not
        rewrite bodies. After renaming an image already placed on a page, update the
        media-image `source` with update_block. `new_name` is a plain filename with
        extension. Returns the raw operation result; re-read with get_file.
        """
        name = resolve_site(site, settings.default_site)
        return await files_service.rename_file(client, name, uuid, new_name)

    @mcp.tool(annotations=tool_annotations("Transform file", idempotent=False))
    async def transform_file(
        uuid: str,
        operation: str,
        size: str | None = None,
        level: str | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Apply one image transform IN PLACE: convert-jpg, scale, sepia,
        black-and-white, rotate-90, or compress.

        `size` rides along for scale (pixel target as a string); `level` for compress
        (light|medium|heavy|maximum, server default medium). Transforms overwrite the
        stored file and repeat calls accumulate (two rotate-90s turn 180 degrees) —
        duplicate_file first to keep the original. Non-image files fail upstream.
        Returns the raw operation result; re-read with get_file for the new record.
        """
        name = resolve_site(site, settings.default_site)
        return await files_service.transform_file(
            client, name, uuid, operation, size=size, level=level
        )

    @mcp.tool(annotations=tool_annotations("Duplicate file", idempotent=False))
    async def duplicate_file(uuid: str, site: str | None = None) -> dict[str, Any]:
        """Duplicate a file: the copy gets a NEW uuid (and a name like `x-1.png`).

        The safe pre-step before a destructive transform: duplicate, then transform
        the copy. Returns the raw operation result; find the copy via list_files.
        """
        name = resolve_site(site, settings.default_site)
        return await files_service.duplicate_file(client, name, uuid)

    @mcp.tool(annotations=tool_annotations("Delete file", destructive=True))
    async def delete_file(uuid: str, site: str | None = None) -> dict[str, Any]:
        """Delete a file permanently (DESTRUCTIVE — confirm with the user first).

        Removes the disk file and its record. Bodies referencing `files/<name>` are
        NOT rewritten — the media-image blocks pointing at it break visually and must
        be removed or re-sourced separately.
        """
        name = resolve_site(site, settings.default_site)
        return await files_service.delete_file(client, name, uuid)

    @mcp.tool(annotations=tool_annotations("Add image from file", idempotent=False))
    async def add_image_from_file(
        page: str,
        source: str,
        alt: str,
        caption: str | None = None,
        citation: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        card: bool = False,
        box: bool = False,
        size: str | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Upload an image AND place it on a page in one step (the tutorial flow).

        `source` works like upload_file (path / URL / data: / base64:); the file is
        uploaded, associated with `page`, and a `media-image` block is inserted whose
        `source` is the new site-relative `files/<name>` url — so metadata.images and
        the body stay consistent. `alt` is required; `caption`/`citation` render under
        the image; `card`/`box` are the HAX treatments; `size` is small|wide.
        Anchor/placement work as in add_block (append/prepend page-level, after/before
        need an anchor). Returns `{file: <upload record>, ...block-op result}` — one
        git revision covers the placement; the upload itself is not revisioned.
        """
        name = resolve_site(site, settings.default_site)
        return await files_service.add_image_from_file(
            client,
            settings,
            catalog,
            name,
            page,
            source,
            alt,
            caption=caption,
            citation=citation,
            anchor=anchor,
            occurrence=occurrence,
            placement=placement,
            card=card,
            box=box,
            size=size,
        )
