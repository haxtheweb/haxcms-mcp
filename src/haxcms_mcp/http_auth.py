"""Per-caller authentication for the streamable-HTTP transport (#3140, docs/adr/0004).

The MCP server is an OAuth 2.1 *resource server*. The authorization server is HAXcms itself
(ADR-0004, option A): it issues the access tokens, and those tokens are ordinary HAXcms access
tokens, so a caller acts with exactly their own HAXcms permissions.

* `HaxcmsTokenVerifier` checks a presented bearer by asking HAXcms (`GET session` with that
  bearer). Valid answers are cached briefly, keyed by a hash of the token.
* `build_auth_provider` wraps it in FastMCP's `RemoteAuthProvider`, which rejects requests
  without a valid token (401 + `WWW-Authenticate`) and serves the RFC 9728 protected-resource
  metadata that points MCP clients at the HAXcms authorization server.
* `PrincipalMiddleware` exposes the verified caller to `HaxcmsClient` for one MCP request.
"""

from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING, Any

from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext
from pydantic import AnyHttpUrl

from haxcms_mcp.client.principal import Principal, current_principal
from haxcms_mcp.logging import get_logger

if TYPE_CHECKING:
    from fastmcp.server.middleware import CallNext

    from haxcms_mcp.client import HaxcmsClient
    from haxcms_mcp.config import Settings

logger = get_logger(__name__)

VERIFY_CACHE_TTL_S = 30.0
VERIFY_CACHE_MAX = 1024
VERIFY_TIMEOUT_S = 10.0


def _unverified_exp(token: str) -> int | None:
    """Read `exp` from a JWT payload WITHOUT trusting it (HAXcms already validated the token;
    this only bounds how long FastMCP treats it as live)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    exp = payload.get("exp") if isinstance(payload, dict) else None
    return int(exp) if isinstance(exp, int | float) else None


class HaxcmsTokenVerifier(TokenVerifier):
    """Valid means: the HAXcms instance accepts this bearer and names a user."""

    def __init__(
        self,
        client: HaxcmsClient,
        *,
        clock: Any = time.monotonic,
        required_scopes: list[str] | None = None,
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self._client = client
        self._clock = clock
        self._cache: dict[str, tuple[float, AccessToken]] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        key = Principal(token).key
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < VERIFY_CACHE_TTL_S:
            return cached[1]
        try:
            response = await self._client.request(
                "GET",
                self._client.sys("session"),
                auth="none",
                headers={"Authorization": f"Bearer {token}"},
                timeout=VERIFY_TIMEOUT_S,
                no_retry=True,
            )
        except Exception as exc:  # noqa: BLE001 - an unreachable HAXcms means "not verified"
            logger.warning("token verification failed: %s", type(exc).__name__)
            return None
        if response.status_code != 200:
            self._cache.pop(key, None)
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict) or body.get("authenticated") is not True:
            return None
        user = body.get("user")
        if not isinstance(user, str) or not user:
            return None
        access = AccessToken(
            token=token,
            client_id=user,
            scopes=list(self.required_scopes or []),
            expires_at=_unverified_exp(token),
            claims={"user": user},
        )
        if len(self._cache) >= VERIFY_CACHE_MAX:
            self._cache.clear()
        self._cache[key] = (now, access)
        return access


def build_auth_provider(settings: Settings, client: HaxcmsClient) -> RemoteAuthProvider:
    """The FastMCP auth provider for `HAXCMS_MCP_HTTP_AUTH=haxcms`."""
    public = settings.public_url or f"http://{settings.http_host}:{settings.http_port}"
    authorization_server = settings.authorization_server_url or settings.base_url
    return RemoteAuthProvider(
        token_verifier=HaxcmsTokenVerifier(client),
        authorization_servers=[AnyHttpUrl(authorization_server)],
        base_url=public.rstrip("/"),
        resource_name="HAXcms MCP",
    )


class PrincipalMiddleware(Middleware):
    """Bind the verified caller to `current_principal` for the rest of the MCP request."""

    async def on_request(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        access = get_access_token()
        if access is None:
            return await call_next(context)
        user = access.claims.get("user") if access.claims else None
        token = current_principal.set(
            Principal(access.token, user if isinstance(user, str) else access.client_id)
        )
        try:
            return await call_next(context)
        finally:
            current_principal.reset(token)
