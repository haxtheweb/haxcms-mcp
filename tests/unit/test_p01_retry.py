"""Unit tests for the retry policy (PLAN Phase 1 T1.2)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from haxcms_mcp.client.retry import RetryPolicy, retry_after_seconds, with_retry
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

pytestmark = pytest.mark.unit

POLICY = RetryPolicy(retry_max=3)


def make_request(method: str = "GET", url: str = "http://x.invalid/system/api/v1/sites"):
    return httpx.Request(method, url)


class Recorder:
    """Fake send + sleep + on_retry that records the sequence of events."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.sent = 0
        self.sleeps: list[float] = []
        self.retries = 0

    async def send(self, request: httpx.Request) -> httpx.Response:
        self.sent += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    async def on_retry(self) -> None:
        self.retries += 1

    def kwargs(self) -> dict[str, Any]:
        return {"sleep": self.sleep, "on_retry": self.on_retry}


def response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers or {}, request=make_request())


async def test_429_with_retry_after_then_success() -> None:
    rec = Recorder([response(429, {"Retry-After": "5"}), response(200)])
    result = await with_retry(rec.send, make_request(), POLICY, **rec.kwargs())
    assert result.status_code == 200
    assert rec.sleeps == [5.0]
    assert rec.retries == 1


async def test_429_without_retry_after_uses_default() -> None:
    rec = Recorder([response(429), response(200)])
    await with_retry(rec.send, make_request(), POLICY, **rec.kwargs())
    assert rec.sleeps == [2.0]


async def test_retry_after_is_capped_at_60s() -> None:
    assert retry_after_seconds(response(429, {"Retry-After": "120"}), POLICY) == 60.0
    assert retry_after_seconds(response(429, {"Retry-After": "-3"}), POLICY) == 2.0
    assert retry_after_seconds(response(429, {"Retry-After": "garbage"}), POLICY) == 2.0


async def test_429_exhaustion_returns_last_response() -> None:
    rec = Recorder([response(429) for _ in range(4)])
    result = await with_retry(rec.send, make_request(), POLICY, **rec.kwargs())
    assert result.status_code == 429
    assert rec.sent == 4  # 1 initial + retry_max retries
    assert rec.retries == 3


async def test_503_retried_for_get_with_backoff() -> None:
    rec = Recorder([response(503) for _ in range(4)])
    result = await with_retry(rec.send, make_request("GET"), POLICY, **rec.kwargs())
    assert result.status_code == 503
    assert rec.sent == 4
    assert rec.sleeps == [0.5, 1.0, 2.0]


async def test_503_then_success() -> None:
    rec = Recorder([response(503), response(200)])
    result = await with_retry(rec.send, make_request("GET"), POLICY, **rec.kwargs())
    assert result.status_code == 200
    assert rec.sleeps == [0.5]


async def test_post_never_retried_on_503() -> None:
    rec = Recorder([response(503)])
    result = await with_retry(rec.send, make_request("POST"), POLICY, **rec.kwargs())
    assert result.status_code == 503
    assert rec.sent == 1
    assert rec.sleeps == []


async def test_post_429_is_retried() -> None:
    rec = Recorder([response(429, {"Retry-After": "1"}), response(200)])
    result = await with_retry(rec.send, make_request("POST"), POLICY, **rec.kwargs())
    assert result.status_code == 200


async def test_connection_error_retried_for_get_then_success() -> None:
    rec = Recorder([httpx.ConnectError("boom"), httpx.ConnectError("boom"), response(200)])
    result = await with_retry(rec.send, make_request("GET"), POLICY, **rec.kwargs())
    assert result.status_code == 200
    assert rec.sleeps == [0.5, 1.0]


async def test_connection_error_on_post_maps_to_upstream_error() -> None:
    rec = Recorder([httpx.ConnectError("boom")])
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await with_retry(rec.send, make_request("POST"), POLICY, **rec.kwargs())
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR
    assert rec.sent == 1


async def test_timeout_exhaustion_maps_to_timeout_code() -> None:
    rec = Recorder([httpx.ReadTimeout("slow") for _ in range(4)])
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await with_retry(rec.send, make_request("GET"), POLICY, **rec.kwargs())
    assert excinfo.value.code is ErrorCode.TIMEOUT
    assert rec.sent == 4
