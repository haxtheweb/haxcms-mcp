"""HaxcmsClient: the single HTTP pipeline to one HAXcms instance (PLAN §2.2 step 5, T1.5).

Owns one `httpx.AsyncClient` (base_url, timeout, cookie jar). `request()` ensures a valid access
token, ensures the Site/User Token for `bearer+site`/`bearer+user` calls, consumes the
process-wide Outbound Budget, applies the retry policy, and performs one reactive refresh on a
403 "Invalid bearer token". JSON helpers unwrap the `{status, data}` envelope.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx

from haxcms_mcp.client.auth import AuthManager
from haxcms_mcp.client.budget import OutboundBudget
from haxcms_mcp.client.envelope import error_from_response, is_invalid_bearer, unwrap, unwrap_full
from haxcms_mcp.client.principal import current_principal
from haxcms_mcp.client.retry import RetryPolicy, with_retry
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from haxcms_mcp.config import Settings
    from haxcms_mcp.generated.route import Route

logger = get_logger(__name__)

AuthMode = Literal["none", "bearer", "bearer+user", "bearer+site"]

SYSTEM_API_PREFIX = "/system/api/v1"


def _too_large(size: int, limit: int) -> HaxcmsMcpError:
    return HaxcmsMcpError(
        ErrorCode.UNSUPPORTED,
        f"the HAXcms response is {size} bytes, over this server's {limit} byte download cap",
        hint="raise HAXCMS_MCP_DOWNLOAD_MAX_MB, or export a smaller format or a single page",
    )


SITE_API_TEMPLATE = "/_sites/{site}/x/api/v1"

# Per-caller sessions kept at once in authenticated HTTP mode (#3140); least recently used
# sessions are closed first. HAXcms access tokens live 15 minutes, so a caller whose session
# was evicted simply gets a fresh one (new User/Site Token fetch) on their next request.
MAX_CALLER_SESSIONS = 256


@dataclass
class _CallerSession:
    http: httpx.AsyncClient
    auth: AuthManager


class HaxcmsClient:
    """Async HTTP client for the HAXcms system and site APIs."""

    def __init__(
        self,
        settings: Settings,
        *,
        budget: OutboundBudget | None = None,
        policy: RetryPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self._default_http = self._new_http()
        # stdio / single identity: this one bucket. Per-caller HTTP mode: every USER gets a
        # bucket of their own (RATE_LIMIT_RPS/BURST) and all users together are capped by
        # `_total_budget` (RATE_LIMIT_TOTAL_RPS), so one caller cannot starve the others and
        # the instance never sees more than the total (security follow-up).
        self._shared_budget = (
            budget if budget is not None else OutboundBudget.from_settings(settings)
        )
        self._total_budget = OutboundBudget(
            rate=settings.rate_limit_total_rps,
            capacity=max(settings.rate_limit_burst, int(settings.rate_limit_total_rps * 2)),
            max_wait=settings.rate_limit_max_wait_s,
            clock=clock,
        )
        self._user_budgets: OrderedDict[str, OutboundBudget] = OrderedDict()
        self.policy = policy if policy is not None else RetryPolicy.from_settings(settings)
        self._sleep = sleep
        self._default_auth = AuthManager(settings, self, clock=clock)
        self._sessions: OrderedDict[str, _CallerSession] = OrderedDict()
        self._closing: set[asyncio.Task[None]] = set()

    def _new_http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.settings.base_url, timeout=self.settings.timeout_s)

    # --- per-caller routing (#3140) ---------------------------------------------------
    def _caller_session(self) -> _CallerSession | None:
        """The current caller's session in authenticated HTTP mode, else None (process-wide)."""
        if not self.settings.per_caller_auth:
            return None
        principal = current_principal.get()
        if principal is None:
            return None
        key = principal.key
        session = self._sessions.get(key)
        if session is not None:
            self._sessions.move_to_end(key)
            return session
        session = _CallerSession(
            http=self._new_http(),
            auth=AuthManager(self.settings, self, clock=self._clock, principal=principal),
        )
        self._sessions[key] = session
        while len(self._sessions) > MAX_CALLER_SESSIONS:
            _, evicted = self._sessions.popitem(last=False)
            self._close_later(evicted.http)
        return session

    @property
    def budget(self) -> OutboundBudget:
        """The current caller's bucket in per-caller mode, else the process-wide one."""
        if not self.settings.per_caller_auth:
            return self._shared_budget
        principal = current_principal.get()
        if principal is None:
            return self._shared_budget
        user = principal.username or principal.key
        bucket = self._user_budgets.get(user)
        if bucket is None:
            bucket = OutboundBudget.from_settings(self.settings)
            self._user_budgets[user] = bucket
            while len(self._user_budgets) > MAX_CALLER_SESSIONS:
                self._user_budgets.popitem(last=False)
        self._user_budgets.move_to_end(user)
        return bucket

    def _buckets(self) -> list[OutboundBudget]:
        caller = self.budget
        if caller is self._shared_budget:
            return [caller]
        return [caller, self._total_budget]

    def _close_later(self, http: httpx.AsyncClient) -> None:
        try:
            task = asyncio.get_running_loop().create_task(http.aclose())
        except RuntimeError:  # no running loop: nothing in flight can be using it
            return
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    @property
    def http(self) -> httpx.AsyncClient:
        """The httpx client (cookie jar) of the current caller, or the process-wide one."""
        session = self._caller_session()
        return session.http if session is not None else self._default_http

    @property
    def auth(self) -> AuthManager:
        """The token lifecycle of the current caller, or the process-wide one."""
        session = self._caller_session()
        return session.auth if session is not None else self._default_auth

    # --- path helpers -----------------------------------------------------------
    def sys(self, path: str = "") -> str:
        """System API path: `sys("session/login")` -> `/system/api/v1/session/login`."""
        return f"{SYSTEM_API_PREFIX}/{path.lstrip('/')}" if path else SYSTEM_API_PREFIX

    def site_path(self, site: str, path: str = "") -> str:
        """Site API path: `site_path("demo", "items")` -> `/_sites/demo/x/api/v1/items`."""
        base = SITE_API_TEMPLATE.format(site=site)
        return f"{base}/{path.lstrip('/')}" if path else base

    # --- core request pipeline ----------------------------------------------------
    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        data: Any | None = None,
        files: Any | None = None,
        params: Mapping[str, Any] | None = None,
        auth: AuthMode = "bearer",
        site: str | None = None,
        timeout: float | None = None,
        accept: str | None = None,
        headers: Mapping[str, str] | None = None,
        no_retry: bool = False,
        budget: OutboundBudget | None = None,
        max_bytes: int | None = None,
    ) -> httpx.Response:
        """Send one request with auth headers, budget accounting, and retry/refresh handling."""
        request_headers: dict[str, str] = dict(headers or {})
        if accept is not None:
            request_headers["Accept"] = accept

        token: str | None = None
        if auth != "none":
            token = await self.auth.ensure_access()
            if auth == "bearer+user":
                user_token = await self.auth.user_token()
                if user_token is not None:
                    request_headers["X-HAXCMS-User-Token"] = user_token
            elif auth == "bearer+site":
                if site is None:
                    raise HaxcmsMcpError(
                        ErrorCode.INVALID_ARGUMENT,
                        "site is required for site-token authenticated calls",
                    )
                site_token = await self.auth.site_token(site)
                if site_token is not None:
                    request_headers["X-HAXCMS-Site-Token"] = site_token
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"

        policy = RetryPolicy(retry_max=0) if no_retry else self.policy
        kwargs: dict[str, Any] = {
            "json": json,
            "data": data,
            "files": files,
            "params": params,
        }
        if timeout is not None:
            # passing timeout=None to build_request would DISABLE the client-level timeout
            kwargs["timeout"] = timeout
        response = await self._send(
            method, path, request_headers, policy, kwargs, budget, max_bytes
        )

        # One reactive refresh on 403 "Invalid bearer token" (API-REF §2.2, PLAN §2.2 step 5).
        if auth != "none" and not self.settings.no_auth and is_invalid_bearer(response):
            logger.info("bearer token refused; refreshing once and retrying %s %s", method, path)
            self.auth.invalidate()
            token = await self.auth.ensure_access(force=True)
            if token is not None:
                request_headers["Authorization"] = f"Bearer {token}"
            else:
                request_headers.pop("Authorization", None)
            response = await self._send(
                method, path, request_headers, policy, kwargs, budget, max_bytes
            )
        return response

    async def _send(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        policy: RetryPolicy,
        kwargs: dict[str, Any],
        budget: OutboundBudget | None = None,
        max_bytes: int | None = None,
    ) -> httpx.Response:
        request = self.http.build_request(method, path, headers=headers, **kwargs)
        send = self.http.send if max_bytes is None else self._capped_sender(max_bytes)
        # `budget` lets a caller draw from a separate bucket (token verification must not
        # be able to starve tool traffic, and vice versa)
        buckets = [budget] if budget is not None else self._buckets()

        async def acquire() -> None:
            for bucket in buckets:
                await bucket.acquire()

        await acquire()
        started = time.monotonic()
        response = await with_retry(send, request, policy, sleep=self._sleep, on_retry=acquire)
        # PLAN §5: every outbound request at DEBUG as `METHOD path status ms` — raw_path so
        # %2F-encoded slugs log as sent, and never headers (they carry the bearer tokens).
        elapsed_ms = (time.monotonic() - started) * 1000
        logger.debug(
            "%s %s %s %.0fms",
            method,
            request.url.raw_path.decode("ascii", errors="replace"),
            response.status_code,
            elapsed_ms,
        )
        return response

    def _capped_sender(
        self, max_bytes: int
    ) -> Callable[[httpx.Request], Awaitable[httpx.Response]]:
        """A `send` that streams the body and stops once it exceeds `max_bytes`, so a huge
        export or zip never has to fit in memory just to be refused (security follow-up)."""

        async def send(request: httpx.Request) -> httpx.Response:
            response = await self.http.send(request, stream=True)
            try:
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    raise _too_large(int(declared), max_bytes)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():  # decoded: caps gzip bombs too
                    size += len(chunk)
                    if size > max_bytes:
                        raise _too_large(size, max_bytes)
                    chunks.append(chunk)
            finally:
                await response.aclose()
            # the body is already decoded, so drop the transfer headers that described it
            headers = [
                (key, value)
                for key, value in response.headers.multi_items()
                if key.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
            ]
            return httpx.Response(
                response.status_code,
                headers=headers,
                content=b"".join(chunks),
                request=request,
                extensions={"http_version": response.extensions.get("http_version", b"")},
            )

        return send

    async def call(
        self, route: Route, *, auth: AuthMode | None = None, **kwargs: Any
    ) -> httpx.Response:
        """`request()` for a generated spec route (ADR-0005): method and path from the spec,
        auth defaulting to what the spec requires. Pass `auth` to send MORE than the spec
        requires (an open route that answers differently for a known user)."""
        return await self.request(route.method, route.path, auth=auth or route.auth, **kwargs)

    # --- JSON convenience wrappers --------------------------------------------------
    async def get_json(self, path: str, **kwargs: Any) -> Any:
        return unwrap(await self.request("GET", path, **kwargs))

    async def post_json(self, path: str, **kwargs: Any) -> Any:
        return unwrap(await self.request("POST", path, **kwargs))

    async def patch_json(self, path: str, **kwargs: Any) -> Any:
        return unwrap(await self.request("PATCH", path, **kwargs))

    async def delete_json(self, path: str, **kwargs: Any) -> Any:
        return unwrap(await self.request("DELETE", path, **kwargs))

    async def get_json_full(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return unwrap_full(await self.request("GET", path, **kwargs))

    async def post_json_full(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return unwrap_full(await self.request("POST", path, **kwargs))

    async def download(self, path: str, **kwargs: Any) -> bytes:
        """GET a binary artifact (published zips, files, exports), streamed under the
        DOWNLOAD_MAX_MB cap."""
        kwargs.setdefault("max_bytes", self.settings.download_max_mb * 1024 * 1024)
        response = await self.request("GET", path, **kwargs)
        if response.status_code >= 400:
            raise error_from_response(response)
        return response.content

    # --- lifecycle -------------------------------------------------------------------
    async def aclose(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            await session.http.aclose()
        await self._default_http.aclose()

    async def __aenter__(self) -> HaxcmsClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
