#!/usr/bin/env python3
"""Generate the bundled block catalog (PLAN Phase 4 T4.4, dev aid).

Writes one `src/haxcms_mcp/services/catalog/bundled/<tag>.json` per Core Block (PLAN
Appendix B) in the catalog entry shape (§2.3): `{tag, title, description, category,
attributes[{name, type, required, description, enum?}], slots[{name, description}],
example_html, agent_notes}`.

Attribute/slot/example data comes from the haxcms-nodejs public build's
`<pkg>/lib/<tag>.haxProperties.json` when it exists (18 of the 31 Appendix B tags).
The 13 inline-only elements (media-image, video-player, grid-plate, ... — API-REF §8)
have no JSON file; their entries come from the CURATED table below, verified against the
minified element sources in the build (a read-only Explore pass). CURATED and OVERRIDES
fields WIN over extracted ones — Appendix B: corrections land in the bundled catalog,
never in PLAN.

Usage:
    uv run python scripts/extract_hax_properties.py [--build DIR] [--only TAG ...]

The default build dir is `../haxcms-nodejs/src/public/build/es6/node_modules/@haxtheweb`
relative to the repo root. The haxcms-nodejs checkout is only ever READ.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from haxcms_mcp.services.catalog.hax_properties import entry_from_hax_properties  # noqa: E402

BUNDLED_DIR = ROOT / "src" / "haxcms_mcp" / "services" / "catalog" / "bundled"
DEFAULT_BUILD = (
    ROOT.parent
    / "haxcms-nodejs"
    / "src"
    / "public"
    / "build"
    / "es6"
    / "node_modules"
    / "@haxtheweb"
)

FIELD_ORDER = (
    "tag",
    "title",
    "description",
    "category",
    "attributes",
    "slots",
    "example_html",
    "agent_notes",
)
_TEXT_FIELDS = {"tag", "title", "description", "category", "example_html", "agent_notes"}

# list_blocks categories (PLAN T4.4: text|media|layout|assessment|education|reference|embed)
CATEGORIES: dict[str, str] = {
    "media-image": "media",
    "video-player": "media",
    "audio-player": "media",
    "image-compare-slider": "media",
    "image-gallery": "media",
    "accent-card": "layout",
    "grid-plate": "layout",
    "page-section": "layout",
    "place-holder": "layout",
    "simple-cta": "layout",
    "a11y-collapse": "text",
    "stop-note": "text",
    "code-sample": "text",
    "md-block": "text",
    "self-check": "assessment",
    "multiple-choice": "assessment",
    "true-false-question": "assessment",
    "short-answer-question": "assessment",
    "sorting-question": "assessment",
    "matching-question": "assessment",
    "fill-in-the-blanks": "assessment",
    "mark-the-words": "assessment",
    "tagging-question": "assessment",
    "flash-card": "assessment",
    "vocab-term": "education",
    "lrndesign-timeline": "education",
    "learning-component": "education",
    "citation-element": "reference",
    "license-element": "reference",
    "block-quote": "reference",
    "wikipedia-query": "embed",
}

CC_LICENSES = ["by", "by-sa", "by-nd", "by-nc", "by-nc-sa", "by-nc-nd"]


def _attr(
    name: str,
    type: str = "string",
    required: bool = False,
    description: str = "",
    enum: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "type": type,
        "required": required,
        "description": description,
    }
    if enum:
        out["enum"] = enum
    return out


def _slot(name: str, description: str = "") -> dict[str, str]:
    return {"name": name, "description": description}


FLAG = "boolean flag: emit name=name (presence is truth)"

# Full entries for the 13 inline-only tags (no .haxProperties.json in the build).
# Attributes mirror the elements' inline haxProperties (configure + advanced groups,
# verified from the minified sources), plus the SimpleColors-inherited accent-color/dark
# where the element extends that base. developer-group entries are omitted, matching the
# build-JSON extraction (which reads configure/advanced only).
CURATED: dict[str, dict[str, Any]] = {
    "media-image": {
        "title": "Enhanced Image",
        "description": "A way of presenting images with various enhancements.",
        "attributes": [
            _attr(
                "source",
                required=True,
                description="image file (files/<name> uploaded via add_file, or a full URL)",
            ),
            _attr("alt", required=True, description="alt text describing the image"),
            _attr("link", description="wrap the image in a link to this URL/file"),
            _attr("card", "boolean", description="card treatment; " + FLAG),
            _attr("box", "boolean", description="box treatment; " + FLAG),
            _attr(
                "offset",
                description="pull the image out of the text column",
                enum=["none", "wide", "narrow"],
            ),
            _attr("citation", description="attribution / credit line"),
            _attr("caption", description="figure caption shown under the image"),
            _attr("figure-label-title", description="label title shown above the caption"),
            _attr("figure-label-description", description="label description text"),
            _attr("thumbnail", description="separate thumbnail image URL"),
            _attr("round", "boolean", description="round the image corners; " + FLAG),
            _attr("disable-zoom", "boolean", description="turn off click-to-zoom; " + FLAG),
            _attr(
                "size",
                description="display width (CSS honors only small; anything else "
                "renders at the default wide)",
                enum=["small", "wide"],
            ),
            _attr("accent-color", description="inherited design-system accent color"),
            _attr("dark", "boolean", description="inherited dark-mode toggle; " + FLAG),
        ],
        "example_html": (
            '<media-image source="https://dummyimage.com/300x200/000/fff"'
            ' alt="Placeholder image" card="card"'
            ' citation="This is my citation."></media-image>'
        ),
        "agent_notes": (
            "Upload the image first (add_file) and use the returned site-relative url as "
            "source. Boolean attributes take their own name as the value (card=card)."
        ),
    },
    "video-player": {
        "title": "Video",
        "description": "Accessible video playback across multiple sources.",
        "attributes": [
            _attr(
                "source",
                required=True,
                description="YouTube/Vimeo/Kaltura/mp4 URL or uploaded file",
            ),
            _attr("media-title", description="accessible title for the player"),
            _attr("thumbnail-src", description="custom poster/thumbnail image URL"),
            _attr(
                "tracks", description="JSON array of caption tracks: [{src, label, srclang, kind}]"
            ),
            _attr("start-time", "number", description="playback start offset in seconds"),
            _attr("end-time", "number", description="playback end offset in seconds"),
            _attr("learning-mode", "boolean", description=FLAG),
            _attr("hide-youtube-link", "boolean", description=FLAG),
            _attr("linkable", "boolean", description="deep-linkable timestamps; " + FLAG),
            _attr("hide-timestamps", "boolean", description=FLAG),
            _attr("hide-transcript", "boolean", description=FLAG),
            _attr("audio-description-source", description="audio-description media URL"),
            _attr(
                "accent-color",
                description="accent color (SimpleColors palette); deprecated developer "
                "setting in haxProperties but still rendered by the element",
            ),
            _attr("dark", "boolean", description="inherited dark-mode toggle; " + FLAG),
        ],
        "example_html": (
            '<video-player source="https://www.youtube.com/watch?v=LrS7dqokTLE"'
            ' data-width="75" data-margin="center"></video-player>'
        ),
        "agent_notes": (
            "source accepts provider watch URLs as well as direct media files; "
            "accessible title goes in media-title."
        ),
    },
    "audio-player": {
        "title": "Audio",
        "description": "This can present video in a highly accessible manner regardless of source.",
        "attributes": [
            _attr(
                "source",
                required=True,
                description="audio/video URL or uploaded file (files/<name>)",
            ),
            _attr("media-title", description="accessible title for the player"),
            _attr("accent-color", description="design-system accent color"),
            _attr("track", description="closed-captions file URL"),
            _attr("thumbnail-src", description="poster image URL"),
            _attr("learning-mode", "boolean", description=FLAG),
            _attr("hide-youtube-link", "boolean", description=FLAG),
            _attr("linkable", "boolean", description=FLAG),
            _attr("start-time", "number", description="inherited: playback start offset"),
            _attr("end-time", "number", description="inherited: playback end offset"),
            _attr("hide-transcript", "boolean", description="inherited; " + FLAG),
            _attr("hide-timestamps", "boolean", description="inherited; " + FLAG),
            _attr("dark", "boolean", description="inherited dark-mode toggle; " + FLAG),
        ],
        "example_html": (
            '<audio-player source="https://archive.org/download/tvtunes_4710/Jonny%20Quest.mp3"'
            ' media-title="Jonny Quest Theme"></audio-player>'
        ),
        "agent_notes": "extends video-player with audioOnly forced; same attribute family.",
    },
    "accent-card": {
        "title": "Card",
        "description": "A card with optional accent styling.",
        "attributes": [
            _attr("image-src", description="card image URL (files/... or full URL)"),
            _attr("image-alt", description="alt text for the card image"),
            _attr(
                "image-align",
                description="horizontal image position",
                enum=["left", "center", "right"],
            ),
            _attr(
                "image-valign",
                description="vertical image position",
                enum=["top", "center", "bottom"],
            ),
            _attr("accent-color", description="design-system accent color"),
            _attr("dark", "boolean", description=FLAG),
            _attr("horizontal", "boolean", description="image beside content; " + FLAG),
            _attr("accent-heading", "boolean", description="accent the heading area; " + FLAG),
            _attr("accent-background", "boolean", description="accent the background; " + FLAG),
            _attr("no-border", "boolean", description=FLAG),
            _attr("flat", "boolean", description="no shadow; " + FLAG),
        ],
        "slots": [
            _slot("heading", "card heading (wrapper h3-h6)"),
            _slot("subheading", "line under the heading (wrapper div/p/h4-h6)"),
            _slot("content", "card body (wrapper p)"),
            _slot("footer", "card footer (wrapper div/p)"),
            _slot("corner", "corner decoration (advanced; wrapper div/p)"),
        ],
        "example_html": (
            '<accent-card accent-color="red" accent-heading="accent-heading"'
            ' horizontal="horizontal" image-src="https://placehold.co/500x300">'
            '<h3 slot="heading">Accent Card</h3>'
            '<h4 slot="subheading">A card with optional accent stylings.</h4>'
            '<div slot="content"><p>This card is highly customizable to contain any '
            "content you'd like</p></div>"
            "</accent-card>"
        ),
        "agent_notes": "",
    },
    "grid-plate": {
        "title": "Column layout",
        "description": "Layout material in simple columns",
        "attributes": [
            _attr(
                "layout",
                required=True,
                description="column template (name = relative widths)",
                enum=[
                    "1",
                    "1-1",
                    "2-1",
                    "1-2",
                    "3-1",
                    "1-3",
                    "1-1-1",
                    "2-1-1",
                    "1-2-1",
                    "1-1-2",
                    "1-1-1-1",
                ],
            ),
            _attr(
                "disable-responsive",
                "boolean",
                description="keep columns side-by-side on small screens; " + FLAG,
            ),
            _attr(
                "item-padding",
                "number",
                description="padding inside each column, px (0-120, step 4)",
            ),
            _attr(
                "item-margin", "number", description="margin around each column, px (0-120, step 4)"
            ),
        ],
        "slots": [
            _slot("col-1", "first column"),
            _slot("col-2", "second column"),
            _slot("col-3", "third column"),
            _slot("col-4", "fourth column"),
            _slot("col-5", "fifth column"),
            _slot("col-6", "sixth column"),
        ],
        "example_html": (
            '<grid-plate layout="1-1" item-margin="16" item-padding="16">'
            '<p slot="col-1">Column one content</p>'
            '<p slot="col-2">Column two content</p>'
            "</grid-plate>"
        ),
        "agent_notes": (
            "layout lists relative column widths (1-1 = two equal columns); every child "
            "must carry slot=col-N matching the layout's column count. Legacy numeric "
            "aliases (12, 8, 6/6, 4/4/4, 3/3/3/3) are accepted at runtime."
        ),
    },
    "place-holder": {
        "title": "Placeholder",
        "description": (
            "A place holder that can be converted into the media type that's been selected"
        ),
        "attributes": [
            _attr(
                "type",
                description="kind of media it stands in for (default text)",
                enum=["text", "document", "audio", "video", "image", "math"],
            ),
            _attr("text", description="message shown inside the placeholder"),
        ],
        "example_html": '<place-holder type="image" text="Figure coming soon"></place-holder>',
        "agent_notes": (
            "the icon is auto-derived from type; save wipes slot and derived attributes."
        ),
    },
    "simple-cta": {
        "title": "Call to action",
        "description": "A simple button with a link to take action.",
        "attributes": [
            _attr("label", required=True, description="button text"),
            _attr("link", required=True, description="destination URL"),
            _attr("hide-icon", "boolean", description=FLAG),
            _attr(
                "icon",
                description="simple-icons name as iconset:icon (default icons:chevron-right)",
            ),
        ],
        "example_html": (
            '<simple-cta label="Click to learn more" link="https://haxtheweb.org/"></simple-cta>'
        ),
        "agent_notes": "",
    },
    "code-sample": {
        "title": "Code sample",
        "description": "A sample of code highlighted in the page",
        "attributes": [
            _attr(
                "type",
                description="language of the code (default html)",
                enum=["javascript", "html", "css", "xml", "json", "yaml", "php"],
            ),
            _attr("copy-clipboard-button", "boolean", description="show a copy button; " + FLAG),
            _attr("highlight-start", "number", description="first line number to highlight"),
            _attr("highlight-end", "number", description="last line number to highlight"),
        ],
        "example_html": (
            '<code-sample type="javascript" copy-clipboard-button="copy-clipboard-button">'
            '<template preserve-content="preserve-content">const great = "example";\n'
            "const great2 = great;</template></code-sample>"
        ),
        "agent_notes": (
            "the code MUST live inside <template preserve-content=...> and be "
            "HTML-escaped (<, >, &); the save-time sanitizer keeps template content."
        ),
    },
    "citation-element": {
        "title": "Citation",
        "description": "Citation element with three presentation modes.",
        "attributes": [
            _attr("title", description="title of the cited work"),
            _attr("source", description="URL of the cited work"),
            _attr("date", description="date accessed, as shown"),
            _attr(
                "scope",
                description="what the citation applies to (default sibling)",
                enum=["sibling", "parent"],
            ),
            _attr("license", description="CC license key", enum=CC_LICENSES),
            _attr(
                "creator", description="author / creator name (attribute is creator, not author)"
            ),
            _attr("typeof", description="schema.org type (default oer:ReferencedMaterial)"),
        ],
        "example_html": (
            '<citation-element creator="Cool Joe" license="by" title="Te Futr Da Biz"'
            ' source="https://duckduckgo.com/" date="03/07/2020"></citation-element>'
        ),
        "agent_notes": (
            "license-name/license-link/license-image are auto-derived from the license "
            "key; an incoming author value is mapped to creator."
        ),
    },
    "license-element": {
        "title": "License",
        "description": "Provide a license for your work.",
        "attributes": [
            _attr("title", description="work title shown in the notice"),
            _attr("source", description="URL of the work"),
            _attr("license", description="CC license key", enum=CC_LICENSES),
            _attr("creator", description="author name (attribute is creator, not author)"),
            _attr("more-link", description="URL of a licensing details page"),
            _attr(
                "more-label",
                description="label for the more-link (default 'on the licensing details page')",
            ),
        ],
        "example_html": (
            '<license-element title="Wonderland" creator="Mad Hatter"'
            ' source="https://haxtheweb.org/" license="by"></license-element>'
        ),
        "agent_notes": (
            "license-name/license-image/license-link auto-derived; has-more computed "
            "from more-link."
        ),
    },
    "lrndesign-timeline": {
        "title": "Timeline",
        "description": "A timeline of events with images and text",
        "attributes": [
            _attr("timeline-title", description="heading shown above the timeline"),
            _attr("accent-color", description="design-system accent color"),
            _attr("dark", "boolean", description=FLAG),
            _attr(
                "events",
                description=(
                    "JSON array of {heading, details, imagesrc, imagealt} — primary way to "
                    "supply events; when empty, light-DOM <section> children are used instead"
                ),
            ),
        ],
        "slots": [_slot("default", "timeline description shown under the title")],
        "example_html": (
            '<lrndesign-timeline timeline-title="Course history">'
            "<section><h2>1855 - Charter</h2><p>Charter signed and in effect.</p></section>"
            "<section><h2>1953 - Rename</h2><p>The current name became official.</p></section>"
            "</lrndesign-timeline>"
        ),
        "agent_notes": (
            "Prefer the events attribute (JSON array); the <section>-children fallback "
            "takes the first h1-h6 as heading and remaining children as details. "
            "timeline-size (xs/sm/md/lg/xl) exists but is unreliable in 26.8.1."
        ),
    },
    "md-block": {
        "title": "Markdown",
        "description": "A block of markdown content directly or remote loaded",
        "attributes": [
            _attr("markdown", description="raw markdown string"),
            _attr("source", description="remote .md file URL (takes priority over markdown)"),
            _attr("accent-color", description="inherited design-system accent color"),
            _attr("dark", "boolean", description="inherited dark-mode toggle; " + FLAG),
        ],
        "slots": [
            _slot("default", "markdown source text (moved into the markdown property on load)")
        ],
        "example_html": (
            '<md-block markdown="- The first bulleted item in a long list.."></md-block>'
        ),
        "agent_notes": "tag body content is treated as markdown, not rendered HTML.",
    },
    "learning-component": {
        "title": "Learning Component",
        "description": (
            "A card for instructors to communicate pedagogy and instructional strategies."
        ),
        "attributes": [
            _attr(
                "type",
                description="component kind; auto-derives title, icon and accent-color",
                enum=[
                    "objectives",
                    "connection",
                    "knowledge",
                    "strategy",
                    "discuss",
                    "listen",
                    "make",
                    "observe",
                    "present",
                    "read",
                    "reflect",
                    "research",
                    "watch",
                    "write",
                    "content",
                    "assessment",
                    "quiz",
                    "submission",
                    "lesson",
                    "module",
                    "task",
                    "activity",
                    "project",
                    "practice",
                    "unit",
                ],
            ),
            _attr("subtitle", description="line under the component heading"),
            _attr("url", description="linked resource URL"),
            _attr("title", description="overrides the type-based title"),
            _attr("icon", description="overrides the type-based icon (iconify name)"),
            _attr("accent-color", description="overrides the type-based color"),
            _attr("dark", "boolean", description="inherited dark-mode toggle; " + FLAG),
        ],
        "slots": [_slot("default", "component body content")],
        "example_html": (
            '<learning-component type="objectives" subtitle="Unit 1">'
            "<p>By the end of this lesson, you should be able to...</p>"
            "</learning-component>"
        ),
        "agent_notes": (
            "changing type overwrites title/icon on update — set explicit overrides "
            "only together with (or after) type, or omit type."
        ),
    },
}

# corrections/additions for entries extracted from build JSON (agent_notes etc.);
# `extra_attributes` appends to the extracted list instead of replacing it
OVERRIDES: dict[str, dict[str, Any]] = {
    "flash-card": {
        "extra_attributes": [
            _attr("speak", "boolean", description="text-to-speech: speak the card; " + FLAG),
            _attr("listen", "boolean", description="text-to-speech: listen mode; " + FLAG),
        ],
        "agent_notes": (
            "front and back go in children with slot=front / slot=back "
            "(<p slot='front'>...</p><p slot='back'>...</p>)."
        ),
    },
    "true-false-question": {
        "agent_notes": (
            "the correct answer is a child <input type=checkbox value=True|False> "
            "carrying a bare `correct` attribute; the editor-only _tfanswer property "
            "is stripped on save (saveOptions.unsetAttributes)."
        ),
    },
    "self-check": {
        "agent_notes": (
            "the question goes in a child with slot=question (<p slot=question>...</p>); "
            "the answer is the default slot content."
        ),
    },
    "multiple-choice": {
        "agent_notes": (
            "answers are child inputs: <input type=checkbox value=...> with a bare "
            "`correct` attribute on the right ones; single-option switches to one-answer "
            "mode; randomize shuffles; check-label/hide-buttons adjust the UI."
        ),
    },
    "stop-note": {
        # icon is a real reflected attribute (CSS :host([icon=...]) + rendered simple-icon)
        # but not a haxProperties settings entry — the gizmo icon is unrelated
        "extra_attributes": [
            _attr(
                "icon",
                description="icon override, e.g. stopnoteicons:stop-icon; derived from "
                "status when omitted",
            ),
        ],
        "agent_notes": "the message body goes in a child with slot=message.",
    },
    "a11y-collapse": {
        # expanded IS a configure entry but saveOptions.unsetAttributes strips it from
        # editor saves; direct content writes persist it and the element honors it
        "extra_attributes": [
            _attr(
                "expanded",
                "boolean",
                description="expand by default; the HAX editor strips it from its own "
                "saves, direct content writes persist it; " + FLAG,
            ),
        ],
        "agent_notes": (
            "the trigger is a child with slot=heading; the revealed body is the default "
            "slot content."
        ),
    },
    "image-compare-slider": {
        # title is rendered as an <h2> above the slider (source-verified) but is not a
        # haxProperties settings entry
        "extra_attributes": [
            _attr("title", description="optional heading rendered above the slider"),
        ],
    },
}


def build_entry(tag: str, build_dir: Path) -> tuple[dict[str, Any], str]:
    """`(entry, origin)`; origin is 'build' (JSON found) or 'curated'."""
    extracted: dict[str, Any] | None = None
    matches = sorted(build_dir.glob(f"*/lib/{tag}.haxProperties.json"))
    if matches:
        props = json.loads(matches[0].read_text(encoding="utf-8"))
        extracted = entry_from_hax_properties(tag, props)
    entry: dict[str, Any] = {}
    origin = "curated"
    if extracted is not None:
        origin = "build"
        entry.update({k: v for k, v in extracted.items() if v not in ("", None, [], {})})
    for key, value in CURATED.get(tag, {}).items():
        if value not in ("", None, [], {}):
            entry[key] = value  # curated wins: source-verified corrections
    overrides = dict(OVERRIDES.get(tag, {}))
    extra = overrides.pop("extra_attributes", None)
    if extra:
        entry["attributes"] = [*entry.get("attributes", []), *extra]
    entry.update(overrides)
    entry["tag"] = tag
    entry["category"] = CATEGORIES[tag]
    full: dict[str, Any] = {}
    for field in FIELD_ORDER:
        full[field] = entry.get(field, "" if field in _TEXT_FIELDS else [])
    return full, origin


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the bundled block catalog.")
    parser.add_argument(
        "--build",
        type=Path,
        default=DEFAULT_BUILD,
        help="haxcms-nodejs public build @haxtheweb directory",
    )
    parser.add_argument("--only", nargs="*", default=None, help="limit to these tags")
    args = parser.parse_args()
    tags = sorted(args.only) if args.only else sorted(CATEGORIES)
    unknown = [tag for tag in tags if tag not in CATEGORIES]
    if unknown:
        print(f"tags without a category: {', '.join(unknown)}", file=sys.stderr)
        return 1
    BUNDLED_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"build": 0, "curated": 0}
    for tag in tags:
        entry, origin = build_entry(tag, args.build)
        path = BUNDLED_DIR / f"{tag}.json"
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        counts[origin] += 1
        print(f"wrote {path.name} ({origin})")
    print(f"{len(tags)} entries: {counts['build']} from build JSON, {counts['curated']} curated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
