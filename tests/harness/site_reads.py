"""Anonymous site-level reads used by the live suites (shape verified by the Phase 2 probe).

The site outline (`GET /_sites/{site}/x/api/v1/items`) is public — the functional and
integration tests use it to assert on created pages without waiting for Phase 3 tools.
"""

from __future__ import annotations

from typing import Any

import httpx


def public_items(base_url: str, site: str) -> list[dict[str, Any]]:
    """The site's public outline items (empty list when the shape is unexpected)."""
    body = httpx.get(f"{base_url}/_sites/{site}/x/api/v1/items", timeout=30).json()
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        rows = data.get("items")
        return rows if isinstance(rows, list) else []
    return data if isinstance(data, list) else []


def public_titles(base_url: str, site: str) -> list[str]:
    """The outline's page titles, in manifest order."""
    return [str(item.get("title")) for item in public_items(base_url, site)]
