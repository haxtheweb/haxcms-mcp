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

_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def site_lock(site: str) -> AsyncIterator[None]:
    """Serialise writes for one site name within this process."""
    lock = _locks.setdefault(site, asyncio.Lock())
    async with lock:
        yield
