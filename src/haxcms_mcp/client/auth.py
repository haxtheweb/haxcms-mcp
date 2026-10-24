"""Authentication manager: access token, refresh, Site/User Tokens (PLAN ??2.3, API-REF ??2).

State: `access_token`, `access_issued_at`, cookie jar (on the client's httpx instance, holds
`haxcms_refresh_token`), `user_token`, per-site `site_tokens`. Access tokens live 15 minutes;
we refresh proactively at 12 minutes and reactively on a 403 "Invalid bearer token" (the client
calls `invalidate()` then `ensure_access(force=True)`). In `NO_AUTH` mode nothing is sent.

An explicit `logout()` sets a logged-out flag: automatic login is suppressed until the Agent
calls the `login` tool again, even when env credentials are configured.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import TYPE_CHECKING, Any

import httpx

from haxcms_mcp.client.envelope import MSG_AUTH_REQUIRED, error_from_response, unwrap_full
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from haxcms_mcp.client import HaxcmsClient
    from haxcms_mcp.config import Settings

logger = get_logger(__name__)

ACCESS_TOKEN_TTL_S = 15 * 60  # server-side: exp = iat + 15 min (API-REF ??2.1)
REFRESH_AFTER_S = 12 * 60  # PLAN ??2.3: refresh proactively at 12 min
REFRESH_COOKIE = "haxcms_refresh_token"


def parse_app_settings(text: str) -> dict[str, Any]:
    """Extract the `window.appSettings` object from a connection-settings JS response.

    Locate `window.appSettings`, then `json.JSONDecoder().raw_decode` from the first `{`
    (API-REF ??2.5).
    """
    marker = text.find("window.appSettings")
    if marker < 0:
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            "connection-settings response has no window.appSettings assignment",
            details={"body_head": text[:200]},
        )
    start = text.find("{", marker)
    if start < 0:
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            "connection-settings response has no JSON object after window.appSettings",
            details={"body_head": text[:200]},
        )
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            f"could not parse window.appSettings JSON: {exc}",
        ) from exc
    if not isinstance(obj, dict):
        raise HaxcmsMcpError(ErrorCode.UPSTREAM_ERROR, "window.appSettings is not a JSON object")
    return obj


class AuthManager:
    """Login/refresh lifecycle plus Site Token and User Token acquisition."""

    def __init__(
        self,
        settings: Settings,
        client: HaxcmsClient,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._client = client
        self._clock = clock
        self.access_token: str | None = None
        self.access_issued_at: float | None = None
        self.username: str | None = settings.username
        self._password: str | None = settings.password
        self.user_token_value: str | None = None
        self.site_tokens: dict[str, str] = {}
        self._logged_out = False

    # --- state ---------------------------------------------------------------
    @property
    def no_auth(self) -> bool:
        return self._settings.no_auth

    @property
    def has_refresh_cookie(self) -> bool:
        return REFRESH_COOKIE in self._client.http.cookies

    @property
    def token_age_s(self) -> float | None:
        if self.access_token is None or self.access_issued_at is None:
            return None
        return self._clock() - self.access_issued_at

    def _can_login(self) -> bool:
        return bool(self.username and self._password)

    def invalidate(self) -> None:
        """Drop the access token (reactive refresh on 403 'Invalid bearer token')."""
        self.access_token = None

    def _store_token(self, jwt: str) -> None:
        self.access_token = jwt
        self.access_issued_at = self._clock()

    def _clear(self) -> None:
        self.access_token = None
        self.access_issued_at = None
        self.user_token_value = None
        self.site_tokens.clear()
        self._client.http.cookies.clear()

    # --- access token lifecycle ------------------------------------------------
    async def ensure_access(self, *, force: bool = False) -> str | None:
        """Return a valid access token, logging in or refreshing as needed.

        Raises AUTH_REQUIRED when there is no session and none can be established.
        Returns None in NO_AUTH mode (callers then send no auth headers).
        """
        if self.no_auth:
            return None
        fresh = (
            self.access_token is not None
            and self.access_issued_at is not None
            and (self._clock() - self.access_issued_at) < REFRESH_AFTER_S
        )
        if fresh and not force:
            return self.access_token

        if self.access_token is not None or self.has_refresh_cookie:
            if await self.refresh():
                return self.access_token
            logger.info("token refresh failed; falling back to login")

        if self._logged_out:
            raise HaxcmsMcpError(
                ErrorCode.AUTH_REQUIRED,
                "session was logged out",
                hint="call the login tool to start a new session",
            )
        if self._can_login():
            assert self.username is not None and self._password is not None
            return await self.login(self.username, self._password)
        raise HaxcmsMcpError(
            ErrorCode.AUTH_REQUIRED,
            MSG_AUTH_REQUIRED,
            hint="call the login tool or set HAXCMS_MCP_USERNAME/HAXCMS_MCP_PASSWORD",
        )

    async def login(self, username: str, password: str) -> str:
        """POST session/login; store the access token and replace process credentials."""
        response = await self._client.request(
            "POST",
            self._client.sys("session/login"),
            json={"username": username, "password": password},
            auth="none",
            no_retry=True,  # the login limiter's Retry-After is minutes; surface 429 immediately
        )
        body = unwrap_full(response)
        jwt = body.get("jwt")
        if not isinstance(jwt, str) or not jwt:
            raise HaxcmsMcpError(
                ErrorCode.UPSTREAM_ERROR,
                "login response did not include a jwt",
                details={"keys": sorted(body)},
            )
        self._store_token(jwt)
        self.username = username
        self._password = password
        self._logged_out = False
        logger.info("logged in as %s", username)
        return jwt

    async def refresh(self) -> bool:
        """GET session/refresh using the cookie jar; False when the refresh token is refused.

        Never send Origin/Referer on this call (API-REF ??2.2); httpx adds neither. Refresh tokens
        rotate per use, so a failed refresh must not be retried with the stale cookie.
        """
        if self.no_auth:
            return False
        try:
            response = await self._client.request(
                "GET",
                self._client.sys("session/refresh"),
                auth="none",
                no_retry=True,
            )
            body = unwrap_full(response)
        except HaxcmsMcpError as exc:
            logger.debug("refresh failed: %s", exc.code.value)
            self.access_token = None
            return False
        jwt = body.get("jwt")
        if not isinstance(jwt, str) or not jwt:
            self.access_token = None
            return False
        self._store_token(jwt)
        return True

    async def logout(self) -> None:
        """POST session/logout (best effort) and clear all local auth state."""
        if not self.no_auth and (self.access_token is not None or self.has_refresh_cookie):
            with contextlib.suppress(HaxcmsMcpError, httpx.HTTPError):
                await self._client.request(
                    "POST", self._client.sys("session/logout"), auth="bearer", no_retry=True
                )
        self._clear()
        self._logged_out = True
        logger.info("logged out")

    # --- request tokens (connection-settings) ------------------------------------
    async def fetch_app_settings(self, site: str | None = None) -> dict[str, Any]:
        """GET session/connection-settings; the site Referer picks the siteToken's site."""
        headers = {"Accept": "application/javascript"}
        if site is not None:
            headers["Referer"] = f"{self._settings.base_url}/_sites/{site}/"
        response = await self._client.request(
            "GET",
            self._client.sys("session/connection-settings"),
            auth="none",
            headers=headers,
        )
        if response.status_code >= 400:
            raise error_from_response(response)
        settings = parse_app_settings(response.text)
        # Cache both tokens from any fetch: userToken is site-independent.
        user_token = settings.get("userToken")
        if isinstance(user_token, str) and user_token:
            self.user_token_value = user_token
        if site is not None:
            site_token = settings.get("siteToken")
            if isinstance(site_token, str) and site_token:
                self.site_tokens[site] = site_token
        return settings

    async def site_token(self, site: str) -> str | None:
        """Cached per-Site X-HAXCMS-Site-Token value (None in NO_AUTH mode)."""
        if self.no_auth:
            return None
        cached = self.site_tokens.get(site)
        if cached is not None:
            return cached
        await self.fetch_app_settings(site)
        token = self.site_tokens.get(site)
        if token is None:
            raise HaxcmsMcpError(
                ErrorCode.AUTH_FAILED,
                f"connection-settings returned no siteToken for site {site!r}",
                hint=f"check that site {site!r} exists (list_sites)",
            )
        return token

    async def user_token(self) -> str | None:
        """Cached process-wide X-HAXCMS-User-Token value (None in NO_AUTH mode)."""
        if self.no_auth:
            return None
        if self.user_token_value is not None:
            return self.user_token_value
        await self.fetch_app_settings()
        if self.user_token_value is None:
            raise HaxcmsMcpError(
                ErrorCode.AUTH_FAILED,
                "connection-settings returned no userToken",
                hint="the instance may run an older HAXcms; check its configuration",
            )
        return self.user_token_value
