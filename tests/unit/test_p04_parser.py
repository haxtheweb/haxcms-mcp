"""Unit tests for the block parser and serializer (PLAN Phase 4 T4.2).

Round-trip goldens per PLAN: parse → serialize equals the fixture modulo insignificant
whitespace and attribute quote style — asserted structurally (tag/attributes/collapsed
text per block) plus serializer idempotence (a second pass changes nothing). Bare boolean
attributes serialise in lxml's bare form (`<input correct>`) which HAX accepts (presence
is truth); tools that want `card="card"` pass the value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from haxcms_mcp.services.content.media_schema import build_media_schema
from haxcms_mcp.services.content.parser import parse_blocks, parse_body, to_blocks
from haxcms_mcp.services.content.serializer import serialize, serialize_elements

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pages"

ALL_FIXTURES = ["tutorial_finished", "grid_plate", "quiz", "bare_text", "empty"]


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def shape(blocks: list) -> list[tuple]:
    """Whitespace/quote-insensitive block structure: (tag, attributes, collapsed text)."""
    return [(block.tag, block.attributes, block.text) for block in blocks]


# --- round-trips ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_roundtrip_equals_fixture_modulo_whitespace(name: str) -> None:
    blocks = parse_blocks(fixture(name))
    reparsed = parse_blocks(serialize(blocks))
    assert shape(reparsed) == shape(blocks)


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_serializer_is_idempotent(name: str) -> None:
    once = serialize(parse_blocks(fixture(name)))
    twice = serialize(parse_blocks(once))
    assert twice == once


def test_tutorial_fixture_block_sequence() -> None:
    blocks = parse_blocks(fixture("tutorial_finished"))
    assert [block.tag for block in blocks] == [
        "p",
        "p",
        "p",
        "media-image",
        "p",
        "h2",
        "p",
        "media-image",
        "h2",
        "p",
        "video-player",
        "p",
    ]
    assert blocks[0].index == 0 and blocks[-1].index == len(blocks) - 1


# --- bare text --------------------------------------------------------------------------------


def test_bare_text_is_wrapped_in_paragraphs() -> None:
    blocks = parse_blocks(fixture("bare_text"))
    assert [block.tag for block in blocks] == ["p", "p", "p"]
    assert blocks[0].text == "Loose text before anything."
    assert blocks[1].text == "A real paragraph."
    assert blocks[2].text == "and loose text after"
    assert blocks[0].html == "<p>Loose text before anything.</p>"


def test_bare_text_between_elements_and_after_comments() -> None:
    blocks = parse_blocks("<p>a</p><!-- note -->loose tail")
    assert [(block.tag, block.text) for block in blocks] == [("p", "a"), ("p", "loose tail")]


def test_whitespace_only_body_has_no_blocks() -> None:
    assert parse_body("") == []
    assert parse_body("   \n  ") == []


def test_empty_page_fixture() -> None:
    blocks = parse_blocks(fixture("empty"))
    assert len(blocks) == 1
    assert blocks[0].tag == "p"
    assert blocks[0].text == ""
    assert blocks[0].html == "<p></p>"
    # preview falls back to the html for text-less blocks
    assert blocks[0].preview == "<p></p>"


# --- slots and attributes -----------------------------------------------------------------------


def test_grid_plate_slots_preserved() -> None:
    blocks = parse_blocks(fixture("grid_plate"))
    grid = blocks[1]
    assert grid.tag == "grid-plate"
    assert grid.attributes == {"layout": "1-1", "disable-responsive": "disable-responsive"}
    assert 'slot="col-1"' in grid.html
    assert 'slot="col-2"' in grid.html
    assert "Left column" in grid.text and "Left text." in grid.text
    # slotted children survive the round trip unchanged
    assert '<h2 slot="col-1">Left column</h2>' in serialize(parse_blocks(grid.html))


def test_self_check_question_slot_preserved() -> None:
    blocks = parse_blocks(fixture("quiz"))
    self_check = blocks[0]
    assert self_check.tag == "self-check"
    assert '<p slot="question">Which of these is a songline?</p>' in self_check.html


def test_boolean_attributes_round_trip() -> None:
    blocks = parse_blocks(fixture("quiz"))
    multiple_choice = blocks[1]
    assert multiple_choice.attributes["randomize"] == "randomize"
    # lxml parses bare `correct` as an empty-string attribute and serialises it bare again
    assert "correct" in multiple_choice.html
    reparsed = parse_blocks(serialize(blocks))
    assert shape(reparsed) == shape(blocks)


def test_media_image_attributes_and_text_normalisation() -> None:
    blocks = parse_blocks(fixture("tutorial_finished"))
    first_image = blocks[3]
    assert first_image.attributes["source"] == "files/Songline_1.png"
    assert first_image.attributes["size"] == "wide"
    assert first_image.text == ""  # media blocks carry no text
    assert first_image.preview.startswith("<media-image ")
    grid = parse_blocks(fixture("grid_plate"))[1]
    assert "  " not in grid.text and not grid.text.startswith(" ")  # whitespace collapsed


# --- media schema -----------------------------------------------------------------------------


def test_media_schema_from_tutorial_page() -> None:
    schema = build_media_schema(parse_body(fixture("tutorial_finished")))
    assert schema == [
        {"tag": "media-image", "properties": {"source": "files/Songline_1.png"}},
        {"tag": "media-image", "properties": {"source": "files/Songline_2.png"}},
        {
            "tag": "video-player",
            "properties": {"source": "https://www.youtube.com/watch?v=prairie-walk"},
        },
    ]


def test_media_schema_finds_nested_and_dedupes() -> None:
    elements = parse_body(
        '<p>Text with <img src="a.png"> inside.</p>'
        '<grid-plate layout="1-1"><media-image slot="col-1" source="b.png"></media-image>'
        "</grid-plate>"
        '<p><img src="a.png"> again</p>'
        "<a11y-gif-player src='c.gif'></a11y-gif-player>"
    )
    schema = build_media_schema(elements)
    assert schema == [
        {"tag": "img", "properties": {"src": "a.png"}},
        {"tag": "media-image", "properties": {"source": "b.png"}},
        {"tag": "a11y-gif-player", "properties": {"src": "c.gif"}},
    ]


def test_media_schema_empty_without_media() -> None:
    assert build_media_schema(parse_body("<p>plain</p>")) == []


# --- serializer ----------------------------------------------------------------------------------


def test_serialize_elements_matches_serialize_blocks() -> None:
    elements = parse_body(fixture("tutorial_finished"))
    assert serialize_elements(elements) == serialize(to_blocks(elements))


def test_serialize_joins_with_newlines() -> None:
    blocks = parse_blocks("<p>one</p><p>two</p>")
    assert serialize(blocks) == "<p>one</p>\n<p>two</p>"
