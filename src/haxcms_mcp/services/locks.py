"""Per-Site write locks (PLAN §2.3).

`async with site_lock(site):` wraps every service write so two concurrent Tool calls
cannot interleave a read-modify-write on the same Page in one process. Locks are keyed by
site name (writes to different sites stay parallel) and are taken ONLY at the outermost
operation entry points (the block operations, `set_page_content`, page/site writes) —
helpers those call (e.g. `content.save_content`) never re-acquire, so nesting cannot
deadlock.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# site -> lock. Deliberately NOT scoped per caller: on a non-IAM HAXcms every user writes to
# the same sites, so two callers must still serialise on one site. (On HAXiam two users'
# same-named sites then wait on each other briefly; correctness wins over that.)
_locks: dict[str, asyncio.Lock] = {}
MAX_IDLE_LOCKS = 1024


def _prune() -> None:
    """Drop idle locks once the table grows (keys are caller-supplied site names)."""
    if len(_locks) <= MAX_IDLE_LOCKS:
        return
    for key, lock in list(_locks.items()):
        if not lock.locked():
            del _locks[key]


@asynccontextmanager
async def site_lock(site: str) -> AsyncIterator[None]:
    """Serialise writes for one site name within this process."""
    lock = _locks.get(site)
    if lock is None:
        _prune()  # bounded: the keys are caller-supplied site names (security audit)
        lock = _locks.setdefault(site, asyncio.Lock())
    async with lock:
        yield
