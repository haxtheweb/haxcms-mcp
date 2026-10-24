"""Output Directory write rules for exports (PLAN §2.3, T8.3).

Export Tools write into `HAXCMS_MCP_OUTPUT_DIR/<site>/<timestamp>-<name>.<ext>` and return
`{path, bytes, mimetype}` — never the bytes and never a URL. Naming reuses the Phase 7
conversion rules (`services/conversion.py`): untrusted names are sanitized to their last
path segment, and collisions take the first free `<stem>-<n><suffix>` slot so an export
never overwrites an earlier artifact.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from haxcms_mcp.config import Settings
from haxcms_mcp.models.export import ExportArtifact
from haxcms_mcp.services.conversion import _unique_path, safe_filename


def timestamp_prefix(now: datetime | None = None) -> str:
    """`YYYYMMDD-HHMMSS` in local time; `now` is injectable for deterministic tests."""
    moment = now if now is not None else datetime.now().astimezone()
    return moment.strftime("%Y%m%d-%H%M%S")


def export_filename(name: str, *, now: datetime | None = None) -> str:
    """`<timestamp>-<sanitized name>` — the PLAN §2.3 file naming rule."""
    return f"{timestamp_prefix(now)}-{safe_filename(name, 'export')}"


def site_output_dir(settings: Settings, site: str) -> Path:
    """`HAXCMS_MCP_OUTPUT_DIR/<site>/` — every site exports into its own subfolder.

    The site name is sanitized too (defense in depth: it normally arrives already
    lowercased and server-validated, but never trust it as a path segment).
    """
    return settings.output_dir / safe_filename(site, "site")


def write_export(
    content: bytes,
    *,
    settings: Settings,
    site: str,
    name: str,
    mimetype: str,
    format: str,
    page_id: str | None = None,
    now: datetime | None = None,
) -> ExportArtifact:
    """Write one export artifact and return its ExportArtifact record.

    Creates the site subfolder, picks a collision-free timestamped filename, writes the
    bytes, and never returns the content itself (PLAN §2.3).
    """
    path = _unique_path(site_output_dir(settings, site), export_filename(name, now=now))
    path.write_bytes(content)
    return ExportArtifact(
        site=site,
        page_id=page_id,
        format=format,
        path=path,
        bytes=len(content),
        mimetype=mimetype,
        created_at=time.time(),
    )
