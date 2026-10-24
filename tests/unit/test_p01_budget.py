"""Unit tests for the OutboundBudget token bucket (PLAN Phase 1 T1.1)."""

from __future__ import annotations

import asyncio

import pytest

from haxcms_mcp.client.budget import OutboundBudget
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

pytestmark = pytest.mark.unit


class FakeClock:
    """Monotonic clock advanced only by the budget's own sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def make_budget(rate: float, capacity: int, max_wait: float) -> tuple[OutboundBudget, FakeClock]:
    clock = FakeClock()
    return (
        OutboundBudget(
            rate=rate, capacity=capacity, max_wait=max_wait, clock=clock, sleep=clock.sleep
        ),
        clock,
    )


async def test_burst_is_immediate() -> None:
    budget, clock = make_budget(rate=1.0, capacity=3, max_wait=30.0)
    start = clock.now
    for _ in range(3):
        await budget.acquire()
    assert clock.now == start, "burst tokens must not wait"
    assert budget.stats.waits == 0


async def test_acquire_waits_for_refill() -> None:
    budget, clock = make_budget(rate=2.0, capacity=1, max_wait=30.0)
    await budget.acquire()  # empties the bucket
    await budget.acquire()  # must wait 1/2 s
    assert clock.now == pytest.approx(1000.5)
    assert budget.stats.waits == 1


async def test_refill_accumulates_over_time() -> None:
    budget, clock = make_budget(rate=1.0, capacity=4, max_wait=30.0)
    for _ in range(4):
        await budget.acquire()
    clock.now += 2.5  # 2.5 tokens refill
    assert budget.try_acquire() is True
    assert budget.try_acquire() is True
    assert budget.try_acquire() is False


async def test_denial_when_wait_exceeds_max() -> None:
    budget, _ = make_budget(rate=0.1, capacity=1, max_wait=5.0)  # 10 s per token
    await budget.acquire()
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await budget.acquire()
    error = excinfo.value
    assert error.code is ErrorCode.RATE_LIMITED
    assert error.details is not None
    assert error.details["retry_after_s"] == pytest.approx(10.0)
    assert budget.stats.denials == 1


async def test_concurrent_acquires_serialise_fairly() -> None:
    budget, clock = make_budget(rate=4.0, capacity=1, max_wait=30.0)
    await budget.acquire()  # empties the bucket immediately
    await asyncio.gather(*(budget.acquire() for _ in range(5)))
    # 6 tokens total at 4/s with capacity 1: (6 - 1) / 4 = 1.25 s of queueing
    assert clock.now == pytest.approx(1001.25)
    assert budget.stats.waits == 5
    assert budget.stats.denials == 0


async def test_concurrent_denials_do_not_starve_waiters() -> None:
    budget, _ = make_budget(rate=0.5, capacity=1, max_wait=1.0)  # 2 s per token > max_wait
    await budget.acquire()
    results = await asyncio.gather(*(budget.acquire() for _ in range(3)), return_exceptions=True)
    assert all(isinstance(r, HaxcmsMcpError) for r in results)
    assert budget.stats.denials == 3


def test_try_acquire_never_raises() -> None:
    budget, _ = make_budget(rate=1.0, capacity=1, max_wait=30.0)
    assert budget.try_acquire() is True
    assert budget.try_acquire() is False


def test_invalid_construction() -> None:
    with pytest.raises(ValueError):
        OutboundBudget(rate=0, capacity=1, max_wait=1)
    with pytest.raises(ValueError):
        OutboundBudget(rate=1, capacity=0, max_wait=1)
    with pytest.raises(ValueError):
        OutboundBudget(rate=1, capacity=1, max_wait=-1)
