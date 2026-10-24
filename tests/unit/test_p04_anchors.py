"""Unit tests for anchor resolution (PLAN Phase 4 T4.2; §2.3).

Covers the PLAN list: text, selector, auto detection, occurrence, not-found payload,
ambiguous payload, attribute-value match for images.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.content import Block
from haxcms_mcp.services.content.anchors import find_matches, parse_selector, resolve_anchor
from haxcms_mcp.services.content.parser import parse_blocks

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pages"


def fixture_blocks(name: str) -> list[Block]:
    return parse_blocks((FIXTURES / f"{name}.html").read_text(encoding="utf-8"))


# --- auto detection ------------------------------------------------------------------------------


def test_auto_kind_detects_selectors() -> None:
    blocks = fixture_blocks("tutorial_finished")
    # a bare lowercase tag with optional brackets is a selector...
    assert resolve_anchor(blocks, "video-player").tag == "video-player"
    assert resolve_anchor(blocks, "media-image[source*=Songline_1]").index == 3
    # ...anything else (spaces, punctuation, capitals) is text — both links match as text
    assert [block.tag for block in find_matches(blocks, "Watch it here.")] == ["p", "p"]
    assert resolve_anchor(blocks, "Designing in the Prairie Spirit").tag == "h2"


def test_explicit_kinds_override_detection() -> None:
    blocks = fixture_blocks("tutorial_finished")
    # forced text: "h2" as text matches nothing (no block TEXT contains 'h2')
    assert find_matches(blocks, "video-player", kind="text") == []
    # forced selector
    assert resolve_anchor(blocks, "h2", kind="selector", occurrence=1).text == (
        "Designing in the Prairie Spirit"
    )


# --- text matching --------------------------------------------------------------------------------


def test_text_match_is_case_insensitive_substring() -> None:
    blocks = fixture_blocks("tutorial_finished")
    block = resolve_anchor(blocks, "PRAIRIE DOES NOT ANNOUNCE")
    assert block.text == "The prairie does not announce its design; you have to notice it."


def test_text_match_searches_media_attribute_values() -> None:
    blocks = fixture_blocks("tutorial_finished")
    # "Songline_1" appears in no block TEXT — the media-image attribute scan finds it
    block = resolve_anchor(blocks, "Songline_1")
    assert block.tag == "media-image"
    assert block.index == 3
    # "prairie-walk" LOOKS like a tag selector to auto-detection — force the text kind
    # to reach the video-player's source URL fragment
    assert find_matches(blocks, "prairie-walk", kind="text")[0].tag == "video-player"
    assert find_matches(blocks, "prairie-walk") == []  # auto: selector, no such tag
    # non-media blocks get NO attribute scan: the <a href> URL is not block text
    assert find_matches(blocks, "https://example.com/lecture") == []


def test_empty_anchor_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as info:
        resolve_anchor(fixture_blocks("empty"), "   ")
    assert info.value.code is ErrorCode.INVALID_ARGUMENT


# --- selectors ------------------------------------------------------------------------------------


def test_parse_selector_grammar() -> None:
    assert parse_selector("media-image") == ("media-image", [])
    assert parse_selector("input[correct]") == ("input", [("correct", None, None)])
    assert parse_selector('a[href="https://x.dev"]') == ("a", [("href", "=", "https://x.dev")])
    assert parse_selector("media-image[source*=Songline]") == (
        "media-image",
        [("source", "*=", "Songline")],
    )
    assert parse_selector("input[type=checkbox][value=Ada]") == (
        "input",
        [("type", "=", "checkbox"), ("value", "=", "Ada")],
    )


def test_selector_tag_only() -> None:
    blocks = fixture_blocks("tutorial_finished")
    assert [block.index for block in find_matches(blocks, "p")] == [0, 1, 2, 4, 6, 9, 11]
    assert len(find_matches(blocks, "h2")) == 2


def test_selector_attribute_presence() -> None:
    blocks = fixture_blocks("quiz")
    inputs = find_matches(blocks, "input")
    assert inputs == []  # inputs are CHILDREN of multiple-choice, not top-level blocks
    correct = find_matches(fixture_blocks("quiz"), "multiple-choice[randomize]")
    assert len(correct) == 1


def test_selector_attribute_value_and_contains() -> None:
    blocks = fixture_blocks("tutorial_finished")
    assert resolve_anchor(blocks, "media-image[source=files/Songline_2.png]").index == 7
    assert resolve_anchor(blocks, "media-image[source*=Songline_2]").index == 7
    assert find_matches(blocks, "media-image[source*=nope]") == []


def test_selector_chained_brackets() -> None:
    blocks = fixture_blocks("quiz")
    matches = find_matches(blocks, "multiple-choice[title=Prairie quiz][single-option]")
    assert len(matches) == 1 and matches[0].tag == "multiple-choice"


def test_invalid_selector_raises() -> None:
    with pytest.raises(HaxcmsMcpError) as info:
        parse_selector("123nope")
    assert info.value.code is ErrorCode.INVALID_ARGUMENT


# --- occurrence ---------------------------------------------------------------------------------


def test_occurrence_first_last_and_integer() -> None:
    blocks = fixture_blocks("tutorial_finished")
    assert resolve_anchor(blocks, "h2", occurrence="first").text == (
        "Designing in the Prairie Spirit"
    )
    assert resolve_anchor(blocks, "h2", occurrence="last").text == "The First Secret is Noticing"
    assert resolve_anchor(blocks, "h2", occurrence=1).index == 5
    assert resolve_anchor(blocks, "h2", occurrence="2").index == 8


def test_single_match_needs_no_occurrence() -> None:
    blocks = fixture_blocks("tutorial_finished")
    assert resolve_anchor(blocks, "video-player").index == 10


def test_occurrence_out_of_range() -> None:
    blocks = fixture_blocks("tutorial_finished")
    with pytest.raises(HaxcmsMcpError) as info:
        resolve_anchor(blocks, "h2", occurrence=3)
    assert info.value.code is ErrorCode.ANCHOR_NOT_FOUND
    assert "out of range" in info.value.message


def test_invalid_occurrence_word() -> None:
    with pytest.raises(HaxcmsMcpError) as info:
        resolve_anchor(fixture_blocks("tutorial_finished"), "h2", occurrence="second")
    assert info.value.code is ErrorCode.INVALID_ARGUMENT


# --- error payloads -----------------------------------------------------------------------------


def test_not_found_payload_carries_previews() -> None:
    blocks = fixture_blocks("tutorial_finished")
    with pytest.raises(HaxcmsMcpError) as info:
        resolve_anchor(blocks, "no such text anywhere")
    error = info.value
    assert error.code is ErrorCode.ANCHOR_NOT_FOUND
    assert error.details is not None
    assert error.details["anchor"] == "no such text anywhere"
    assert error.details["block_count"] == 12
    previews = error.details["blocks"]
    assert len(previews) <= 10
    assert previews[0] == {
        "index": 0,
        "tag": "p",
        "preview": "The course title came from a phrase I could not stop turning over.",
    }


def test_not_found_preview_limit() -> None:
    blocks = parse_blocks("".join(f"<p>block {i}</p>" for i in range(15)))
    with pytest.raises(HaxcmsMcpError) as info:
        resolve_anchor(blocks, "missing")
    assert info.value.details is not None
    assert len(info.value.details["blocks"]) == 10


def test_ambiguous_payload_lists_every_match() -> None:
    blocks = fixture_blocks("tutorial_finished")
    with pytest.raises(HaxcmsMcpError) as info:
        resolve_anchor(blocks, "Watch it here.")
    error = info.value
    assert error.code is ErrorCode.ANCHOR_AMBIGUOUS
    assert "matches 2 blocks" in error.message
    matches = error.details["matches"]  # type: ignore[index]
    assert [entry["index"] for entry in matches] == [9, 11]
    assert all("preview" in entry and "tag" in entry for entry in matches)
