"""Settings for the HAXcms MCP server.

All settings come from environment variables (prefix ``HAXCMS_MCP_``) or a ``.env`` file in the
working directory, via pydantic-settings. See PLAN.md Section 4 for the full table.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
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
    # Folders local-path sources may come from. Empty (the default) turns local-path sources
    # off: the working directory is often $HOME or / and holds this server's own .env
    # (security audit). Dotfiles and key files are refused even inside a root.
    input_roots: Annotated[list[Path], NoDecode] = Field(default_factory=list)
    max_inline_base64_mb: int = 10

    # --- Transport ------------------------------------------------------------
    transport: Literal["stdio", "http"] = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    http_path: str = "/mcp"
    log_level: str = "INFO"

    # --- HTTP transport security (#3140, docs/adr/0004) -------------------------
    # "none": one process-wide HAXcms identity (env credentials / login tool), loopback only.
    # "haxcms": every MCP request must carry `Authorization: Bearer <HAXcms access token>`;
    # each caller acts as their own HAXcms user and env credentials are never used.
    http_auth: Literal["none", "haxcms"] = "none"
    # Public URL of this MCP endpoint's origin (OAuth protected-resource metadata, RFC 9728).
    public_url: str | None = None
    # Authorization server advertised to clients; defaults to the HAXcms instance (option A).
    authorization_server_url: str | None = None
    # None = decided by transport: private/loopback URL sources and local-path sources are
    # allowed over stdio and refused over HTTP.
    allow_private_url_sources: bool | None = None
    allow_local_sources: bool | None = None
    # DNS-rebinding protection (security audit): the HTTP transport only answers requests whose
    # Host is loopback, the bind address, the PUBLIC_URL host, or one of these; a browser
    # Origin must be loopback, same-origin, or one of HTTP_ALLOWED_ORIGINS. Comma-separated.
    http_allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    http_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Per client address: after this many refused bearer tokens in a minute, answer 429
    # without asking HAXcms (0 disables; use the reverse proxy's limit when behind one).
    auth_failures_per_minute: int = 20
    # Per-caller mode: results expire, are capped per user, and are fetched via signed links.
    output_ttl_s: int = 3600
    output_caller_quota_mb: int = 200
    download_ttl_s: int = 900

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
            return [p.strip() for p in value.split(os.pathsep) if p.strip()]
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return list(value)
        return value

    @field_validator("http_allowed_hosts", "http_allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def _fail_closed_http(self) -> Settings:
        """Never serve HTTP beyond loopback without per-caller auth (#3140)."""
        if self.transport != "http" or self.http_auth != "none":
            return self
        if not is_loopback_host(self.http_host):
            raise ValueError(
                f"refusing to serve the HTTP transport on {self.http_host!r} without "
                "authentication: set HAXCMS_MCP_HTTP_AUTH=haxcms (each caller then acts as "
                "their own HAXcms user), or bind to 127.0.0.1"
            )
        return self

    @model_validator(mode="after")
    def _require_tls_when_exposed(self) -> Settings:
        """Bearer tokens from other hosts must not travel in clear text (security audit)."""
        if not self.per_caller_auth or is_loopback_host(self.http_host):
            return self
        if not (self.public_url or "").lower().startswith("https://"):
            raise ValueError(
                "HAXCMS_MCP_HTTP_AUTH=haxcms on a non-loopback bind needs "
                "HAXCMS_MCP_PUBLIC_URL=https://... (terminate TLS in front of this server): "
                "callers send their HAXcms access token on every request"
            )
        return self

    # --- derived -------------------------------------------------------------------
    @property
    def per_caller_auth(self) -> bool:
        """True when each MCP caller brings their own HAXcms token (HTTP + http_auth)."""
        return self.transport == "http" and self.http_auth != "none"

    @property
    def transport_guard(self) -> dict[str, Any]:
        """Host/Origin validation kwargs for FastMCP's HTTP transport (DNS rebinding)."""
        hosts = list(self.http_allowed_hosts)
        origins = list(self.http_allowed_origins)
        if self.public_url:
            public = urlsplit(self.public_url)
            if public.hostname:
                hosts.append(public.netloc)
                hosts.append(public.hostname)
                origins.append(f"{public.scheme}://{public.netloc}")
        return {
            "host_origin_protection": True,
            "allowed_hosts": hosts,
            "allowed_origins": origins,
        }

    @property
    def ssrf_guard_enabled(self) -> bool:
        if self.allow_private_url_sources is not None:
            return not self.allow_private_url_sources
        return self.transport == "http"

    @property
    def local_sources_enabled(self) -> bool:
        if self.allow_local_sources is not None:
            return self.allow_local_sources
        return self.transport != "http"


def is_loopback_host(host: str) -> bool:
    """`localhost` or a loopback IP literal (`0.0.0.0` / `::` bind everything: not loopback)."""
    value = host.strip().strip("[]").lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def load_settings(**overrides: Any) -> Settings:
    """Load settings from environment/.env with optional keyword overrides."""
    return Settings(**overrides)
