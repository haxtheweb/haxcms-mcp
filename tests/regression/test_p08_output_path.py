"""Phase 8 regression snapshot: the Output Directory path golden (PLAN §2.3/§6.4).

Freezes the artifact naming contract — `HAXCMS_MCP_OUTPUT_DIR/<site>/<timestamp>-<name>.<ext>`
— and the ExportArtifact dump shape the tools return (path/bytes/mimetype, never the bytes).
Machine-specific parts (the output root, the wall clock) are normalized away.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services.exports import output
from tests.harness.snapshots import assert_or_update_snapshot

pytestmark = pytest.mark.regression

NOW = datetime(2026, 10, 1, 15, 4, 5)


def test_export_output_path_golden(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    settings = Settings(base_url="http://snapshot.invalid", output_dir=tmp_path)
    artifact = output.write_export(
        b"PK\x03\x04zip",
        settings=settings,
        site="demo",
        name="demo.zip",
        mimetype="application/zip",
        format="zip",
        now=NOW,
    )
    dumped = dump_model(artifact)
    dumped["path"] = Path(str(dumped["path"])).relative_to(tmp_path).as_posix()
    dumped["created_at"] = 1767225600.0
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("export_output_path", dumped, update=update)
