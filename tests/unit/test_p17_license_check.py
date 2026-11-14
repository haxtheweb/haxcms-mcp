"""Unit tests for scripts/check_licenses.py, the dependency license gate CI runs.

The script is not a package module, so it is loaded from its path (the same pattern as
test_p09_docs_current.py).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "check_licenses.py"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("check_licenses_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_licenses = _load_script()

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "license_string",
    [
        "MIT",
        "Apache-2.0",
        "Apache-2.0 OR BSD-3-Clause",
        "BSD-3-Clause AND MIT",
        "Apache Software License",
        "The Unlicense (Unlicense)",
        "ISC License (ISCL)",
    ],
)
def test_permissive_licenses_pass(license_string: str) -> None:
    assert check_licenses.is_permissive(license_string) is True


@pytest.mark.parametrize(
    "license_string",
    [
        "",
        "LGPL-3.0-only",
        "Mozilla Public License 2.0 (MPL 2.0)",
        "GPL-3.0-or-later",
        "MIT AND GPL-2.0-only",
        "Apache-2.0 OR LGPL-3.0-only",
        "Proprietary",
    ],
)
def test_everything_else_needs_a_review(license_string: str) -> None:
    assert check_licenses.is_permissive(license_string) is False


def test_the_project_declares_apache_2() -> None:
    assert check_licenses.project_problems() == []
