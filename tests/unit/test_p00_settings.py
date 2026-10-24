"""Unit tests for haxcms_mcp.config.Settings (Phase 0, PLAN Section 4)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from haxcms_mcp.config import Settings

pytestmark = pytest.mark.unit

BASE = {"HAXCMS_MCP_BASE_URL": "http://localhost:3000"}


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any real HAXCMS_MCP_* variables so tests are hermetic."""
    for key in list(os.environ):
        if key.startswith("HAXCMS_MCP_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    for key, value in BASE.items():
        monkeypatch.setenv(key, value)
    settings = Settings()
    assert settings.base_url == "http://localhost:3000"
    assert settings.username is None
    assert settings.password is None
    assert settings.default_site is None
    assert settings.no_auth is False
    assert settings.read_only is False
    assert settings.rate_limit_rps == 4
    assert settings.rate_limit_burst == 8
    assert settings.rate_limit_max_wait_s == 30
    assert settings.retry_max == 3
    assert settings.timeout_s == 60
    assert settings.export_timeout_s == 300
    assert settings.output_dir == Path("haxcms-mcp-output")
    assert settings.input_roots == [Path.cwd()]
    assert settings.max_inline_base64_mb == 10
    assert settings.transport == "stdio"
    assert (settings.http_host, settings.http_port, settings.http_path) == (
        "127.0.0.1",
        8765,
        "/mcp",
    )
    assert settings.log_level == "INFO"
    assert settings.catalog_live_ttl_s == 600
    assert settings.test_haxcms_dir is None
    assert settings.test_haxcms_version == "26.8.1"
    assert settings.test_keep_runtime is False


def test_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAXCMS_MCP_BASE_URL", "https://cms.example.com")
    monkeypatch.setenv("HAXCMS_MCP_USERNAME", "author")
    monkeypatch.setenv("HAXCMS_MCP_PASSWORD", "s3cret")
    monkeypatch.setenv("HAXCMS_MCP_DEFAULT_SITE", "my-course")
    monkeypatch.setenv("HAXCMS_MCP_NO_AUTH", "true")
    monkeypatch.setenv("HAXCMS_MCP_READ_ONLY", "1")
    monkeypatch.setenv("HAXCMS_MCP_RATE_LIMIT_RPS", "2.5")
    monkeypatch.setenv("HAXCMS_MCP_RATE_LIMIT_BURST", "3")
    monkeypatch.setenv("HAXCMS_MCP_RETRY_MAX", "5")
    monkeypatch.setenv("HAXCMS_MCP_TIMEOUT_S", "15")
    monkeypatch.setenv("HAXCMS_MCP_TRANSPORT", "http")
    monkeypatch.setenv("HAXCMS_MCP_HTTP_PORT", "9000")
    monkeypatch.setenv("HAXCMS_MCP_LOG_LEVEL", "debug")
    settings = Settings()
    assert settings.base_url == "https://cms.example.com"
    assert settings.username == "author"
    assert settings.password == "s3cret"
    assert settings.default_site == "my-course"
    assert settings.no_auth is True
    assert settings.read_only is True
    assert settings.rate_limit_rps == 2.5
    assert settings.rate_limit_burst == 3
    assert settings.retry_max == 5
    assert settings.timeout_s == 15
    assert settings.transport == "http"
    assert settings.http_port == 9000
    assert settings.log_level == "DEBUG"


def test_base_url_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAXCMS_MCP_BASE_URL", "http://localhost:3000///")
    assert Settings().base_url == "http://localhost:3000"
    monkeypatch.setenv("HAXCMS_MCP_BASE_URL", "  https://x.example.org/  ")
    assert Settings().base_url == "https://x.example.org"


def test_base_url_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAXCMS_MCP_BASE_URL", "localhost:3000")
    with pytest.raises(ValidationError, match="http://"):
        Settings()
    monkeypatch.setenv("HAXCMS_MCP_BASE_URL", "   ")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.delenv("HAXCMS_MCP_BASE_URL")
    with pytest.raises(ValidationError):
        Settings()  # base_url is required


def test_input_roots_split(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAXCMS_MCP_BASE_URL", "http://h:1")
    first = Path(os.path.abspath("in1"))
    second = Path(os.path.abspath("in2"))
    monkeypatch.setenv(
        "HAXCMS_MCP_INPUT_ROOTS",
        os.pathsep.join([str(first), str(second)]),
    )
    settings = Settings()
    assert settings.input_roots == [first, second]


def test_input_roots_empty_falls_back_to_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("HAXCMS_MCP_BASE_URL", "http://h:1")
    monkeypatch.setenv("HAXCMS_MCP_INPUT_ROOTS", os.pathsep)
    assert Settings().input_roots == [Path.cwd()]
