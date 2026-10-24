"""Import and conversion data models (PLAN Phase 7 T7.1).

Wire shapes verified in the sibling sources at ../haxcms-nodejs (e969655c) and
live-probed (findings recorded in PROGRESS.md):

* Document importers (POST actions/import-{docx,pptx,html,xlsx,pdf}) return
  `{items: [...], filename}` — JSONOutlineSchemaItem-shaped records with server-fresh
  ids and `contents` (NOT `content`); importDocx nests children under parent slugs;
  importXlsx adds `selectedSheet`.
* Platform importers (POST site/import/{platform}) return the same items shape and may
  add `files` / `siteFiles` download maps (remote platforms; they feed createSite's
  `build.files`) plus `site.license`. The html platform returns just
  `{items, filename}`.
* Every import/converter error is HTTP 400 with the message on `data.error` (NOT
  `data.message`); envelope.response_message extracts both.
* Converters return their result under `data.contents`: text (docxToHtml, mdToHtml,
  htmlToMd, prettyHtml, jsonToYaml, yamlToJson, pdfToHtml, xlsxToCsv, pptxToHtml) or
  base64 binary (htmlToDocx, htmlToPdf — they add `filename`). docxToPdf bypasses the
  envelope entirely and streams RAW application/pdf bytes.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item

IMPORT_KINDS: Final[tuple[str, ...]] = ("docx", "pptx", "html", "xlsx", "pdf")

# The server enforces EXTENSIONS (importDocx regexes .docx and checks zip magic; the
# html platform allow-lists .html/.htm), so legacy binaries (.doc/.xls/.ppt — never
# parseable by the OOXML/pdf importers) are refused locally instead of after a doomed
# upload.
KIND_BY_EXTENSION: Final[dict[str, str]] = {
    ".docx": "docx",
    ".pptx": "pptx",
    ".html": "html",
    ".htm": "html",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
}

KIND_BY_MIMETYPE: Final[dict[str, str]] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/pdf": "pdf",
}

_KIND_HINT: Final[str] = (
    "supported document kinds: docx (.docx), pptx (.pptx), html (.html/.htm), "
    "xlsx (.xlsx), pdf (.pdf) — detected from the filename extension or mimetype"
)


def detect_import_kind(*, filename: str | None = None, mimetype: str | None = None) -> str:
    """Map a source's filename/mimetype to an importer kind (one of IMPORT_KINDS).

    The extension wins (the server enforces it); the mimetype is the fallback for
    data:/base64: sources without a usable filename. Raises INVALID_ARGUMENT when
    neither identifies a supported kind.
    """
    if filename:
        suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
        kind = KIND_BY_EXTENSION.get(suffix)
        if kind is not None:
            return kind
    if mimetype:
        normalized = mimetype.split(";")[0].strip().lower()
        kind = KIND_BY_MIMETYPE.get(normalized)
        if kind is not None:
            return kind
    seen = filename or mimetype or "an empty source"
    raise HaxcmsMcpError(
        ErrorCode.INVALID_ARGUMENT,
        f"cannot detect an import kind from {seen!r}",
        hint=_KIND_HINT,
    )


class ImportedItem(BaseModel):
    """One imported outline record, BEFORE it exists in any site.

    Server-fresh ids; `contents` holds the imported HTML (the bulk outline API that
    later creates the pages also accepts `content`). Unknown upstream keys ride along
    as extras.
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    title: str = ""
    slug: str | None = None
    parent: str | None = None
    indent: int = 0
    order: int = 0
    contents: str | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> ImportedItem:
        return cls.model_validate(record)


class ImportData(BaseModel):
    """Parsed `data` of an import response (spec ImportData schema, live-verified)."""

    model_config = ConfigDict(extra="allow")

    items: list[ImportedItem] = Field(default_factory=list)
    filename: str | None = None
    files: dict[str, Any] | None = None
    site_files: dict[str, Any] | None = None
    license: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ImportData:
        raw_items = data.get("items")
        items = [
            ImportedItem.from_api(record)
            for record in (raw_items if isinstance(raw_items, list) else [])
            if isinstance(record, dict)
        ]
        site = data.get("site")
        raw_license = site.get("license") if isinstance(site, dict) else None
        files = data.get("files")
        site_files = data.get("siteFiles")
        filename = data.get("filename")
        consumed = {"items", "filename", "files", "siteFiles", "site"}
        extras = {
            key: value
            for key, value in data.items()
            if key not in consumed and key not in cls.model_fields
        }
        return cls(
            items=items,
            filename=filename if isinstance(filename, str) else None,
            files=files if isinstance(files, dict) else None,
            site_files=site_files if isinstance(site_files, dict) else None,
            license=raw_license if isinstance(raw_license, str) else None,
            **extras,
        )


class ImportResult(BaseModel):
    """What the import composites report back (PLAN T7.1).

    `created` holds the re-fetched site Items (real ids/locations); `skipped` counts
    imported records that never materialized in the outline; `warnings` collects
    anything noteworthy (e.g. dropped download maps).
    """

    model_config = ConfigDict(extra="allow")

    site: str
    created: list[Item] = Field(default_factory=list)
    skipped: int = 0
    warnings: list[str] | None = None
    source_filename: str | None = None


class ConversionResult(BaseModel):
    """One converter's result (PLAN T7.1/T7.4): inline `text` OR a written binary file.

    Binary results (htmlToDocx/htmlToPdf base64, docxToPdf raw bytes) are written under
    settings.output_dir and reported as `{path, bytes, mimetype, filename}`; upstream
    extras (xlsxToCsv's sheetNames/selectedSheet, pptxToHtml's files map) ride along.
    """

    model_config = ConfigDict(extra="allow")

    text: str | None = None
    path: str | None = None
    bytes: int | None = None
    mimetype: str | None = None
    filename: str | None = None
