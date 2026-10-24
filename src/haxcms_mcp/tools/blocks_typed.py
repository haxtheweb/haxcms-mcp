"""Typed Core Block tools: one add_<block> per PLAN Appendix B row (Phase 4 T4.5).

Each tool mirrors its Appendix B signature (plus the shared page / anchor / occurrence /
placement / site tail), builds the block's attributes and inner HTML, validates them
against the Block Catalog and inserts through the same service path as the generic
add_block — one GET + one PATCH content, one git revision, idempotent=False because
every call appends a NEW block. `page` is an id or slug, as everywhere else.

Conventions:
- plain-text parameters (headings, questions, labels) are HTML-escaped; parameters
  named *_html — and list/table cells — are trusted markup passed through as-is.
- HAX flag booleans render as name="name" through build_block_html; None/False values
  are omitted from the block and skip validation.
- Appendix B parameters that 26.8.1's elements do not actually have (the assessment
  `title`s, page-section `accent_color`) pass through to catalog validation, which
  rejects them with the known-attribute list — the catalog is the arbiter, the PLAN
  signatures are immutable.
"""

from __future__ import annotations

from html import escape
from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services.catalog.service import CatalogService
from haxcms_mcp.services.content import blocks as blocks_service
from haxcms_mcp.services.content.blocks import build_block_html
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def _text(value: Any) -> str:
    """Escape a plain-text parameter for embedding into an HTML string."""
    return escape(str(value), quote=True)


def _input(value: str, *, correct: bool = False, kind: str | None = "checkbox") -> str:
    """One assessment `<input>` child; `correct` renders as the bare flag attribute."""
    parts = ["<input"]
    if kind is not None:
        parts.append(f' type="{kind}"')
    parts.append(f' value="{_text(value)}"')
    if correct:
        parts.append(" correct")
    parts.append(">")
    return "".join(parts)


def _guard(condition: bool, message: str) -> None:
    """Raise INVALID_ARGUMENT unless `condition` — shared input sanity for typed tools."""
    if not condition:
        raise HaxcmsMcpError(ErrorCode.INVALID_ARGUMENT, message)


def register_typed_block_tools(
    mcp: FastMCP, settings: Settings, client: HaxcmsClient, catalog: CatalogService
) -> None:
    """Register the 37 typed block tools: 31 Appendix B Core Blocks + 6 native (T4.5).

    `catalog` is the server-wide shared CatalogService (one live-merge cache), built in
    server.py and also used by the generic content tools.
    """

    async def _insert(
        page: str,
        tag: str,
        attributes: dict[str, Any],
        inner_html: str,
        anchor: str | None,
        occurrence: str | int | None,
        placement: str,
        site: str | None,
    ) -> dict[str, Any]:
        """Shared tail of every typed tool: validate, build the HTML, insert, dump."""
        name = resolve_site(site, settings.default_site)
        await catalog.validate(tag, attributes, site=name)
        html = build_block_html(tag, attributes, inner_html)
        result = await blocks_service.insert_block(
            client,
            name,
            page,
            html,
            anchor=anchor,
            occurrence=occurrence,
            placement=placement,
        )
        return dump_model(result)

    # --- media --------------------------------------------------------------------------------

    @mcp.tool(annotations=tool_annotations("Add image", idempotent=False))
    async def add_image(
        page: str,
        source: str,
        alt: str,
        caption: str | None = None,
        citation: str | None = None,
        card: bool = False,
        box: bool = False,
        round: bool = False,
        size: str | None = None,
        offset: str | None = None,
        link: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a media-image block: the tutorial image, with optional caption/citation.

        `source` is a site-relative path (`files/...`) or an absolute URL; `alt` is
        required by the element. Flags: `card` (card treatment), `box` (drop shadow),
        `round` (circular crop). `size`: small|wide; `offset`: none|wide|narrow (margin
        bleed); `link` wraps the image in an anchor. Anchor/placement work as in
        add_block.
        """
        attributes = {
            "source": source,
            "alt": alt,
            "caption": caption,
            "citation": citation,
            "card": card,
            "box": box,
            "round": round,
            "size": size,
            "offset": offset,
            "link": link,
        }
        return await _insert(
            page, "media-image", attributes, "", anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add video", idempotent=False))
    async def add_video(
        page: str,
        source: str,
        title: str | None = None,
        accent_color: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        thumbnail: str | None = None,
        hide_transcript: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a video-player block: YouTube/Vimeo/Kaltura watch URLs or direct mp4/webm.

        `title` becomes the accessible media-title; `start_time`/`end_time` are seconds;
        `thumbnail` overrides the preview image; `accent_color` is a SimpleColors palette
        name. Anchor/placement work as in add_block.
        """
        attributes = {
            "source": source,
            "media-title": title,
            "accent-color": accent_color,
            "start-time": start_time,
            "end-time": end_time,
            "thumbnail-src": thumbnail,
            "hide-transcript": hide_transcript,
        }
        return await _insert(
            page, "video-player", attributes, "", anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add audio", idempotent=False))
    async def add_audio(
        page: str,
        source: str,
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add an audio-player block (mp3 or any hosted audio URL); `title` becomes the
        accessible media-title. Anchor/placement work as in add_block.
        """
        attributes = {"source": source, "media-title": title}
        return await _insert(
            page, "audio-player", attributes, "", anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add image compare slider", idempotent=False))
    async def add_image_compare(
        page: str,
        top_src: str,
        bottom_src: str,
        top_alt: str,
        bottom_alt: str,
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add an image-compare-slider block: drag-handle before/after comparison of two
        images; `title` renders as a heading above the slider. Anchor/placement work as
        in add_block.
        """
        attributes = {
            "top-src": top_src,
            "bottom-src": bottom_src,
            "top-alt": top_alt,
            "bottom-alt": bottom_alt,
            "title": title,
        }
        return await _insert(
            page, "image-compare-slider", attributes, "", anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add image gallery", idempotent=False))
    async def add_image_gallery(
        page: str,
        images: list[dict[str, Any]],
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add an image-gallery block: a lightbox gallery of media-image children.

        `images` is a list of `{src, alt, caption}` dicts (caption optional); each entry
        becomes one `<media-image>` child — the gallery root takes no attributes here.
        Anchor/placement work as in add_block.
        """
        _guard(bool(images), "images needs at least one {src, alt, caption} entry")
        cards: list[str] = []
        for image in images:
            attrs = f' source="{_text(image.get("src", ""))}" alt="{_text(image.get("alt", ""))}"'
            caption = image.get("caption")
            if caption:
                attrs += f' caption="{_text(caption)}"'
            cards.append(f"<media-image{attrs}></media-image>")
        inner = "".join(cards)
        return await _insert(page, "image-gallery", {}, inner, anchor, occurrence, placement, site)

    # --- text ---------------------------------------------------------------------------------

    @mcp.tool(annotations=tool_annotations("Add collapse", idempotent=False))
    async def add_collapse(
        page: str,
        heading: str,
        content_html: str,
        expanded: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add an a11y-collapse block: `heading` is the always-visible toggle text,
        `content_html` the collapsible body (trusted HTML).

        `expanded=True` opens it by default — the HAX editor strips that flag from its
        own saves, but content written through this server keeps it. Anchor/placement
        work as in add_block.
        """
        attributes = {"heading": heading, "expanded": expanded}
        return await _insert(
            page, "a11y-collapse", attributes, content_html, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add stop note", idempotent=False))
    async def add_stop_note(
        page: str,
        title: str,
        content_html: str,
        icon: str | None = None,
        url: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a stop-note block: the red attention banner for must-read warnings.

        `content_html` is the trusted-HTML message body (slot=message); `icon` overrides
        the status-derived icon (e.g. `stopnoteicons:stop-icon`); `url` adds a learn-more
        link. For softer callouts prefer accent-card or self-check. Anchor/placement work
        as in add_block.
        """
        attributes = {"title": title, "url": url, "icon": icon}
        inner = f'<div slot="message">{content_html}</div>'
        return await _insert(
            page, "stop-note", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add code sample", idempotent=False))
    async def add_code_sample(
        page: str,
        code: str,
        language: str = "javascript",
        copy_button: bool = True,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a code-sample block with syntax highlighting and a copy button.

        Pass `code` verbatim — it is escaped automatically and stored inside
        `<template preserve-content>` so the sanitizer keeps whitespace and entities.
        `language`: javascript|html|css|xml|json|yaml|php. Anchor/placement work as in
        add_block.
        """
        attributes = {"type": language, "copy-clipboard-button": copy_button}
        inner = '<template preserve-content="preserve-content">' + _text(code) + "</template>"
        return await _insert(
            page, "code-sample", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add markdown block", idempotent=False))
    async def add_markdown_block(
        page: str,
        markdown: str | None = None,
        source_url: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add an md-block block: Markdown rendered by the element — pass inline
        `markdown` OR a `source_url` to fetch from, exactly one. Anchor/placement work as
        in add_block.
        """
        _guard(
            bool(markdown) != bool(source_url),
            "pass exactly one of markdown / source_url",
        )
        attributes = {"markdown": markdown, "source": source_url}
        return await _insert(page, "md-block", attributes, "", anchor, occurrence, placement, site)

    # --- layout -------------------------------------------------------------------------------

    @mcp.tool(annotations=tool_annotations("Add accent card", idempotent=False))
    async def add_accent_card(
        page: str,
        heading: str,
        content_html: str,
        subheading: str | None = None,
        image_src: str | None = None,
        image_alt: str | None = None,
        accent_color: str | None = None,
        horizontal: bool = False,
        flat: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add an accent-card block: a colored callout card with slotted heading, optional
        subheading and trusted-HTML body (`content_html`).

        `horizontal` lays image and content side by side; `flat` removes the shadow;
        `accent_color` is a SimpleColors palette name. Heading/subheading are escaped
        plain text. Anchor/placement work as in add_block.
        """
        attributes = {
            "image-src": image_src,
            "image-alt": image_alt,
            "accent-color": accent_color,
            "horizontal": horizontal,
            "flat": flat,
        }
        parts = [f'<h3 slot="heading">{_text(heading)}</h3>']
        if subheading:
            parts.append(f'<h4 slot="subheading">{_text(subheading)}</h4>')
        parts.append(f'<div slot="content">{content_html}</div>')
        inner = "".join(parts)
        return await _insert(
            page, "accent-card", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add grid", idempotent=False))
    async def add_grid(
        page: str,
        layout: str,
        columns: list[str],
        disable_responsive: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a grid-plate block: `layout` is a column template — 1, 1-1, 2-1, 1-2, 3-1,
        1-3, 1-1-1, 2-1-1, 1-2-1, 1-1-2, 1-1-1-1 — and `columns` carries one trusted-HTML
        string per column, slotted into col-1...col-N.

        `disable_responsive` keeps the layout fixed on small screens. Anchor/placement
        work as in add_block.
        """
        _guard(bool(columns), "columns needs one HTML string per grid column")
        attributes = {"layout": layout, "disable-responsive": disable_responsive}
        slots = (
            f'<div slot="col-{index}">{column}</div>' for index, column in enumerate(columns, 1)
        )
        inner = "".join(slots)
        return await _insert(
            page, "grid-plate", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add page section", idempotent=False))
    async def add_page_section(
        page: str,
        content_html: str,
        accent_color: str | None = None,
        image: str | None = None,
        full: bool = False,
        filter: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a page-section block: a full-bleed themed section wrapping `content_html`
        (trusted HTML).

        `image` sets a background image; `full` makes the section full-height; `filter`
        dims the background behind content. NOTE: 26.8.1's page-section has no
        accent-color attribute — passing `accent_color` fails validation; style through
        `image`, the site theme, or the preset/bg attributes (see get_block_schema).
        Anchor/placement work as in add_block.
        """
        attributes = {
            "accent-color": accent_color,
            "image": image,
            "full": full,
            "filter": filter,
        }
        return await _insert(
            page, "page-section", attributes, content_html, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add placeholder", idempotent=False))
    async def add_placeholder(
        page: str,
        kind: str = "image",
        text: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a place-holder block: the dashed stand-in the tutorial drops for media to
        come.

        `kind`: text|document|audio|video|image|math (26.8.1's enum — Appendix B's old
        `code` value no longer exists and fails validation); `text` is the label shown
        inside. Anchor/placement work as in add_block.
        """
        attributes = {"type": kind, "text": text}
        return await _insert(
            page, "place-holder", attributes, "", anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add call to action", idempotent=False))
    async def add_cta(
        page: str,
        label: str,
        link: str,
        icon: str | None = None,
        hide_icon: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a simple-cta block: a call-to-action button; `icon` is an iron-icon name
        (e.g. `link`), `hide_icon` drops it. Anchor/placement work as in add_block.
        """
        attributes = {"label": label, "link": link, "icon": icon, "hide-icon": hide_icon}
        return await _insert(
            page, "simple-cta", attributes, "", anchor, occurrence, placement, site
        )

    # --- assessment ---------------------------------------------------------------------------

    @mcp.tool(annotations=tool_annotations("Add self check", idempotent=False))
    async def add_self_check(
        page: str,
        title: str,
        question_html: str,
        answer_html: str,
        image: str | None = None,
        alt: str | None = None,
        accent_color: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a self-check block: a question whose answer reveals on click — self-
        assessment only, nothing is graded or recorded.

        `question_html` goes into the question slot, `answer_html` into the default slot
        (both trusted HTML); `accent_color`: primary|accent|success|warning|error|info.
        Anchor/placement work as in add_block.
        """
        attributes = {
            "title": title,
            "image": image,
            "alt": alt,
            "accent-color": accent_color,
        }
        inner = f'<div slot="question">{question_html}</div>{answer_html}'
        return await _insert(
            page, "self-check", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add multiple choice", idempotent=False))
    async def add_multiple_choice(
        page: str,
        question: str,
        answers: list[dict[str, Any]],
        title: str | None = None,
        randomize: bool = False,
        single: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a multiple-choice block: a self-graded checkbox question.

        `answers` is a list of `{label, correct}` dicts — each entry with a truthy
        `correct` is a right answer. `single=True` switches to one-answer mode
        (single-option flag); `randomize` shuffles at display time. The element has NO
        title attribute in 26.8.1 — passing one fails validation with the known list.
        Anchor/placement work as in add_block.
        """
        attributes = {
            "question": question,
            "title": title,
            "randomize": randomize,
            "single-option": single,
        }
        inner = "\n".join(
            _input(str(answer.get("label", "")), correct=bool(answer.get("correct")))
            for answer in answers
        )
        return await _insert(
            page, "multiple-choice", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add true/false question", idempotent=False))
    async def add_true_false(
        page: str,
        question: str,
        answer: bool,
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a true-false-question block; `answer` is the correct choice — it renders
        two checkbox inputs (True/False) with the right one flagged `correct`. No title
        attribute exists in 26.8.1. Anchor/placement work as in add_block.
        """
        attributes = {"question": question, "title": title}
        inner = "\n".join(
            [
                _input("True", correct=bool(answer)),
                _input("False", correct=not bool(answer)),
            ]
        )
        return await _insert(
            page, "true-false-question", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add short answer question", idempotent=False))
    async def add_short_answer(
        page: str,
        question: str,
        answers: list[str],
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a short-answer-question block; `answers` lists every accepted free-text
        answer (all flagged correct, matched case-sensitively). No title attribute in
        26.8.1. Anchor/placement work as in add_block.
        """
        attributes = {"question": question, "title": title}
        inner = "\n".join(_input(item, correct=True) for item in answers)
        return await _insert(
            page, "short-answer-question", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add sorting question", idempotent=False))
    async def add_sorting_question(
        page: str,
        question: str,
        ordered_items: list[str],
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a sorting-question block; `ordered_items` is the list in its CORRECT order
        — the element shuffles them at display time. No title attribute in 26.8.1.
        Anchor/placement work as in add_block.
        """
        attributes = {"question": question, "title": title}
        inner = "\n".join(_input(item, kind=None) for item in ordered_items)
        return await _insert(
            page, "sorting-question", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add matching question", idempotent=False))
    async def add_matching_question(
        page: str,
        question: str,
        pairs: list[list[str]],
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a matching-question block; `pairs` is a list of two-item lists
        `[prompt, match]` — prompts are flagged correct, matches form the shuffle pool.
        No title attribute in 26.8.1. Anchor/placement work as in add_block.
        """
        for pair in pairs:
            _guard(len(pair) == 2, f"each matching pair needs [prompt, match], got {pair!r}")
        attributes = {"question": question, "title": title}
        rows: list[str] = []
        for prompt, match in pairs:
            rows.append(_input(prompt, correct=True, kind=None))
            rows.append(_input(match, kind=None))
        inner = "\n".join(rows)
        return await _insert(
            page, "matching-question", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add fill in the blanks", idempotent=False))
    async def add_fill_in_the_blanks(
        page: str,
        question: str,
        text_with_blanks: str,
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a fill-in-the-blanks block; `text_with_blanks` uses the element grammar —
        `[answer]` per blank, `[answer1~answer2]` for accepted alternatives. No title
        attribute in 26.8.1. Anchor/placement work as in add_block.
        """
        attributes = {"question": question, "statement": text_with_blanks, "title": title}
        return await _insert(
            page, "fill-in-the-blanks", attributes, "", anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add mark the words", idempotent=False))
    async def add_mark_the_words(
        page: str,
        question: str,
        text: str,
        correct_words: list[str],
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a mark-the-words block: `text` is the statement (plain text) and
        `correct_words` lists the words that must be selected — each renders as a flagged
        input the element matches against the statement. No title attribute in 26.8.1.
        Anchor/placement work as in add_block.
        """
        attributes = {"question": question, "statement": text, "title": title}
        inner = "\n".join(_input(word, correct=True, kind=None) for word in correct_words)
        return await _insert(
            page, "mark-the-words", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add tagging question", idempotent=False))
    async def add_tagging_question(
        page: str,
        question: str,
        options: list[dict[str, Any]],
        title: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a tagging-question block: `options` is a list of `{label, correct}` dicts —
        correct labels are the answer key, all labels render as the tag pool. No title
        attribute in 26.8.1. Anchor/placement work as in add_block.
        """
        attributes = {"question": question, "title": title}
        inner = "\n".join(
            _input(str(option.get("label", "")), correct=bool(option.get("correct")), kind=None)
            for option in options
        )
        return await _insert(
            page, "tagging-question", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add flash card", idempotent=False))
    async def add_flash_card(
        page: str,
        front: str,
        back: str,
        image: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a flash-card block: click (or space) flips between `front` and `back`
        (inline HTML allowed); `image` sets the card's img-source for visual cards.
        Anchor/placement work as in add_block.
        """
        attributes = {"img-source": image}
        inner = f'<p slot="front">{front}</p><p slot="back">{back}</p>'
        return await _insert(
            page, "flash-card", attributes, inner, anchor, occurrence, placement, site
        )

    # --- education ----------------------------------------------------------------------------

    @mcp.tool(annotations=tool_annotations("Add vocab term", idempotent=False))
    async def add_vocab_term(
        page: str,
        term: str,
        definition_html: str,
        links: list[dict[str, Any]] | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a vocab-term block: an inline popover definition for `term`.

        `definition_html` lands in the element's information attribute (markup OK);
        `links` is an optional list of `{title, href}` dicts serialized as the element's
        JSON attribute. PLAN spells the default `[]`; None means the same thing and keeps
        the linter's mutable-default rule. Anchor/placement work as in add_block.
        """
        attributes = {"term": term, "information": definition_html, "links": links or None}
        return await _insert(
            page, "vocab-term", attributes, "", anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add learning component", idempotent=False))
    async def add_learning_component(
        page: str,
        kind: str,
        title: str,
        content_html: str,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a learning-component block: a UDL-aligned wrapper tagging `content_html`
        (trusted HTML) with a learning purpose.

        `kind` is one of the element's type values — objectives, connection, knowledge,
        strategy, discuss, listen, make, observe, present, read, reflect, research,
        watch, write, content, assessment, quiz, submission, lesson, module, task,
        activity, project, practice, unit (get_block_schema lists them all). Set `title`
        at creation: the element overwrites title/icon when its type changes later.
        Anchor/placement work as in add_block.
        """
        attributes = {"type": kind, "title": title}
        inner = content_html
        return await _insert(
            page, "learning-component", attributes, inner, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add timeline", idempotent=False))
    async def add_timeline(
        page: str,
        title: str,
        events: list[dict[str, Any]],
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add an lrndesign-timeline block: a vertical timeline.

        `events` is a list of `{heading, details_html, image}` dicts, serialized to the
        element's JSON events attribute (as heading/details/imagesrc) — the element
        renders from the attribute, not from children. Anchor/placement work as in
        add_block.
        """
        events_attr: list[dict[str, Any]] = []
        for event in events:
            row: dict[str, Any] = {
                "heading": event.get("heading", ""),
                "details": event.get("details_html", ""),
            }
            if event.get("image"):
                row["imagesrc"] = event["image"]
            events_attr.append(row)
        attributes = {"timeline-title": title, "events": events_attr}
        return await _insert(
            page, "lrndesign-timeline", attributes, "", anchor, occurrence, placement, site
        )

    # --- reference ----------------------------------------------------------------------------

    @mcp.tool(annotations=tool_annotations("Add styled quote", idempotent=False))
    async def add_styled_quote(
        page: str,
        quote: str,
        citation: str | None = None,
        image: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a block-quote block: the STYLED HAX pull-quote (distinct from the native
        add_blockquote) — `quote` is the quote text/HTML, `citation` its source, `image`
        an optional speaker portrait. Anchor/placement work as in add_block.
        """
        attributes = {"citation": citation, "image": image}
        return await _insert(
            page, "block-quote", attributes, quote, anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add citation", idempotent=False))
    async def add_citation(
        page: str,
        title: str,
        source_url: str,
        creator: str | None = None,
        date: str | None = None,
        license: str | None = None,
        scope: str = "sibling",
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a citation-element block: a rendered citation with schema.org markup.

        `license` is a Creative Commons key (by, by-sa, by-nd, by-nc, by-nc-sa,
        by-nc-nd); `scope` is sibling|parent (how the citation attaches to surrounding
        content). Anchor/placement work as in add_block.
        """
        attributes = {
            "title": title,
            "source": source_url,
            "creator": creator,
            "date": date,
            "license": license,
            "scope": scope,
        }
        return await _insert(
            page, "citation-element", attributes, "", anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add license", idempotent=False))
    async def add_license(
        page: str,
        license: str = "by-sa",
        title: str | None = None,
        author: str | None = None,
        source: str | None = None,
        more_label: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a license-element block: a Creative Commons badge.

        `license`: by|by-sa|by-nd|by-nc|by-nc-sa|by-nc-nd; `author` renders as the
        element's creator attribute; `more_label` customizes the derived link text.
        Anchor/placement work as in add_block.
        """
        attributes = {
            "license": license,
            "title": title,
            "creator": author,
            "source": source,
            "more-label": more_label,
        }
        return await _insert(
            page, "license-element", attributes, "", anchor, occurrence, placement, site
        )

    # --- embed --------------------------------------------------------------------------------

    @mcp.tool(annotations=tool_annotations("Add Wikipedia query", idempotent=False))
    async def add_wikipedia_query(
        page: str,
        search: str,
        hide_title: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a wikipedia-query block: a live Wikipedia result panel for `search`.
        Anchor/placement work as in add_block.
        """
        attributes = {"search": search, "hide-title": hide_title}
        return await _insert(
            page, "wikipedia-query", attributes, "", anchor, occurrence, placement, site
        )

    # --- native HTML blocks ---------------------------------------------------------------------

    @mcp.tool(annotations=tool_annotations("Add paragraph", idempotent=False))
    async def add_paragraph(
        page: str,
        text_or_html: str,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a native <p> paragraph; `text_or_html` may carry inline markup (<em>,
        <strong>, <a>, ...) — it is parsed as HTML, not escaped. Anchor/placement work as
        in add_block.
        """
        return await _insert(page, "p", {}, text_or_html, anchor, occurrence, placement, site)

    @mcp.tool(annotations=tool_annotations("Add heading", idempotent=False))
    async def add_heading(
        page: str,
        text: str,
        level: int = 2,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a native heading <h1>-<h6>; `level` defaults to 2 (the tutorial's H2).
        `text` is escaped plain text — for headings containing links use add_block or
        replace_block. Anchor/placement work as in add_block.
        """
        _guard(1 <= level <= 6, f"level must be 1-6, got {level!r}")
        return await _insert(
            page, f"h{level}", {}, _text(text), anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add list", idempotent=False))
    async def add_list(
        page: str,
        items: list[str],
        ordered: bool = False,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a native <ul> — or <ol> with `ordered=True`; `items` are inline-HTML
        strings, one per <li>. Anchor/placement work as in add_block.
        """
        _guard(bool(items), "items needs at least one list item")
        inner = "".join(f"<li>{item}</li>" for item in items)
        tag = "ol" if ordered else "ul"
        return await _insert(page, tag, {}, inner, anchor, occurrence, placement, site)

    @mcp.tool(annotations=tool_annotations("Add table", idempotent=False))
    async def add_table(
        page: str,
        rows: list[list[str]],
        header: bool = True,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a native <table>; `rows` are lists of cell inline-HTML strings (keep rows
        equal length). With `header=True` the first row renders as <th> headings inside
        <thead>, the rest as <td> inside <tbody>. Anchor/placement work as in add_block.
        """
        _guard(bool(rows), "rows needs at least one row")
        parts: list[str] = []
        body_rows = rows
        if header:
            head = "".join(f"<th>{cell}</th>" for cell in rows[0])
            parts.append(f"<thead><tr>{head}</tr></thead>")
            body_rows = rows[1:]
        if body_rows:
            body = "".join(
                "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in body_rows
            )
            parts.append(f"<tbody>{body}</tbody>")
        inner = "".join(parts)
        return await _insert(page, "table", {}, inner, anchor, occurrence, placement, site)

    @mcp.tool(annotations=tool_annotations("Add blockquote", idempotent=False))
    async def add_blockquote(
        page: str,
        text: str,
        cite: str | None = None,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a native <blockquote>; `text` is escaped plain text and `cite` a source
        URL. For the styled HAX pull-quote use add_styled_quote. Anchor/placement work as
        in add_block.
        """
        attributes = {"cite": cite}
        return await _insert(
            page, "blockquote", attributes, _text(text), anchor, occurrence, placement, site
        )

    @mcp.tool(annotations=tool_annotations("Add divider", idempotent=False))
    async def add_divider(
        page: str,
        anchor: str | None = None,
        occurrence: str | int | None = None,
        placement: str = "append",
        site: str | None = None,
    ) -> dict[str, Any]:
        """Add a native <hr> horizontal rule: a visual section divider. Anchor/placement
        work as in add_block.
        """
        return await _insert(page, "hr", {}, "", anchor, occurrence, placement, site)
