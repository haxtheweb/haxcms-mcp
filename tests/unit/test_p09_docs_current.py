"""Unit tests for T9.2: docs/tools.md must match a fresh generation from the registry.

scripts/gen_tool_docs.py is not a package module, so it is loaded from its path (the
same pattern as test_p07_gen_tools.py). These tests are the in-process twin of the CI
`--check` step; they are synchronous so the generator's asyncio.run() has no live loop.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
GEN_PATH = ROOT / "scripts" / "gen_tool_docs.py"
DOCS_PATH = ROOT / "docs" / "tools.md"


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("gen_tool_docs_under_test", GEN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen_tool_docs = _load_generator()
DOCS_TEXT: str = gen_tool_docs.build_docs_text()
TOOLS: list[Any] = gen_tool_docs.collect_tools()

pytestmark = pytest.mark.unit


def test_committed_docs_are_current() -> None:
    assert DOCS_PATH.exists(), "docs/tools.md missing - run scripts/gen_tool_docs.py"
    assert DOCS_PATH.read_text(encoding="utf-8") == DOCS_TEXT


def test_generation_is_deterministic() -> None:
    assert gen_tool_docs.build_docs_text() == DOCS_TEXT


def test_docs_cover_every_registered_tool() -> None:
    assert len(TOOLS) >= 100
    for tool in TOOLS:
        assert f"## `{tool.name}`" in DOCS_TEXT
        assert f"[`{tool.name}`](#{tool.name.lower()})" in DOCS_TEXT
    assert f"{len(TOOLS)} tools" in DOCS_TEXT


def test_every_section_carries_annotations_and_parameters() -> None:
    # each tool section shows the four hints (the index table spells them capitalized)
    assert DOCS_TEXT.count("read-only: ") == len(TOOLS)
    for tool in TOOLS:
        parameters = tool.parameters or {}
        properties = parameters.get("properties") or {}
        for name in properties:
            assert f"| `{name}` |" in DOCS_TEXT


def test_first_paragraph_extraction() -> None:
    extract = gen_tool_docs.first_paragraph
    assert extract("One line.\n\nSecond paragraph.") == "One line."
    assert extract("Wrapped\nlines here.\n\nArgs:\n    x: 1") == "Wrapped lines here."
    assert extract("Summary.\nReturns:\n    dict") == "Summary."
    assert extract("Solo.\n\nReturns:\n    dict") == "Solo."
    assert extract(None) == ""
    assert extract("   ") == ""


def test_schema_type_rendering() -> None:
    render = gen_tool_docs.schema_type
    assert render({"type": "string"}) == "string"
    assert render({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "string | null"
    assert render({"type": "array", "items": {"type": "object"}}) == "array[object]"
    assert render({"enum": ["a", "b"]}) == '"a" | "b"'
    assert render({}) == "any"
