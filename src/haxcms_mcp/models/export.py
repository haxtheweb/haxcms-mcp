"""Export artifact models (PLAN Phase 8 T8.1).

Wire shapes source-verified in the sibling checkout ../haxcms-nodejs (e969655c):
`src/siteRoutes/v1/exports.js` (the format lists and the EXPORT_MEDIA_TYPES map are copied
verbatim), `src/systemRoutes/v1/routes/{downloadSite,downloadSiteSkeleton,
saveSiteAsTemplate}.js` and `src/lib/{SiteRoutesMap,SystemRoutesMap}.js` (mounts + auth).

* `GET site/export/{format}` answers BINARY (Content-Disposition attachment) for
  pdf/docx/epub/html and a DESCRIPTOR JSON for zip/markdown/skeleton; the descriptor's
  `export.href` points at the route that really produces the bytes (the system download /
  download-skeleton POSTs, or `content?mode=concat&format=md`).
* `GET items/{idOrSlug}/export/{format}` is a binary download for ALL eight formats
  (json/yaml/xml serialize the item summary + content; md is turndown under `# {title}`).
* `POST sites/{name}/save-as-template` -> `{saved, name, filename, path, link}` — the
  skeleton lands in `<configDirectory>/user/skeletons/`, which the skeletons list route
  scans, so the template becomes visible to `list_skeletons`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

# The server's exact allow-lists (exports.js SITE_EXPORT_FORMATS / ITEM_EXPORT_FORMATS).
SITE_EXPORT_FORMATS: Final[tuple[str, ...]] = (
    "zip",
    "markdown",
    "pdf",
    "docx",
    "epub",
    "html",
    "skeleton",
)
ITEM_EXPORT_FORMATS: Final[tuple[str, ...]] = (
    "pdf",
    "docx",
    "html",
    "md",
    "json",
    "yaml",
    "xml",
    "epub",
)

# exports.js EXPORT_MEDIA_TYPES verbatim (+ the zip/skeleton descriptor media types).
EXPORT_MEDIA_TYPES: Final[dict[str, str]] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "epub": "application/epub+zip",
    "html": "text/html",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "json": "application/json",
    "yaml": "application/yaml",
    "xml": "application/xml",
    "zip": "application/zip",
    "skeleton": "application/json",
}


class ExportArtifact(BaseModel):
    """One exported file written to the Output Directory (PLAN §2.3).

    `page_id` is None for whole-site exports (dump_model drops it there); `bytes` is the
    file size; `created_at` is epoch seconds at write time.
    """

    site: str
    page_id: str | None = None
    format: str
    path: Path
    bytes: int
    mimetype: str
    created_at: float


class TemplateResult(BaseModel):
    """save_site_as_template result — the server kept the skeleton as a user template."""

    model_config = ConfigDict(extra="ignore")

    saved: bool
    name: str
    filename: str
    path: str  # server-side filesystem path (Operator hint; not reachable from the MCP)
    link: str  # API link to the stored skeleton (GET skeletons/{name})

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> TemplateResult:
        """Parse the save-as-template response `data` (shape source-verified)."""
        return cls(
            saved=bool(data.get("saved", True)),
            name=str(data.get("name", "")),
            filename=str(data.get("filename", "")),
            path=str(data.get("path", "")),
            link=str(data.get("link", "")),
        )
