"""Unit tests for the Output Directory write rules (PLAN §2.3 / Phase 8 test plan).

Covers the naming (`<output>/<site>/<timestamp>-<name>.<ext>`), collision handling
(first free `-<n>` slot, never overwrite), site-subfolder creation, and the sanitization
of untrusted names. The clock is injected so timestamps are deterministic.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from haxcms_mcp.config import Settings
from haxcms_mcp.services.exports import output

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 15, 4, 5)
PREFIX = "20261001-150405"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        base_url="http://hax.invalid",
        username="envuser",
        password="envpass",
        output_dir=tmp_path,
    )


def test_timestamp_prefix_matches_the_spec_shape() -> None:
    assert re.fullmatch(r"\d{8}-\d{6}", output.timestamp_prefix(NOW))
    assert output.timestamp_prefix(NOW) == PREFIX


def test_export_filename_combines_timestamp_and_sanitized_name() -> None:
    assert output.export_filename("demo.zip", now=NOW) == f"{PREFIX}-demo.zip"
    # untrusted names lose any directory part; empty names fall back to "export"
    assert output.export_filename("../../etc/passwd", now=NOW) == f"{PREFIX}-passwd"
    assert output.export_filename("a\\b\\evil.zip", now=NOW) == f"{PREFIX}-evil.zip"
    assert output.export_filename("", now=NOW) == f"{PREFIX}-export"


def test_site_output_dir_is_the_site_subfolder(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert output.site_output_dir(settings, "demo") == tmp_path / "demo"
    # defense in depth: even a traversal-y site name cannot escape the output dir
    assert output.site_output_dir(settings, "../x") == tmp_path / "x"


def test_write_export_creates_the_site_subfolder_and_records_metadata(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    artifact = output.write_export(
        b"PK\x03\x04zip",
        settings=settings,
        site="demo",
        name="demo.zip",
        mimetype="application/zip",
        format="zip",
        now=NOW,
    )
    assert artifact.path.parent == tmp_path / "demo"
    assert artifact.path.name == f"{PREFIX}-demo.zip"
    assert artifact.path.read_bytes() == b"PK\x03\x04zip"
    assert artifact.site == "demo"
    assert artifact.page_id is None
    assert artifact.format == "zip"
    assert artifact.bytes == 7
    assert artifact.mimetype == "application/zip"
    assert artifact.created_at > 0


def test_write_export_never_overwrites_colliding_names(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    kwargs = {
        "settings": settings,
        "site": "demo",
        "name": "demo.zip",
        "mimetype": "application/zip",
        "format": "zip",
        "now": NOW,
    }
    first = output.write_export(b"one", **kwargs)  # type: ignore[arg-type]
    second = output.write_export(b"two", **kwargs)  # type: ignore[arg-type]
    third = output.write_export(b"three", **kwargs)  # type: ignore[arg-type]
    assert first.path.name == f"{PREFIX}-demo.zip"
    assert second.path.name == f"{PREFIX}-demo-1.zip"
    assert third.path.name == f"{PREFIX}-demo-2.zip"
    # the earlier artifacts are untouched
    assert first.path.read_bytes() == b"one"
    assert second.path.read_bytes() == b"two"


def test_write_export_keeps_the_page_id_for_page_exports(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    artifact = output.write_export(
        b"# Home",
        settings=settings,
        site="demo",
        name="home.md",
        mimetype="text/markdown",
        format="md",
        page_id="item-1",
        now=NOW,
    )
    assert artifact.page_id == "item-1"
    assert artifact.path.name == f"{PREFIX}-home.md"
