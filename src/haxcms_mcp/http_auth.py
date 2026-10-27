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
* `AuthFailureLimiter` (ASGI) answers 429 to a client address that keeps presenting tokens
  HAXcms refuses, so made-up bearers cannot flood the instance with verification calls.

Verification draws from its own outbound bucket (security audit): unauthenticated traffic can
never drain the budget that verified callers' tool calls use, and vice versa.
"""

from __future__ import annotations

import base64
import json
import time
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Any

from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext
from pydantic import AnyHttpUrl

from haxcms_mcp.client.budget import OutboundBudget
from haxcms_mcp.client.principal import Principal, current_principal
from haxcms_mcp.logging import get_logger

if TYPE_CHECKING:
    from fastmcp.server.middleware import CallNext
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from haxcms_mcp.client import HaxcmsClient
    from haxcms_mcp.config import Settings

logger = get_logger(__name__)

VERIFY_CACHE_TTL_S = 30.0
VERIFY_FAILURE_TTL_S = 10.0  # a refused token is not re-asked about for this long
VERIFY_CACHE_MAX = 1024
VERIFY_TIMEOUT_S = 10.0
# separate bucket for verification calls (see module docstring)
VERIFY_RATE_RPS = 10.0
VERIFY_BURST = 20
VERIFY_MAX_WAIT_S = 2.0


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
        # key -> (verified_at, token or None for a refusal); LRU-bounded
        self._cache: OrderedDict[str, tuple[float, AccessToken | None]] = OrderedDict()
        self._budget = OutboundBudget(
            rate=VERIFY_RATE_RPS, capacity=VERIFY_BURST, max_wait=VERIFY_MAX_WAIT_S, clock=clock
        )

    def _remember(self, key: str, now: float, access: AccessToken | None) -> None:
        self._cache[key] = (now, access)
        self._cache.move_to_end(key)
        while len(self._cache) > VERIFY_CACHE_MAX:
            self._cache.popitem(last=False)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        key = Principal(token).key
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None:
            ttl = VERIFY_CACHE_TTL_S if cached[1] is not None else VERIFY_FAILURE_TTL_S
            if now - cached[0] < ttl:
                return cached[1]
        try:
            response = await self._client.request(
                "GET",
                self._client.sys("session"),
                auth="none",
                headers={"Authorization": f"Bearer {token}"},
                timeout=VERIFY_TIMEOUT_S,
                no_retry=True,
                budget=self._budget,
            )
        except Exception as exc:  # noqa: BLE001 - an unreachable HAXcms means "not verified"
            # not cached: an outage or a full verification bucket is not a verdict on the token
            logger.warning("token verification unavailable: %s", type(exc).__name__)
            return None
        access = self._access_from(token, response)
        if access is None and response.status_code in (200, 401, 403):
            self._remember(key, now, None)  # HAXcms answered: this token is not valid
        elif access is not None:
            self._remember(key, now, access)
        return access

    def _access_from(self, token: str, response: Any) -> AccessToken | None:
        if response.status_code != 200:
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
        return AccessToken(
            token=token,
            client_id=user,
            scopes=list(self.required_scopes or []),
            expires_at=_unverified_exp(token),
            claims={"user": user},
        )


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


class AuthFailureLimiter:
    """ASGI middleware: after `limit` 401 answers to one client address within `window_s`,
    answer 429 (with Retry-After) without touching the auth layer or HAXcms.

    The address is the TCP peer. Behind a reverse proxy every caller shares the proxy's
    address, so rate-limit failed auth at the proxy instead and set the limit to 0 here.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        window_s: float = 60.0,
        clock: Any = time.monotonic,
        max_clients: int = 4096,
    ) -> None:
        self.app = app
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._max_clients = max_clients
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    def _recent(self, client: str, now: float) -> deque[float]:
        hits = self._failures.get(client)
        if hits is None:
            hits = deque()
            self._failures[client] = hits
            while len(self._failures) > self._max_clients:
                self._failures.popitem(last=False)
        self._failures.move_to_end(client)
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        return hits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.limit <= 0:
            await self.app(scope, receive, send)
            return
        peer = scope.get("client")
        client = str(peer[0]) if peer else "unknown"
        now = self._clock()
        hits = self._recent(client, now)
        if len(hits) >= self.limit:
            retry = max(1, int(self.window_s - (now - hits[0])) + 1)
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(retry).encode()),
                    ],
                }
            )
            body = b'{"error":"too_many_failed_auth","error_description":"slow down"}'
            await send({"type": "http.response.body", "body": body})
            return

        async def tracking_send(message: Message) -> None:
            if message["type"] == "http.response.start" and message.get("status") == 401:
                self._recent(client, self._clock()).append(self._clock())
            await send(message)

        await self.app(scope, receive, tracking_send)


def transport_middleware(settings: Settings) -> list[Any]:
    """Starlette middleware for the HTTP transport (empty unless per-caller auth is on)."""
    if not settings.per_caller_auth or settings.auth_failures_per_minute <= 0:
        return []
    from starlette.middleware import Middleware as StarletteMiddleware

    return [StarletteMiddleware(AuthFailureLimiter, limit=settings.auth_failures_per_minute)]
