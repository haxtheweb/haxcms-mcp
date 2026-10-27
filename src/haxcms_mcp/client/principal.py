"""Per-caller HAXcms identity for the authenticated HTTP transport (#3140, ADR-0004).

With `HAXCMS_MCP_HTTP_AUTH=haxcms`, every MCP request carries the caller's own HAXcms access
token. `PrincipalMiddleware` copies the verified token into `current_principal` for the
duration of one MCP request, and `HaxcmsClient` routes `client.http` / `client.auth` to a
session that belongs to that token: its own cookie jar, its own User and Site Token cache, and
never the process's environment credentials.
"""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from dataclasses import dataclass

current_principal: ContextVar[Principal | None] = ContextVar("haxcms_principal", default=None)


@dataclass(frozen=True)
class Principal:
    """A verified caller: the HAXcms access token they presented and the user it names."""

    token: str
    username: str | None = None

    @property
    def key(self) -> str:
        """Stable, non-reversible key for per-caller caches (never log the token itself)."""
        return hashlib.sha256(self.token.encode("utf-8")).hexdigest()


def caller_scope() -> str:
    """Key prefix for per-caller state shared in one process (caches, locks): the caller's
    token hash in authenticated HTTP mode, "" otherwise (one identity per process)."""
    principal = current_principal.get()
    return principal.key if principal is not None else ""
