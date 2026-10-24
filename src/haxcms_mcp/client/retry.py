"""Retry policy for outbound requests (PLAN §2.3).

- 429: sleep `Retry-After` (cap 60 s, default 2 s) and retry up to `retry_max` times; every retry
  counts against the Outbound Budget via the `on_retry` hook.
- Connection errors and 502/503/504: retry idempotent methods (GET, HEAD) only, exponential
  back-off 0.5 s, 1 s, 2 s. POST/PATCH/DELETE are never retried automatically.
- httpx timeouts map to TIMEOUT, other transport failures to UPSTREAM_ERROR once retries are
  exhausted (or immediately for non-idempotent methods).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

if TYPE_CHECKING:
    from haxcms_mcp.config import Settings

Send = Callable[[httpx.Request], Awaitable[httpx.Response]]
Sleep = Callable[[float], Awaitable[None]]
OnRetry = Callable[[], Awaitable[None]]

TRANSIENT_STATUSES = frozenset({502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD"})
BACKOFF_SCHEDULE_S = (0.5, 1.0, 2.0)


@dataclass(frozen=True)
class RetryPolicy:
    """Tunables for `with_retry`; defaults per PLAN §2.3 / §4."""

    retry_max: int = 3
    retry_after_cap_s: float = 60.0
    retry_after_default_s: float = 2.0

    @classmethod
    def from_settings(cls, settings: Settings) -> RetryPolicy:
        return cls(retry_max=settings.retry_max)


def retry_after_seconds(response: httpx.Response, policy: RetryPolicy) -> float:
    """Parse Retry-After (seconds form); default 2 s, capped at 60 s."""
    raw = response.headers.get("Retry-After", "")
    try:
        delay = float(raw)
    except ValueError:
        delay = policy.retry_after_default_s
    if delay < 0:
        delay = policy.retry_after_default_s
    return min(delay, policy.retry_after_cap_s)


def _transport_error(exc: httpx.TransportError, request: httpx.Request) -> HaxcmsMcpError:
    if isinstance(exc, httpx.TimeoutException):
        return HaxcmsMcpError(
            ErrorCode.TIMEOUT,
            f"request to {request.url.path} timed out",
            hint="the instance may be busy; retry or raise HAXCMS_MCP_TIMEOUT_S",
        )
    return HaxcmsMcpError(
        ErrorCode.UPSTREAM_ERROR,
        f"connection to {request.url.host} failed: {exc}",
        hint="check HAXCMS_MCP_BASE_URL and that the HAXcms instance is running",
    )


async def with_retry(
    send: Send,
    request: httpx.Request,
    policy: RetryPolicy,
    *,
    sleep: Sleep = asyncio.sleep,
    on_retry: OnRetry | None = None,
) -> httpx.Response:
    """Send `request`, applying the retry policy. Returns the last response on exhaustion."""
    idempotent = request.method.upper() in IDEMPOTENT_METHODS
    rate_limit_attempts = 0
    transient_attempt = 0

    while True:
        try:
            response = await send(request)
        except httpx.TransportError as exc:
            if not idempotent or transient_attempt >= len(BACKOFF_SCHEDULE_S):
                raise _transport_error(exc, request) from exc
            delay = BACKOFF_SCHEDULE_S[transient_attempt]
            transient_attempt += 1
            if on_retry is not None:
                await on_retry()
            await sleep(delay)
            continue

        if response.status_code == 429 and rate_limit_attempts < policy.retry_max:
            delay = retry_after_seconds(response, policy)
            rate_limit_attempts += 1
            if on_retry is not None:
                await on_retry()
            await sleep(delay)
            continue

        if (
            response.status_code in TRANSIENT_STATUSES
            and idempotent
            and transient_attempt < len(BACKOFF_SCHEDULE_S)
        ):
            delay = BACKOFF_SCHEDULE_S[transient_attempt]
            transient_attempt += 1
            if on_retry is not None:
                await on_retry()
            await sleep(delay)
            continue

        return response
