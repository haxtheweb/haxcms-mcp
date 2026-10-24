"""Anchor resolution (PLAN Phase 4 T4.2; §2.3).

An anchor addresses ONE block, by TEXT (case-insensitive substring of `Block.text`, and
of attribute values for media blocks, so "Songline_1" finds the image) or by SELECTOR
(`tag`, `tag[attr]`, `tag[attr=value]`, `tag[attr*=value]`, chained brackets). Kind
`auto` treats the string as a selector when it matches `^[a-z][a-z0-9-]*(\\[[^\\]]+\\])*$`
and as text otherwise.

`occurrence` is `first`, `last` or a 1-based integer into the matches. Zero matches raise
ANCHOR_NOT_FOUND (details carry up to ten block previews); several matches without an
occurrence raise ANCHOR_AMBIGUOUS (details list every match's index and preview).
"""

from __future__ import annotations

import re
from typing import Any

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.content import Block

SELECTOR_RE = re.compile(r"^[a-z][a-z0-9-]*(\[[^\]]+\])*$")
_TAG_RE = re.compile(r"^([a-z][a-z0-9-]*)")
# the name class excludes `*` so `attr*=value` splits into ("attr", "*=", "value")
_CONDITION_RE = re.compile(r"\[\s*([^\]=*\s]+)\s*(?:([*]?=)\s*([^\]]*?)\s*)?\]")

# tags whose attribute values text anchors also search (source/src-carrying media blocks)
MEDIA_TAGS = frozenset({"media-image", "video-player", "audio-player", "img", "a11y-gif-player"})

PREVIEW_LIMIT = 10

Condition = tuple[str, str | None, str | None]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_selector(selector: str) -> tuple[str, list[Condition]]:
    """Split `tag[attr=value][attr*=value][attr]` into `(tag, [(name, op, value), ...])`."""
    match = _TAG_RE.match(selector)
    if not match:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid selector {selector!r}",
            hint="selector grammar: tag, tag[attr], tag[attr=value], tag[attr*=value], chained",
        )
    # findall yields "" for groups that did not participate: a bare [attr] has no op and
    # no value (op "" → None, value None); [attr=value] keeps value (possibly "")
    conditions: list[Condition] = [
        (name, op or None, _unquote(value) if op else None)
        for name, op, value in _CONDITION_RE.findall(selector[match.end() :])
    ]
    return match.group(1), conditions


def _selector_matches(block: Block, tag: str, conditions: list[Condition]) -> bool:
    if block.tag != tag:
        return False
    for name, op, value in conditions:
        actual = block.attributes.get(name)
        if actual is None:
            return False
        if op == "=" and actual != (value or ""):
            return False
        if op == "*=" and (value or "") not in actual:
            return False
    return True


def _text_matches(block: Block, needle: str) -> bool:
    low = needle.lower()
    if low in block.text.lower():
        return True
    if block.tag in MEDIA_TAGS:
        return any(low in value.lower() for value in block.attributes.values())
    return False


def _previews(blocks: list[Block], *, limit: int | None = PREVIEW_LIMIT) -> list[dict[str, Any]]:
    capped = blocks[:limit] if limit is not None else blocks
    return [{"index": block.index, "tag": block.tag, "preview": block.preview} for block in capped]


def find_matches(blocks: list[Block], anchor: str, kind: str = "auto") -> list[Block]:
    """Every block the anchor matches (before occurrence selection)."""
    text = (anchor or "").strip()
    if not text:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "anchor must not be empty",
            hint="pass block text (substring) or a selector like media-image[source*=Songline]",
        )
    if kind not in {"auto", "text", "selector"}:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT, f"invalid anchor kind {kind!r}", hint="auto, text, selector"
        )
    if kind == "auto":
        kind = "selector" if SELECTOR_RE.fullmatch(text) else "text"
    if kind == "selector":
        tag, conditions = parse_selector(text)
        return [block for block in blocks if _selector_matches(block, tag, conditions)]
    return [block for block in blocks if _text_matches(block, text)]


def resolve_anchor(
    blocks: list[Block],
    anchor: str,
    occurrence: str | int | None = None,
    kind: str = "auto",
) -> Block:
    """The ONE block the anchor (+occurrence) addresses; raises the ANCHOR_* errors."""
    matches = find_matches(blocks, anchor, kind)
    if not matches:
        raise HaxcmsMcpError(
            ErrorCode.ANCHOR_NOT_FOUND,
            f"no block matches anchor {anchor!r}",
            hint="anchors match block text (substring, case-insensitive) or a selector "
            "like h2 or media-image[source*=Songline]; occurrence picks among matches",
            details={"anchor": anchor, "block_count": len(blocks), "blocks": _previews(blocks)},
        )
    if occurrence is None:
        if len(matches) == 1:
            return matches[0]
        raise HaxcmsMcpError(
            ErrorCode.ANCHOR_AMBIGUOUS,
            f"anchor {anchor!r} matches {len(matches)} blocks; pass occurrence",
            hint="occurrence is 'first', 'last' or a 1-based number into the matches",
            details={"anchor": anchor, "matches": _previews(matches, limit=None)},
        )
    position = _occurrence_position(occurrence, matches, anchor)
    return matches[position]


def _occurrence_position(occurrence: str | int, matches: list[Block], anchor: str) -> int:
    if isinstance(occurrence, bool):
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT, f"invalid occurrence {occurrence!r}", hint="first/last/int"
        )
    if isinstance(occurrence, int):
        position = occurrence - 1
    else:
        word = occurrence.strip().lower()
        if word == "first":
            position = 0
        elif word == "last":
            position = len(matches) - 1
        elif word.isdigit():
            position = int(word) - 1
        else:
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                f"invalid occurrence {occurrence!r}",
                hint="occurrence is 'first', 'last' or a 1-based number",
            )
    if not 0 <= position < len(matches):
        raise HaxcmsMcpError(
            ErrorCode.ANCHOR_NOT_FOUND,
            f"occurrence {occurrence} out of range: anchor {anchor!r} matches {len(matches)} "
            "blocks",
            details={"anchor": anchor, "matches": _previews(matches, limit=None)},
        )
    return position
