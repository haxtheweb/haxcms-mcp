"""Phase 4 integration tests: every typed block tool against the live instance.

PLAN Phase 4 integration list: `test_p04_typed_blocks_live.py` (every typed tool inserts
and the saved HTML contains the tag with the attributes). This is also the T4.7 verify
probe for sanitisation: for all 37 tools the exact serialized block HTML written by the
tool must come back byte-identical from the stored body — HAXcms 26.8.1 stores what the
envelope save sends, so every Core Block tag survives unchanged.

The tools are chunked by catalog category (one live page per chunk) so a failure names
the category, while a single page per chunk keeps the run short.
"""

from __future__ import annotations

import html as html_module
import re
from typing import Any

import pytest

from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

# (tool, arguments, expected tag, fragments that must survive in the stored body)
Entry = tuple[str, dict[str, Any], str, list[str]]

_ATTR_RE = re.compile(r"""([\w-]+)="([^"]*)"|([\w-]+)='([^']*)'""")


def _normalise_attr(match: re.Match[str]) -> str:
    """Server attribute form: entity-decoded value, re-escaping only & and "."""
    name = match.group(1) or match.group(3)
    value = match.group(2) if match.group(1) else match.group(4)
    value = html_module.unescape(value)
    value = value.replace("&", "&amp;").replace('"', "&quot;")
    return f'{name}="{value}"'


def stored_form(block_html: str) -> str:
    """The exact saveNode sanitisation of one serialized block (live-verified T4.7).

    Every Core Block TAG survives storage unchanged; these forms are rewritten on save
    (GET body and on-disk file agree byte-for-byte):

    * `target="_blank"` on `<a>` is dropped;
    * `preserve-content` on `<template>` (code-sample) is dropped;
    * the bare boolean `correct` on assessment `<input>`s is dropped;
    * attribute VALUES are entity-decoded and re-escaped with only `&` and `"`: JSON
      attributes (vocab-term links, timeline events) come back double-quoted with
      `&quot;` and raw `<p>` inside, `&lt;` inside plain values becomes raw `<`,
      while text nodes keep their escaping.
    """
    out = block_html.replace(' target="_blank"', "")
    out = out.replace(' preserve-content="preserve-content"', "")
    out = re.sub(r" correct(?=>)", "", out)
    return _ATTR_RE.sub(_normalise_attr, out)


MEDIA: list[Entry] = [
    (
        "add_image",
        {
            "source": "files/a.png",
            "alt": "A path",
            "caption": "The path",
            "citation": "Photo: me",
            "card": True,
            "size": "small",
        },
        "media-image",
        ['source="files/a.png"', 'card="card"', 'size="small"'],
    ),
    (
        "add_video",
        {"source": "https://youtu.be/x", "title": "Lecture", "accent_color": "red"},
        "video-player",
        ['source="https://youtu.be/x"', 'media-title="Lecture"', 'accent-color="red"'],
    ),
    (
        "add_audio",
        {"source": "files/a.mp3", "title": "Theme"},
        "audio-player",
        ['source="files/a.mp3"', 'media-title="Theme"'],
    ),
    (
        "add_image_compare",
        {
            "top_src": "files/t.png",
            "bottom_src": "files/b.png",
            "top_alt": "T",
            "bottom_alt": "B",
            "title": "Compare",
        },
        "image-compare-slider",
        ['top-src="files/t.png"', 'bottom-alt="B"', 'title="Compare"'],
    ),
    (
        "add_image_gallery",
        {
            "images": [
                {"src": "files/a.png", "alt": "A"},
                {"src": "files/b.png", "alt": "B & co", "caption": "Cap"},
            ]
        },
        "image-gallery",
        ['source="files/b.png"', "B &amp; co", 'caption="Cap"'],
    ),
]

TEXT: list[Entry] = [
    (
        "add_collapse",
        {"heading": "More & more", "content_html": "<p>Body.</p>", "expanded": True},
        "a11y-collapse",
        ['heading="More &amp; more"', 'expanded="expanded"', "<p>Body.</p>"],
    ),
    (
        "add_stop_note",
        {
            "title": "Hold up",
            "content_html": "<p>Read this.</p>",
            "url": "https://example.com/more",
            "icon": "stopnoteicons:stop-icon",
        },
        "stop-note",
        ['title="Hold up"', 'icon="stopnoteicons:stop-icon"', '<div slot="message">'],
    ),
    (
        "add_code_sample",
        {"code": 'const a = 1 < 2 && "x";'},
        "code-sample",
        ['type="javascript"', "const a = 1 &lt; 2 &amp;&amp;"],
    ),
    (
        "add_markdown_block",
        {"markdown": "# Hi"},
        "md-block",
        ['markdown="# Hi"'],
    ),
]

LAYOUT: list[Entry] = [
    (
        "add_accent_card",
        {
            "heading": "H & more",
            "subheading": "Sub",
            "content_html": "<p>C</p>",
            "image_src": "files/i.png",
            "image_alt": "IA",
            "accent_color": "red",
            "horizontal": True,
        },
        "accent-card",
        ['accent-color="red"', 'horizontal="horizontal"', '<h3 slot="heading">H &amp; more</h3>'],
    ),
    (
        "add_grid",
        {"layout": "1-1", "columns": ["<p>Left</p>", "<p>Right</p>"]},
        "grid-plate",
        ['layout="1-1"', '<div slot="col-2"><p>Right</p></div>'],
    ),
    (
        "add_page_section",
        {"content_html": "<h2>Section</h2>", "image": "files/bg.png", "full": True, "filter": True},
        "page-section",
        ['image="files/bg.png"', 'full="full"', 'filter="filter"'],
    ),
    (
        "add_placeholder",
        {"kind": "image", "text": "Figure coming soon"},
        "place-holder",
        ['type="image"', 'text="Figure coming soon"'],
    ),
    (
        "add_cta",
        {"label": "Click me", "link": "https://example.com", "icon": "link", "hide_icon": True},
        "simple-cta",
        ['label="Click me"', 'hide-icon="hide-icon"'],
    ),
]

ASSESSMENT: list[Entry] = [
    (
        "add_self_check",
        {
            "title": "Check",
            "question_html": "<p>Q?</p>",
            "answer_html": "<p>A.</p>",
            "accent_color": "primary",
        },
        "self-check",
        ['title="Check"', 'accent-color="primary"', '<div slot="question"><p>Q?</p></div>'],
    ),
    (
        "add_multiple_choice",
        {
            "question": "Which & why?",
            "answers": [
                {"label": "A < B", "correct": True},
                {"label": "C", "correct": False},
            ],
            "single": True,
        },
        "multiple-choice",
        ['question="Which &amp; why?"', 'value="A &lt; B"', 'single-option="single-option"'],
    ),
    (
        "add_true_false",
        {"question": "HAX is great.", "answer": True},
        "true-false-question",
        ['question="HAX is great."', 'value="True"'],
    ),
    (
        "add_short_answer",
        {"question": "Which way is up?", "answers": ["North", "Up"]},
        "short-answer-question",
        ['question="Which way is up?"', 'value="North"'],
    ),
    (
        "add_sorting_question",
        {"question": "Order these", "ordered_items": ["1", "2", "3"]},
        "sorting-question",
        ['question="Order these"', 'value="3"'],
    ),
    (
        "add_matching_question",
        {"question": "Match", "pairs": [["Cow", "Moo"], ["Fox", "PaPaPower"]]},
        "matching-question",
        ['value="Cow"', 'value="PaPaPower"'],
    ),
    (
        "add_fill_in_the_blanks",
        {"question": "Complete", "text_with_blanks": "[hax] is [good~great]"},
        "fill-in-the-blanks",
        ['question="Complete"', 'statement="[hax] is [good~great]"'],
    ),
    (
        "add_mark_the_words",
        {"question": "Select the contractions", "text": "it'll be fun", "correct_words": ["it'll"]},
        "mark-the-words",
        ['question="Select the contractions"', "it'll", 'value="it\'ll"'],
    ),
    (
        "add_tagging_question",
        {
            "question": "What does the fox say?",
            "options": [
                {"label": "DingDing", "correct": True},
                {"label": "Moo", "correct": False},
            ],
        },
        "tagging-question",
        ['question="What does the fox say?"', 'value="DingDing"'],
    ),
    (
        "add_flash_card",
        {"front": "What is strawberry in Spanish?", "back": "fresa", "image": "files/i.jpg"},
        "flash-card",
        ['img-source="files/i.jpg"', '<p slot="front">'],
    ),
]

EDUCATION: list[Entry] = [
    (
        "add_vocab_term",
        {
            "term": "HAX Camp",
            "definition_html": "An event.",
            "links": [{"title": "Site", "href": "https://example.com"}],
        },
        "vocab-term",
        ['term="HAX Camp"', 'information="An event."', "https://example.com"],
    ),
    (
        "add_learning_component",
        {"kind": "objectives", "title": "Objectives", "content_html": "<p>Learn.</p>"},
        "learning-component",
        ['type="objectives"', 'title="Objectives"', "<p>Learn.</p>"],
    ),
    (
        "add_timeline",
        {
            "title": "Course history",
            "events": [
                {"heading": "1855", "details_html": "<p>Charter</p>", "image": "files/c.png"},
                {"heading": "1953", "details_html": "<p>Name</p>"},
            ],
        },
        "lrndesign-timeline",
        ['timeline-title="Course history"', "1855"],
    ),
]

REFERENCE: list[Entry] = [
    (
        "add_styled_quote",
        {
            "quote": "<p>So this is how liberty dies</p>",
            "citation": "Padme",
            "image": "files/p.png",
        },
        "block-quote",
        ['citation="Padme"', "<p>So this is how liberty dies</p>"],
    ),
    (
        "add_citation",
        {
            "title": "Te Futr",
            "source_url": "https://duckduckgo.com",
            "creator": "Joe",
            "date": "2020",
            "license": "by",
        },
        "citation-element",
        ['title="Te Futr"', 'license="by"', 'scope="sibling"'],
    ),
    (
        "add_license",
        {
            "title": "Wonderland",
            "author": "Mad Hatter",
            "source": "https://example.com",
            "more_label": "More",
        },
        "license-element",
        ['license="by-sa"', 'creator="Mad Hatter"', 'more-label="More"'],
    ),
]

EMBED: list[Entry] = [
    (
        "add_wikipedia_query",
        {"search": "Internet", "hide_title": True},
        "wikipedia-query",
        ['search="Internet"', 'hide-title="hide-title"'],
    ),
]

NATIVE: list[Entry] = [
    (
        "add_paragraph",
        {"text_or_html": "Hello <em>world</em> & co"},
        "p",
        ["Hello <em>world</em> &amp; co"],
    ),
    (
        "add_heading",
        {"text": "Section & more", "level": 3},
        "h3",
        ["Section &amp; more"],
    ),
    (
        "add_list",
        {"items": ["One", "Two <em>plus</em>"], "ordered": True},
        "ol",
        ["<li>One</li>", "<li>Two <em>plus</em></li>"],
    ),
    (
        "add_table",
        {"rows": [["H1", "H2"], ["a", "b"]], "header": True},
        "table",
        ["<th>H1</th>", "<td>b</td>"],
    ),
    (
        "add_blockquote",
        {"text": "Quoted & cited", "cite": "https://example.com"},
        "blockquote",
        ['cite="https://example.com"', "Quoted &amp; cited"],
    ),
    ("add_divider", {}, "hr", []),
]

CHUNKS: dict[str, list[Entry]] = {
    "media": MEDIA,
    "text": TEXT,
    "layout": LAYOUT,
    "assessment": ASSESSMENT,
    "education": EDUCATION,
    "reference": REFERENCE,
    "embed": EMBED,
    "native": NATIVE,
}


def test_chunks_cover_every_typed_tool() -> None:
    """All 37 typed tools appear in exactly one chunk (guards the table above)."""
    tools = [entry[0] for entries in CHUNKS.values() for entry in entries]
    assert len(tools) == 37 == len(set(tools))


@pytest.mark.parametrize("chunk", sorted(CHUNKS))
async def test_typed_tools_insert_and_survive_storage(
    mcp: McpTestClient, site: str, chunk: str
) -> None:
    entries = CHUNKS[chunk]
    created = await mcp.call("create_page", title=f"Typed {chunk}", site=site)
    page = str(created["id"])

    # a fresh page carries one empty <p> (live-verified: even an empty save re-seeds
    # it), so every insert lands at baseline + n
    baseline = await mcp.call("get_page_blocks", page=page, site=site)
    assert baseline["count"] == 1
    assert baseline["blocks"][0]["tag"] == "p"
    assert baseline["blocks"][0]["text"] == ""

    stored: list[tuple[str, str, list[str]]] = []
    for position, (tool, args, tag, fragments) in enumerate(entries, start=1):
        result = await mcp.call(tool, page=page, site=site, **args)
        assert result["saved"] is True, tool
        assert result["operation"] == "insert_block", tool
        assert result["block_count"] == position + 1, tool
        affected = result["affected"][0]
        assert affected["tag"] == tag, tool
        assert affected["index"] == position, tool
        for fragment in fragments:
            assert fragment in affected["html"], (tool, fragment)
        stored.append((tag, str(affected["html"]), fragments))

    content = await mcp.call("get_page_content", page=page, site=site)
    body = str(content["html"])
    assert [block["tag"] for block in content["blocks"]] == ["p"] + [tag for tag, _, _ in stored]
    for tag, block_html, fragments in stored:
        # T4.7: every tag survives storage; only the four documented attribute forms
        # are rewritten by saveNode (stored_form encodes them exactly)
        assert stored_form(block_html) in body, tag
        for fragment in fragments:
            assert stored_form(fragment) in body, (tag, fragment)
