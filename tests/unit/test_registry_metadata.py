"""server.json (the MCP registry entry) stays in step with the package it describes."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
PROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_versions_match_the_package() -> None:
    assert SERVER["version"] == PROJECT["version"]
    assert [p["version"] for p in SERVER["packages"]] == [PROJECT["version"]]


def test_package_is_the_one_this_repo_builds() -> None:
    (package,) = SERVER["packages"]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == PROJECT["name"]
    assert package["transport"] == {"type": "stdio"}


def test_readme_carries_the_ownership_line() -> None:
    # the registry looks for this exact text in the README PyPI serves
    readme = (REPO_ROOT / PROJECT["readme"]).read_text(encoding="utf-8")
    assert f"mcp-name: {SERVER['name']}" in readme


def test_description_fits_the_registry_limit() -> None:
    assert 1 <= len(SERVER["description"]) <= 100


def test_environment_variables_are_real_settings() -> None:
    from haxcms_mcp.config import Settings

    fields = {name.upper() for name in Settings.model_fields}
    (package,) = SERVER["packages"]
    for variable in package["environmentVariables"]:
        assert variable["name"].startswith("HAXCMS_MCP_")
        assert variable["name"].removeprefix("HAXCMS_MCP_") in fields
    secrets = {v["name"] for v in package["environmentVariables"] if v["isSecret"]}
    assert secrets == {"HAXCMS_MCP_PASSWORD"}
