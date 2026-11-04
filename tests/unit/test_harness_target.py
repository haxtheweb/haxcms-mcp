"""The live-test harness never picks a HAXcms on its own: the target is always explicit."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.harness import haxcms_runtime as harness

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def no_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAXCMS_MCP_TEST_HAXCMS_DIR", raising=False)
    monkeypatch.delenv("HAXCMS_MCP_TEST_HAXCMS_VERSION", raising=False)
    monkeypatch.delenv("HAXCMS_MCP_TEST_BACKEND", raising=False)


def test_without_a_target_the_harness_refuses_instead_of_installing_npm(no_target: None) -> None:
    assert harness.has_haxcms_target() is False
    assert "will not run" in harness.describe_haxcms_target()
    with pytest.raises(RuntimeError, match="HAXCMS_MCP_TEST_HAXCMS_DIR"):
        harness.ensure_haxcms()


def test_a_checkout_target_is_described_with_its_branch_and_commit(
    no_target: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAXCMS_MCP_TEST_HAXCMS_DIR", str(REPO_ROOT))  # any git checkout will do
    assert harness.has_haxcms_target() is True
    line = harness.describe_haxcms_target()
    assert line.startswith(f"HAXcms NodeJS checkout {REPO_ROOT} (")
    assert "@" in line and "?" not in line


def test_an_npm_release_is_only_used_when_named(
    no_target: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAXCMS_MCP_TEST_HAXCMS_VERSION", "26.8.1")
    assert harness.has_haxcms_target() is True
    assert "@haxtheweb/haxcms-nodejs@26.8.1" in harness.describe_haxcms_target()
    assert "not main" in harness.describe_haxcms_target()


def _pytest(env_extra: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """`pytest --collect-only` in a child process, with no HAXcms target unless given."""

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"HAXCMS_MCP_TEST_HAXCMS_DIR", "HAXCMS_MCP_TEST_HAXCMS_VERSION"}
    }
    env.pop("HAXCMS_MCP_TEST_BACKEND", None)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_collecting_live_suites_without_a_target_stops_once_with_instructions() -> None:
    result = _pytest({}, "-m", "integration", "tests/integration/test_p15_instance_policy_live.py")
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert "explicit HAXcms target" in result.stderr


def test_unit_only_runs_need_no_target() -> None:
    result = _pytest({}, "-m", "unit", "tests/unit/test_p15_instance_policy.py")
    assert result.returncode == pytest.ExitCode.OK, result.stdout + result.stderr
    assert "haxcms target: no HAXcms NodeJS target set" in result.stdout
