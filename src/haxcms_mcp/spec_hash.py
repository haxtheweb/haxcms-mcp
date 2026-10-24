"""Hashing of vendored/served HAXcms spec documents (dependency-free on purpose).

Kept apart from `compat.py` so `scripts/sync_specs.py` can import it before the generated
`spec_info.py` exists.
"""

from __future__ import annotations

import hashlib


def spec_sha256(data: bytes) -> str:
    """SHA-256 of a spec document, insensitive to CRLF vs LF checkouts."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
