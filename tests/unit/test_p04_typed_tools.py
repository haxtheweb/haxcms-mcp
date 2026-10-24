"""Unit tests for the typed block tools (PLAN Phase 4 T4.5, Appendix B).

Every typed tool must produce exactly the stored HTML for its block (golden strings on
the affected block) and honour the shared anchor/occurrence/placement tail; validation
failures (stale Appendix B parameters, bad levels, enum violations, empty inputs) must
reject BEFORE any content HTTP. Each tool runs through the in-memory Client against the
stateful respx fake with the catalog routes offline (bundled entries only); the native
tools run with NO catalog routes at all — native tags never touch the network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError
from lxml import html as lhtml

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ITEMS_RE = r".*/_sites/demo/x/api/v1/items/[^/]+(\?|$)"
CONTENT_RE = r".*/_sites/demo/x/api/v1/content/[^/]+(\?|$)"
BLOCKS_RE = r".*/_sites/demo/x/api/v1/blocks/[a-z0-9-]+(\?|$)"
SCHEMAS_RE = r".*/_sites/demo/x/api/v1/schemas(\?|$)"
CE_RE = r".*/_sites/demo/x/api/v1/custom-elements/[a-z0-9-]+$"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

RECORD: dict[str, Any] = {
    "id": "item-1",
    "title": "Songlines",
    "slug": "songlines",
    "metadata": {"published": True},
}


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"status": 200, "jwt": "jwt-1"},
            headers={"set-cookie": "haxcms_refresh_token=r1; Path=/; HttpOnly"},
        )
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def mock_catalog_offline() -> None:
    """The live merge degrades silently: every catalog route answers 404."""
    offline = httpx.Response(404, json={"status": 404, "data": {"message": "Not found"}})
    respx.get(url__regex=BLOCKS_RE).mock(return_value=offline)
    respx.get(url__regex=SCHEMAS_RE).mock(return_value=offline)
    respx.get(url__regex=CE_RE).mock(return_value=offline)


class FakeSite:
    """Stateful item/content endpoints; counts reads so validate-before-fetch is provable."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.gets = 0
        self.patches: list[dict[str, Any]] = []

    def install(self) -> None:
        def get_item(request: httpx.Request) -> httpx.Response:
            self.gets += 1
            data = dict(RECORD)
            if "include=content" in str(request.url):
                data["content"] = self.body
            return httpx.Response(200, json={"status": 200, "data": data})

        def patch_content(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            self.patches.append(payload)
            body = str(payload["body"])
            marker = "></page-break>"
            # upstream pageBreakParser: the stored content is what follows the envelope
            self.body = body.split(marker, 1)[1] if marker in body else body
            return httpx.Response(200, json={"status": 200, "data": dict(RECORD)})

        respx.get(url__regex=ITEMS_RE).mock(side_effect=get_item)
        respx.patch(url__regex=CONTENT_RE).mock(side_effect=patch_content)

    @property
    def last_body(self) -> str:
        return str(self.patches[-1]["body"])


async def call_typed(
    tool: str,
    args: dict[str, Any],
    fake: FakeSite | None = None,
    body: str = "<p>Seed.</p>",
) -> tuple[Any, FakeSite]:
    """Run one typed tool against the fake site; return (result data, fake)."""
    if fake is None:
        fake = FakeSite(body)
        fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        result = await client.call_tool(tool, {"page": "songlines", **args})
    return result.data, fake


async def call_typed_error(
    tool: str, args: dict[str, Any], fake: FakeSite | None = None
) -> tuple[str, FakeSite]:
    """Run one typed tool expecting a ToolError; return (error message, fake)."""
    if fake is None:
        fake = FakeSite("<p>Seed.</p>")
        fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(tool, {"page": "songlines", **args})
    return str(excinfo.value), fake


# --- media ------------------------------------------------------------------------------------


@respx.mock
async def test_add_image_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, fake = await call_typed(
        "add_image",
        {
            "source": "files/a.png",
            "alt": "A path",
            "caption": "The path",
            "citation": "Photo: me",
            "card": True,
            "box": True,
            "round": True,
            "size": "small",
            "offset": "wide",
            "link": "https://example.com",
        },
    )
    assert data["operation"] == "insert_block"
    assert data["saved"] is True
    assert data["site"] == "demo"
    assert data["page_id"] == "item-1"
    assert data["page_slug"] == "songlines"
    assert data["block_count"] == 2
    assert data["affected"][0]["index"] == 1
    golden = (
        '<media-image source="files/a.png" alt="A path" caption="The path" '
        'citation="Photo: me" card="card" box="box" round="round" size="small" '
        'offset="wide" link="https://example.com"></media-image>'
    )
    assert data["affected"][0]["html"] == golden
    assert fake.body == "<p>Seed.</p>\n" + golden


@respx.mock
async def test_add_image_omits_unset_values() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed("add_image", {"source": "files/a.png", "alt": "A"})
    assert data["affected"][0]["html"] == (
        '<media-image source="files/a.png" alt="A"></media-image>'
    )


@respx.mock
async def test_add_video_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_video",
        {
            "source": "https://youtu.be/x",
            "title": "Lecture",
            "accent_color": "red",
            "start_time": 10,
            "end_time": 90,
            "thumbnail": "files/t.png",
            "hide_transcript": True,
        },
    )
    assert data["affected"][0]["html"] == (
        '<video-player source="https://youtu.be/x" media-title="Lecture" accent-color="red" '
        'start-time="10" end-time="90" thumbnail-src="files/t.png" '
        'hide-transcript="hide-transcript"></video-player>'
    )
    data, _ = await call_typed("add_video", {"source": "https://youtu.be/x"})
    assert data["affected"][0]["html"] == (
        '<video-player source="https://youtu.be/x"></video-player>'
    )


@respx.mock
async def test_add_audio_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed("add_audio", {"source": "files/a.mp3", "title": "Theme"})
    assert data["affected"][0]["html"] == (
        '<audio-player source="files/a.mp3" media-title="Theme"></audio-player>'
    )


@respx.mock
async def test_add_image_compare_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_image_compare",
        {
            "top_src": "files/t.png",
            "bottom_src": "files/b.png",
            "top_alt": "T",
            "bottom_alt": "B",
            "title": "Compare",
        },
    )
    assert data["affected"][0]["html"] == (
        '<image-compare-slider top-src="files/t.png" bottom-src="files/b.png" top-alt="T" '
        'bottom-alt="B" title="Compare"></image-compare-slider>'
    )


@respx.mock
async def test_add_image_gallery_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_image_gallery",
        {
            "images": [
                {"src": "files/a.png", "alt": "A"},
                {"src": "files/b.png", "alt": "B & co", "caption": "Cap"},
            ]
        },
    )
    assert data["affected"][0]["html"] == (
        "<image-gallery>"
        '<media-image source="files/a.png" alt="A"></media-image>'
        '<media-image source="files/b.png" alt="B &amp; co" caption="Cap"></media-image>'
        "</image-gallery>"
    )
    message, fake = await call_typed_error("add_image_gallery", {"images": []})
    assert "[INVALID_ARGUMENT]" in message and "at least one" in message
    assert fake.gets == 0 and fake.patches == []


# --- text -------------------------------------------------------------------------------------


@respx.mock
async def test_add_collapse_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_collapse",
        {"heading": "More & more", "content_html": "<p>Body.</p>", "expanded": True},
    )
    assert data["affected"][0]["html"] == (
        '<a11y-collapse heading="More &amp; more" expanded="expanded"><p>Body.</p></a11y-collapse>'
    )
    data, _ = await call_typed(
        "add_collapse", {"heading": "More & more", "content_html": "<p>Body.</p>"}
    )
    assert data["affected"][0]["html"] == (
        '<a11y-collapse heading="More &amp; more"><p>Body.</p></a11y-collapse>'
    )


@respx.mock
async def test_add_stop_note_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_stop_note",
        {
            "title": "Hold up",
            "content_html": "<p>Read this.</p>",
            "url": "https://example.com/more",
            "icon": "stopnoteicons:stop-icon",
        },
    )
    assert data["affected"][0]["html"] == (
        '<stop-note title="Hold up" url="https://example.com/more" '
        'icon="stopnoteicons:stop-icon">'
        '<div slot="message"><p>Read this.</p></div></stop-note>'
    )


@respx.mock
async def test_add_code_sample_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed("add_code_sample", {"code": 'const a = 1 < 2 && "x";\nconst b = a;'})
    assert data["affected"][0]["html"] == (
        '<code-sample type="javascript" copy-clipboard-button="copy-clipboard-button">'
        '<template preserve-content="preserve-content">'
        'const a = 1 &lt; 2 &amp;&amp; "x";\nconst b = a;</template></code-sample>'
    )


@respx.mock
async def test_add_code_sample_language_enum() -> None:
    mock_auth()
    mock_catalog_offline()
    message, fake = await call_typed_error(
        "add_code_sample", {"code": "x = 1", "language": "python"}
    )
    assert "[INVALID_ARGUMENT]" in message and "invalid type" in message
    assert "allowed values: javascript, html, css, xml, json, yaml, php" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_markdown_block_golden_and_exactly_one_source() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed("add_markdown_block", {"markdown": "# Hi"})
    assert data["affected"][0]["html"] == '<md-block markdown="# Hi"></md-block>'
    fake = FakeSite("<p>Seed.</p>")
    fake.install()
    message, _ = await call_typed_error("add_markdown_block", {}, fake=fake)
    assert "[INVALID_ARGUMENT]" in message and "exactly one" in message
    message, _ = await call_typed_error(
        "add_markdown_block", {"markdown": "# Hi", "source_url": "https://x"}, fake=fake
    )
    assert "exactly one" in message
    assert fake.gets == 0 and fake.patches == []


# --- layout -----------------------------------------------------------------------------------


@respx.mock
async def test_add_accent_card_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
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
    )
    assert data["affected"][0]["html"] == (
        '<accent-card image-src="files/i.png" image-alt="IA" accent-color="red" '
        'horizontal="horizontal"><h3 slot="heading">H &amp; more</h3>'
        '<h4 slot="subheading">Sub</h4><div slot="content"><p>C</p></div></accent-card>'
    )


@respx.mock
async def test_add_grid_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_grid", {"layout": "1-1", "columns": ["<p>Left</p>", "<p>Right</p>"]}
    )
    assert data["affected"][0]["html"] == (
        '<grid-plate layout="1-1"><div slot="col-1"><p>Left</p></div>'
        '<div slot="col-2"><p>Right</p></div></grid-plate>'
    )


@respx.mock
async def test_add_grid_rejects_empty_columns_and_bad_layout() -> None:
    mock_auth()
    mock_catalog_offline()
    fake = FakeSite("<p>Seed.</p>")
    fake.install()
    message, _ = await call_typed_error("add_grid", {"layout": "1-1", "columns": []}, fake=fake)
    assert "[INVALID_ARGUMENT]" in message and "columns needs" in message
    message, _ = await call_typed_error(
        "add_grid", {"layout": "5", "columns": ["<p>A</p>"]}, fake=fake
    )
    assert "invalid layout" in message
    assert "allowed values: 1, 1-1" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_page_section_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_page_section",
        {
            "content_html": "<h2>Section</h2>",
            "image": "files/bg.png",
            "full": True,
            "filter": True,
        },
    )
    assert data["affected"][0]["html"] == (
        '<page-section image="files/bg.png" full="full" filter="filter">'
        "<h2>Section</h2></page-section>"
    )


@respx.mock
async def test_add_page_section_accent_color_rejected_with_known_attributes() -> None:
    """Appendix B gives page-section an accent_color; 26.8.1's element has none — the
    catalog rejects it and lists what does exist (bg, preset, ...)."""
    mock_auth()
    mock_catalog_offline()
    message, fake = await call_typed_error(
        "add_page_section", {"content_html": "<p>x</p>", "accent_color": "red"}
    )
    assert "[INVALID_ARGUMENT]" in message
    assert "unknown attributes for page-section: accent-color" in message
    assert "bg" in message and "preset" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_placeholder_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed("add_placeholder", {"text": "Figure coming soon"})
    assert data["affected"][0]["html"] == (
        '<place-holder type="image" text="Figure coming soon"></place-holder>'
    )


@respx.mock
async def test_add_placeholder_code_kind_rejected() -> None:
    """Appendix B lists a `code` kind; 26.8.1's enum dropped it — validation rejects."""
    mock_auth()
    mock_catalog_offline()
    message, fake = await call_typed_error("add_placeholder", {"kind": "code"})
    assert "[INVALID_ARGUMENT]" in message and "invalid type" in message
    assert "allowed values: text, document, audio, video, image, math" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_cta_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_cta",
        {"label": "Click me", "link": "https://example.com", "icon": "link", "hide_icon": True},
    )
    assert data["affected"][0]["html"] == (
        '<simple-cta label="Click me" link="https://example.com" icon="link" '
        'hide-icon="hide-icon"></simple-cta>'
    )


# --- assessment --------------------------------------------------------------------------------


@respx.mock
async def test_add_self_check_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_self_check",
        {
            "title": "Check",
            "question_html": "<p>Q?</p>",
            "answer_html": "<p>A.</p>",
            "image": "files/i.png",
            "alt": "IA",
            "accent_color": "primary",
        },
    )
    assert data["affected"][0]["html"] == (
        '<self-check title="Check" image="files/i.png" alt="IA" accent-color="primary">'
        '<div slot="question"><p>Q?</p></div><p>A.</p></self-check>'
    )


@respx.mock
async def test_add_multiple_choice_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_multiple_choice",
        {
            "question": "Which & why?",
            "answers": [
                {"label": "A < B", "correct": True},
                {"label": "C", "correct": False},
            ],
            "single": True,
        },
    )
    assert data["affected"][0]["html"] == (
        '<multiple-choice question="Which &amp; why?" single-option="single-option">'
        '<input type="checkbox" value="A &lt; B" correct>\n'
        '<input type="checkbox" value="C"></multiple-choice>'
    )


@respx.mock
async def test_assessment_title_parameter_rejected_with_known_attributes() -> None:
    """Appendix B gives the eight assessment tools a title param; 26.8.1's elements have
    no title attribute — the PLAN signatures are immutable, so the catalog rejects with
    an educational error listing what does exist."""
    mock_auth()
    mock_catalog_offline()
    message, fake = await call_typed_error(
        "add_multiple_choice",
        {"question": "Q?", "answers": [{"label": "A", "correct": True}], "title": "Quiz"},
    )
    assert "[INVALID_ARGUMENT]" in message
    assert "unknown attributes for multiple-choice: title" in message
    assert "question" in message  # the hint lists the known attributes
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_true_false_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    fake = FakeSite("<p>Seed.</p>")
    fake.install()
    data, _ = await call_typed(
        "add_true_false", {"question": "HAX is great.", "answer": True}, fake=fake
    )
    assert data["affected"][0]["html"] == (
        '<true-false-question question="HAX is great.">'
        '<input type="checkbox" value="True" correct>\n'
        '<input type="checkbox" value="False"></true-false-question>'
    )
    data, _ = await call_typed(
        "add_true_false", {"question": "HAX is great.", "answer": False}, fake=fake
    )
    assert data["affected"][0]["html"] == (
        '<true-false-question question="HAX is great.">'
        '<input type="checkbox" value="True">\n'
        '<input type="checkbox" value="False" correct></true-false-question>'
    )


@respx.mock
async def test_add_short_answer_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_short_answer", {"question": "Which way is up?", "answers": ["North", "Up"]}
    )
    assert data["affected"][0]["html"] == (
        '<short-answer-question question="Which way is up?">'
        '<input type="checkbox" value="North" correct>\n'
        '<input type="checkbox" value="Up" correct></short-answer-question>'
    )


@respx.mock
async def test_add_sorting_question_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_sorting_question", {"question": "Order these", "ordered_items": ["1", "2", "3"]}
    )
    assert data["affected"][0]["html"] == (
        '<sorting-question question="Order these">'
        '<input value="1">\n<input value="2">\n<input value="3"></sorting-question>'
    )


@respx.mock
async def test_add_matching_question_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_matching_question",
        {"question": "Match", "pairs": [["Cow", "Moo"], ["Fox", "PaPaPower"]]},
    )
    assert data["affected"][0]["html"] == (
        '<matching-question question="Match">'
        '<input value="Cow" correct>\n<input value="Moo">\n'
        '<input value="Fox" correct>\n<input value="PaPaPower"></matching-question>'
    )
    message, fake = await call_typed_error(
        "add_matching_question", {"question": "Match", "pairs": [["only-one"]]}
    )
    assert "[INVALID_ARGUMENT]" in message and "prompt, match" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_fill_in_the_blanks_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_fill_in_the_blanks",
        {"question": "Complete", "text_with_blanks": "[hax] is [good~great]"},
    )
    assert data["affected"][0]["html"] == (
        '<fill-in-the-blanks question="Complete" statement="[hax] is [good~great]">'
        "</fill-in-the-blanks>"
    )


@respx.mock
async def test_add_mark_the_words_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_mark_the_words",
        {
            "question": "Select the contractions",
            "text": "it'll be fun",
            "correct_words": ["it'll"],
        },
    )
    assert data["affected"][0]["html"] == (
        '<mark-the-words question="Select the contractions" statement="it\'ll be fun">'
        '<input value="it\'ll" correct></mark-the-words>'
    )


@respx.mock
async def test_add_tagging_question_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_tagging_question",
        {
            "question": "What does the fox say?",
            "options": [
                {"label": "DingDing", "correct": True},
                {"label": "Moo", "correct": False},
            ],
        },
    )
    assert data["affected"][0]["html"] == (
        '<tagging-question question="What does the fox say?">'
        '<input value="DingDing" correct>\n<input value="Moo"></tagging-question>'
    )


@respx.mock
async def test_add_flash_card_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_flash_card",
        {"front": "What is strawberry in Spanish?", "back": "fresa", "image": "files/i.jpg"},
    )
    assert data["affected"][0]["html"] == (
        '<flash-card img-source="files/i.jpg">'
        '<p slot="front">What is strawberry in Spanish?</p>'
        '<p slot="back">fresa</p></flash-card>'
    )


# --- education / reference / embed ---------------------------------------------------------------


@respx.mock
async def test_add_vocab_term_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_vocab_term",
        {
            "term": "HAX Camp",
            "definition_html": "An event.",
            "links": [{"title": "Site", "href": "https://example.com"}],
        },
    )
    golden = data["affected"][0]["html"]
    assert golden.startswith('<vocab-term term="HAX Camp" information="An event."')
    # the links JSON attribute round-trips (lxml single-quotes attrs containing ")
    element = lhtml.fragment_fromstring(golden)
    assert json.loads(element.get("links") or "") == [
        {"title": "Site", "href": "https://example.com"}
    ]
    # without links the attribute is omitted entirely
    data, _ = await call_typed(
        "add_vocab_term", {"term": "HAX", "definition_html": "Authoring system."}
    )
    assert data["affected"][0]["html"] == (
        '<vocab-term term="HAX" information="Authoring system."></vocab-term>'
    )


@respx.mock
async def test_add_learning_component_golden_and_enum() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_learning_component",
        {"kind": "objectives", "title": "Objectives", "content_html": "<p>Learn.</p>"},
    )
    assert data["affected"][0]["html"] == (
        '<learning-component type="objectives" title="Objectives">'
        "<p>Learn.</p></learning-component>"
    )
    message, fake = await call_typed_error(
        "add_learning_component", {"kind": "dance", "title": "x", "content_html": "<p>y</p>"}
    )
    assert "[INVALID_ARGUMENT]" in message and "invalid type" in message
    assert "objectives" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_timeline_events_attribute_round_trip() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_timeline",
        {
            "title": "Course history",
            "events": [
                {"heading": "1855", "details_html": "<p>Charter</p>", "image": "files/c.png"},
                {"heading": "1953", "details_html": "<p>Name</p>"},
            ],
        },
    )
    element = lhtml.fragment_fromstring(data["affected"][0]["html"])
    assert element.tag == "lrndesign-timeline"
    assert element.get("timeline-title") == "Course history"
    assert json.loads(element.get("events") or "") == [
        {"heading": "1855", "details": "<p>Charter</p>", "imagesrc": "files/c.png"},
        {"heading": "1953", "details": "<p>Name</p>"},
    ]


@respx.mock
async def test_add_styled_quote_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_styled_quote",
        {
            "quote": "<p>So this is how liberty dies</p>",
            "citation": "Padme",
            "image": "files/p.png",
        },
    )
    assert data["affected"][0]["html"] == (
        '<block-quote citation="Padme" image="files/p.png">'
        "<p>So this is how liberty dies</p></block-quote>"
    )


@respx.mock
async def test_add_citation_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_citation",
        {
            "title": "Te Futr",
            "source_url": "https://duckduckgo.com",
            "creator": "Joe",
            "date": "2020",
            "license": "by",
        },
    )
    assert data["affected"][0]["html"] == (
        '<citation-element title="Te Futr" source="https://duckduckgo.com" creator="Joe" '
        'date="2020" license="by" scope="sibling"></citation-element>'
    )
    message, fake = await call_typed_error(
        "add_citation", {"title": "T", "source_url": "https://x", "license": "proprietary"}
    )
    assert "[INVALID_ARGUMENT]" in message and "invalid license" in message
    assert "by-sa" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_license_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed(
        "add_license",
        {
            "title": "Wonderland",
            "author": "Mad Hatter",
            "source": "https://example.com",
            "more_label": "More",
        },
    )
    assert data["affected"][0]["html"] == (
        '<license-element license="by-sa" title="Wonderland" creator="Mad Hatter" '
        'source="https://example.com" more-label="More"></license-element>'
    )


@respx.mock
async def test_add_wikipedia_query_golden() -> None:
    mock_auth()
    mock_catalog_offline()
    data, _ = await call_typed("add_wikipedia_query", {"search": "Internet", "hide_title": True})
    assert data["affected"][0]["html"] == (
        '<wikipedia-query search="Internet" hide-title="hide-title"></wikipedia-query>'
    )


# --- native blocks (no catalog HTTP at all) ------------------------------------------------------


@respx.mock
async def test_add_paragraph_golden_and_anchor_tail() -> None:
    mock_auth()
    data, _ = await call_typed("add_paragraph", {"text_or_html": "Hello <em>world</em> & co"})
    assert data["affected"][0]["html"] == "<p>Hello <em>world</em> &amp; co</p>"
    # the shared tail: placement=before against a text anchor
    data, fake = await call_typed(
        "add_paragraph", {"text_or_html": "Inter", "anchor": "Seed", "placement": "before"}
    )
    assert data["affected"][0]["index"] == 0
    assert fake.body == "<p>Inter</p>\n<p>Seed.</p>"


@respx.mock
async def test_add_heading_golden_and_level_guard() -> None:
    mock_auth()
    data, _ = await call_typed("add_heading", {"text": "Designing <3"})
    assert data["affected"][0]["html"] == "<h2>Designing &lt;3</h2>"
    data, _ = await call_typed("add_heading", {"text": "Top", "level": 1})
    assert data["affected"][0]["html"] == "<h1>Top</h1>"
    fake = FakeSite("<p>Seed.</p>")
    fake.install()
    for bad in (0, 7):
        message, _ = await call_typed_error("add_heading", {"text": "x", "level": bad}, fake=fake)
        assert "[INVALID_ARGUMENT]" in message and "level must be 1-6" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_list_golden() -> None:
    mock_auth()
    data, _ = await call_typed("add_list", {"items": ["One", "Two <em>up</em>"], "ordered": True})
    assert data["affected"][0]["html"] == "<ol><li>One</li><li>Two <em>up</em></li></ol>"
    data, _ = await call_typed("add_list", {"items": ["One"]})
    assert data["affected"][0]["html"] == "<ul><li>One</li></ul>"
    message, fake = await call_typed_error("add_list", {"items": []})
    assert "[INVALID_ARGUMENT]" in message and "at least one" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_table_golden() -> None:
    mock_auth()
    data, _ = await call_typed(
        "add_table", {"rows": [["Name", "Role"], ["Sam", "Guide"]], "header": True}
    )
    assert data["affected"][0]["html"] == (
        "<table><thead><tr><th>Name</th><th>Role</th></tr></thead>"
        "<tbody><tr><td>Sam</td><td>Guide</td></tr></tbody></table>"
    )
    data, _ = await call_typed("add_table", {"rows": [["a", "b"], ["c", "d"]], "header": False})
    assert data["affected"][0]["html"] == (
        "<table><tbody><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></tbody></table>"
    )
    message, fake = await call_typed_error("add_table", {"rows": []})
    assert "[INVALID_ARGUMENT]" in message and "at least one row" in message
    assert fake.gets == 0 and fake.patches == []


@respx.mock
async def test_add_blockquote_and_divider_golden() -> None:
    mock_auth()
    data, _ = await call_typed("add_blockquote", {"text": "Quoted & true", "cite": "https://x"})
    assert data["affected"][0]["html"] == (
        '<blockquote cite="https://x">Quoted &amp; true</blockquote>'
    )
    data, _ = await call_typed("add_divider", {})
    assert data["affected"][0]["html"] == "<hr>"


# --- shared catalog cache ------------------------------------------------------------------------


@respx.mock
async def test_content_and_typed_tools_share_one_catalog_cache() -> None:
    """server.py builds ONE CatalogService for both groups: the live-merge probe for
    media-image runs once, however many tools ask for it."""
    mock_auth()
    offline = httpx.Response(404, json={"status": 404, "data": {"message": "Not found"}})
    blocks_route = respx.get(url__regex=BLOCKS_RE).mock(return_value=offline)
    respx.get(url__regex=SCHEMAS_RE).mock(return_value=offline)
    respx.get(url__regex=CE_RE).mock(return_value=offline)
    fake = FakeSite("<p>Seed.</p>")
    fake.install()
    mcp = build_server(make_settings(default_site="demo"))
    async with Client(mcp) as client:
        await client.call_tool("get_block_schema", {"tag": "media-image"})
        await client.call_tool(
            "add_image", {"page": "songlines", "source": "files/a.png", "alt": "A"}
        )
        await client.call_tool(
            "add_image", {"page": "songlines", "source": "files/b.png", "alt": "B"}
        )
    assert blocks_route.call_count == 1
    assert fake.body.count("<media-image") == 2
