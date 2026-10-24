"""Phase 7 regression: the committed converter module matches the generator (ADR-0002).

The in-process twin of the CI `scripts/gen_tools.py --check` step: regenerating from the
vendored spec plus the override table must reproduce `generated/converters.py` exactly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.regression

ROOT = Path(__file__).resolve().parents[2]
GEN_PATH = ROOT / "scripts" / "gen_tools.py"
OUTPUT_PATH = ROOT / "src" / "haxcms_mcp" / "generated" / "converters.py"


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("gen_tools_regression", GEN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_converters_match_generation() -> None:
    gen_tools = _load_generator()
    assert gen_tools.check(OUTPUT_PATH), (
        "generated/converters.py drifted: run `uv run python scripts/gen_tools.py`, "
        "review the diff and commit"
    )
