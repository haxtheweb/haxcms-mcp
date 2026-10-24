"""Outbound Budget: one process-wide token bucket shared by every request (PLAN §2.3).

`rate` tokens per second refill into a bucket of `capacity` (burst). `acquire()` waits until a
token is reserved, or raises `RATE_LIMITED` when the projected wait exceeds `max_wait`. The clock
and sleeper are injectable so tests run deterministically under a fake clock.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

if TYPE_CHECKING:
    from haxcms_mcp.config import Settings

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class BudgetStats:
    """Metrics exposed for `whoami` and tests."""

    tokens: float
    waits: int
    denials: int


class OutboundBudget:
    """Token bucket rate limiter for outbound HAXcms requests."""

    def __init__(
        self,
        *,
        rate: float,
        capacity: int,
        max_wait: float,
        clock: Clock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if max_wait < 0:
            raise ValueError("max_wait must be >= 0")
        self._rate = float(rate)
        self._capacity = float(capacity)
        self._max_wait = float(max_wait)
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = asyncio.Lock()
        self._waits = 0
        self._denials = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> OutboundBudget:
        return cls(
            rate=settings.rate_limit_rps,
            capacity=settings.rate_limit_burst,
            max_wait=settings.rate_limit_max_wait_s,
        )

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now

    async def acquire(self) -> None:
        """Reserve one token, waiting if needed; raise RATE_LIMITED when the wait is too long."""
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                wait = 0.0
            else:
                wait = (1.0 - self._tokens) / self._rate
                if wait > self._max_wait:
                    self._denials += 1
                    raise HaxcmsMcpError(
                        ErrorCode.RATE_LIMITED,
                        "outbound request budget exhausted: next token in "
                        f"{wait:.1f}s exceeds max wait {self._max_wait:.0f}s",
                        hint=(
                            "retry later, or raise HAXCMS_MCP_RATE_LIMIT_RPS / "
                            "HAXCMS_MCP_RATE_LIMIT_BURST / HAXCMS_MCP_RATE_LIMIT_MAX_WAIT_S"
                        ),
                        details={"retry_after_s": round(wait, 2)},
                    )
                # Reserve into the negative so concurrent acquirers queue fairly.
                self._tokens -= 1.0
        if wait > 0.0:
            self._waits += 1
            await self._sleep(wait)

    def try_acquire(self) -> bool:
        """Non-blocking acquire; True when a token was taken immediately."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    @property
    def stats(self) -> BudgetStats:
        self._refill()
        return BudgetStats(tokens=self._tokens, waits=self._waits, denials=self._denials)
