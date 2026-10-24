"""Settings for the HAXcms MCP server.

All settings come from environment variables (prefix ``HAXCMS_MCP_``) or a ``.env`` file in the
working directory, via pydantic-settings. See PLAN.md Section 4 for the full table.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Operator configuration for one HAXcms MCP process (one Instance)."""

    model_config = SettingsConfigDict(
        env_prefix="HAXCMS_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Connection -------------------------------------------------------
    base_url: str = Field(description="Instance root, e.g. http://localhost:3000")
    username: str | None = None
    password: str | None = None
    default_site: str | None = None
    no_auth: bool = False

    # --- Behaviour ----------------------------------------------------------
    read_only: bool = False
    rate_limit_rps: float = 4.0
    rate_limit_burst: int = 8
    rate_limit_max_wait_s: float = 30.0
    retry_max: int = 3
    timeout_s: float = 60.0
    export_timeout_s: float = 300.0
    catalog_live_ttl_s: int = 600

    # --- File sources and outputs -------------------------------------------
    output_dir: Path = Path("haxcms-mcp-output")
    input_roots: Annotated[list[Path], NoDecode] = Field(default_factory=lambda: [Path.cwd()])
    max_inline_base64_mb: int = 10

    # --- Transport ------------------------------------------------------------
    transport: Literal["stdio", "http"] = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    http_path: str = "/mcp"
    log_level: str = "INFO"

    # --- Test-only -------------------------------------------------------------
    test_haxcms_dir: Path | None = None
    test_haxcms_version: str = "26.8.1"
    test_keep_runtime: bool = False

    @field_validator("base_url")
    @classmethod
    def _normalise_base_url(cls, value: str) -> str:
        """Require an http(s) URL and strip any trailing slash."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("HAXCMS_MCP_BASE_URL must not be empty")
        if not stripped.startswith(("http://", "https://")):
            raise ValueError(
                f"HAXCMS_MCP_BASE_URL must start with http:// or https:// (got {stripped!r})"
            )
        return stripped.rstrip("/")

    @field_validator("input_roots", mode="before")
    @classmethod
    def _split_input_roots(cls, value: Any) -> Any:
        """Accept an os.pathsep-separated string from the environment."""
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(os.pathsep) if p.strip()]
            return parts or [Path.cwd()]
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return list(value)
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.strip().upper()


def load_settings(**overrides: Any) -> Settings:
    """Load settings from environment/.env with optional keyword overrides."""
    return Settings(**overrides)
