"""HaxcmsClient: the single HTTP pipeline to one HAXcms instance (PLAN §2.2 step 5, T1.5).

Owns one `httpx.AsyncClient` (base_url, timeout, cookie jar). `request()` ensures a valid access
token, ensures the Site/User Token for `bearer+site`/`bearer+user` calls, consumes the
process-wide Outbound Budget, applies the retry policy, and performs one reactive refresh on a
403 "Invalid bearer token". JSON helpers unwrap the `{status, data}` envelope.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Literal

import httpx

from haxcms_mcp.client.auth import AuthManager
from haxcms_mcp.client.budget import OutboundBudget
from haxcms_mcp.client.envelope import error_from_response, is_invalid_bearer, unwrap, unwrap_full
from haxcms_mcp.client.retry import RetryPolicy, with_retry
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from haxcms_mcp.config import Settings

logger = get_logger(__name__)

AuthMode = Literal["none", "bearer", "bearer+user", "bearer+site"]

SYSTEM_API_PREFIX = "/system/api/v1"
SITE_API_TEMPLATE = "/_sites/{site}/x/api/v1"


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
        self.http = httpx.AsyncClient(base_url=settings.base_url, timeout=settings.timeout_s)
        self.budget = budget if budget is not None else OutboundBudget.from_settings(settings)
        self.policy = policy if policy is not None else RetryPolicy.from_settings(settings)
        self._sleep = sleep
        self.auth = AuthManager(settings, self, clock=clock)

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
        response = await self._send(method, path, request_headers, policy, kwargs)

        # One reactive refresh on 403 "Invalid bearer token" (API-REF §2.2, PLAN §2.2 step 5).
        if auth != "none" and not self.settings.no_auth and is_invalid_bearer(response):
            logger.info("bearer token refused; refreshing once and retrying %s %s", method, path)
            self.auth.invalidate()
            token = await self.auth.ensure_access(force=True)
            if token is not None:
                request_headers["Authorization"] = f"Bearer {token}"
            else:
                request_headers.pop("Authorization", None)
            response = await self._send(method, path, request_headers, policy, kwargs)
        return response

    async def _send(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        policy: RetryPolicy,
        kwargs: dict[str, Any],
    ) -> httpx.Response:
        request = self.http.build_request(method, path, headers=headers, **kwargs)
        await self.budget.acquire()
        started = time.monotonic()
        response = await with_retry(
            self.http.send, request, policy, sleep=self._sleep, on_retry=self.budget.acquire
        )
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
        """GET a binary artifact (published zips, files, exports)."""
        response = await self.request("GET", path, **kwargs)
        if response.status_code >= 400:
            raise error_from_response(response)
        return response.content

    # --- lifecycle -------------------------------------------------------------------
    async def aclose(self) -> None:
        await self.http.aclose()

    async def __aenter__(self) -> HaxcmsClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
