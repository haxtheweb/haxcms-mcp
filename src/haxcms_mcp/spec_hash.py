"""Hashing of vendored/served HAXcms spec documents.

Kept apart from `compat.py` so `scripts/sync_specs.py` can import it before the generated
`spec_info.py` exists.

The hash is over the *parsed* document, not its bytes, so both HAXcms backends compare equal
when they serve the same contract (#3139), even when their prose differs (descriptions and
summaries are documentation, not contract): NodeJS serves the raw YAML at
`GET /system/api/v1/openapi`, while PHP serves it re-encoded as JSON with `info.version` and
`servers` filled in for the instance, and with empty objects encoded as `[]` (PHP
`json_encode` of an empty array).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import yaml

# Prose that documents the contract without changing it. Dropped only when the value is
# text, so a schema PROPERTY that happens to be called "description" (a dict) is kept.
_PROSE_KEYS = frozenset({"description", "summary"})


def _normalize(node: Any) -> Any:
    if isinstance(node, dict):
        kept = {
            str(key): _normalize(value)
            for key, value in node.items()
            if not (key in _PROSE_KEYS and isinstance(value, str))
        }
        return kept or None
    if isinstance(node, list):
        if not node:
            return None
        return [_normalize(value) for value in node]
    return node


def canonical_spec(data: bytes) -> Any:
    """Parse a spec (JSON or YAML) and drop the per-instance fields a backend may rewrite."""
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    try:
        document = json.loads(text)
    except ValueError:
        document = yaml.safe_load(text)
    if isinstance(document, dict):
        document = dict(document)
        document.pop("servers", None)
        info = document.get("info")
        if isinstance(info, dict):
            document["info"] = {k: v for k, v in info.items() if k != "version"}
    return _normalize(document)


def spec_sha256(data: bytes) -> str:
    """SHA-256 of a spec document's canonical form (format-, encoding- and CRLF-insensitive).

    Falls back to the raw bytes when the document does not parse, so a broken body still
    yields a stable (mismatching) hash rather than an exception.
    """
    try:
        canonical = canonical_spec(data)
    except (UnicodeDecodeError, yaml.YAMLError):
        return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
