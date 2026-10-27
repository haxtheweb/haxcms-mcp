"""Security audit: process-wide caches and locks stay bounded and do not mix callers."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from haxcms_mcp.client.principal import Principal, current_principal
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services import locks
from haxcms_mcp.services.catalog import service as catalog_module
from haxcms_mcp.services.catalog.service import CatalogService

pytestmark = pytest.mark.unit


async def test_catalog_failures_are_only_remembered_briefly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"t": 1000.0}
    monkeypatch.setattr(catalog_module.time, "monotonic", lambda: now["t"])
    service = CatalogService()
    calls = {"n": 0}

    async def failing() -> Any:
        calls["n"] += 1
        raise HaxcmsMcpError(ErrorCode.UPSTREAM_ERROR, "boom")

    assert await service._cached("demo|block|x", failing) is None
    assert await service._cached("demo|block|x", failing) is None
    assert calls["n"] == 1
    now["t"] += catalog_module.FAILURE_CACHE_SECONDS + 1
    await service._cached("demo|block|x", failing)
    assert calls["n"] == 2  # not the 10-minute success TTL


async def test_catalog_entries_are_scoped_per_caller() -> None:
    service = CatalogService()

    async def answer(value: str) -> Any:
        return {"who": value}

    reset = current_principal.set(Principal("token-ann", "ann"))
    try:
        assert await service._cached("same-site|block|x", lambda: answer("ann")) == {"who": "ann"}
    finally:
        current_principal.reset(reset)
    reset = current_principal.set(Principal("token-bob", "bob"))
    try:
        assert await service._cached("same-site|block|x", lambda: answer("bob")) == {"who": "bob"}
    finally:
        current_principal.reset(reset)


async def test_catalog_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_module, "MAX_CACHE_ENTRIES", 5)
    service = CatalogService()

    async def value() -> Any:
        return {"ok": True}

    for n in range(20):
        await service._cached(f"site-{n}|block|x", value)
    assert len(service._cache) == 5


async def test_site_locks_are_pruned_but_held_locks_survive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(locks, "MAX_IDLE_LOCKS", 3)
    monkeypatch.setattr(locks, "_locks", {})
    async with locks.site_lock("held"):
        for n in range(10):
            async with locks.site_lock(f"site-{n}"):
                pass
        assert "held" in locks._locks
        assert len(locks._locks) <= locks.MAX_IDLE_LOCKS + 1


async def test_site_locks_still_serialise_one_site_across_callers() -> None:
    """Correctness over isolation: on a non-IAM HAXcms every user edits the same sites."""
    order: list[str] = []

    async def write(user: str) -> None:
        reset = current_principal.set(Principal(f"token-{user}", user))
        try:
            async with locks.site_lock("shared-site"):
                order.append(f"{user}-start")
                await asyncio.sleep(0.01)
                order.append(f"{user}-end")
        finally:
            current_principal.reset(reset)

    await asyncio.gather(write("ann"), write("bob"))
    assert order in (
        ["ann-start", "ann-end", "bob-start", "bob-end"],
        ["bob-start", "bob-end", "ann-start", "ann-end"],
    )
