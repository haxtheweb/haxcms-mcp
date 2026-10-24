"""Plain-JSON snapshot helpers for the regression suite (PLAN §6.4).

Snapshots live as deterministic JSON files under tests/regression/snapshots/ and are updated
deliberately with `pytest --snapshot-update`. (syrupy is installed but the plan pins the
tool-schema snapshot to a single plain file, so we use plain JSON everywhere for consistency.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "regression" / "snapshots"


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


async def collect_tool_schemas(server: FastMCP) -> dict[str, Any]:
    """Serialise every registered tool: name, description, parameters, annotations."""
    tools = await server.list_tools()
    snapshot: dict[str, Any] = {}
    for tool in sorted(tools, key=lambda t: t.name):
        annotations = (
            tool.annotations.model_dump(mode="json", exclude_none=True)
            if tool.annotations is not None
            else None
        )
        snapshot[tool.name] = {
            "description": tool.description,
            "parameters": tool.parameters,
            "annotations": annotations,
        }
    return snapshot


def assert_or_update_snapshot(name: str, data: Any, *, update: bool) -> None:
    """Compare data against snapshots/<name>.json, or rewrite it when update is set."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{name}.json"
    rendered = canonical_json(data)
    if update or not path.exists():
        path.write_text(rendered, encoding="utf-8")
        if not update:
            # First run created the snapshot; surface that loudly in the report.
            print(f"[snapshots] created {path} (review and commit deliberately)")
        return
    expected = path.read_text(encoding="utf-8")
    if expected != rendered:
        import difflib

        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(), rendered.splitlines(), fromfile=str(path), tofile="actual"
            )
        )
        raise AssertionError(
            f"Snapshot {name} differs (update deliberately with --snapshot-update):\n{diff}"
        )
