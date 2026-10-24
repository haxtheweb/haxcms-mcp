"""The four MCP Prompts (PLAN Phase 9 T9.1).

Prompts are pure text — no network, no state. They brief the Operator's agent on the
proven tool sequences: `hax_author` is the generic authoring discipline (saves, anchors,
block discovery, accessibility, the reserved `x/` route); the three journey prompts mirror
the Appendix D tutorial, the course scaffold, and the Phase 7 import-and-polish flow.
Every tool name mentioned here is checked against the live registry by
`tests/unit/test_p09_prompts.py` — a prompt must never reference a tool that does not
exist.
"""

from __future__ import annotations

from fastmcp import FastMCP

_DISCIPLINE = """\
SAVE DISCIPLINE — HAXcms has no autosave, but on this server every content tool saves for
you: one call is one save and one git revision. There is no separate save step. Make each
call deliberate; inspect history with `list_page_revisions` and undo with
`restore_page_revision` (it rewrites the page — confirm with the user first)."""

_ANCHORS = """\
ANCHOR RULES — insertion tools take `placement`:
- append / prepend: page level, NO anchor (append is the default and keeps order).
- after / before: REQUIRE an `anchor` — a short text snippet identifying the reference
  block (its visible text, or a distinctive attribute value). When several blocks match,
  `occurrence` picks among them (1-based index, or "last").
Run `get_page_blocks` first and copy anchors from the actual block text; a stale anchor
fails the call instead of guessing."""

_A11Y = """\
ACCESSIBILITY DUTIES — every image gets `alt` (required), and should get `caption` and
`citation`; every video and audio gets a descriptive `title`. Never leave alt text empty
or generic ("image", "photo") when the brief describes the media."""

_X_ROUTE = """\
RESERVED ROUTE — under every site, the `x/` URL segment belongs to the HAXcms API itself
(site data, files, revisions). Never create pages or slugs beneath it and never treat an
`x/` URL as content."""

_ARTIFACTS = """\
ARTIFACTS — export and binary converter tools write files into the Output Directory on
the MCP SERVER host and return {path, bytes, mimetype}; they never return file bytes or a
URL. Quote the returned path to the user. PDF rendering needs Chrome on the HAXcms
server; without it those calls fail as UNSUPPORTED and suggest html/docx/epub instead."""


def register_prompts(mcp: FastMCP) -> None:
    """Register the four Phase 9 prompts on the FastMCP app."""

    @mcp.prompt
    def hax_author() -> str:
        """Authoring discipline for working with HAXcms sites through this server."""
        return f"""\
You are a HAXcms authoring agent. You build and edit websites (usually courses) on a
self-hosted HAXcms instance through the tools and resources of this MCP server. Work like
a careful instructional designer: structure first, content second, media last, verify
always.

{_DISCIPLINE}

DISCOVERING BLOCKS — pages are sequences of blocks (native HTML elements and HAX custom
elements). Before using an unfamiliar element:
- `list_blocks` shows the live Block Catalog (every tag the instance can render);
- `get_block_schema` returns one tag's attributes, slots and defaults;
- the resources haxcms://catalog/blocks and haxcms://catalog/blocks/{{tag}} expose the same
  catalog for reading.
Prefer the typed `add_paragraph` / `add_heading` / `add_image` / `add_video` / ... tools
for Core Blocks — they validate arguments and know the attribute names; fall back to the
generic `add_block` for anything else, and edit with `update_block`, `set_block_text`,
`replace_block`, `move_block` or `remove_block`.

{_ANCHORS}

{_A11Y}

{_X_ROUTE}

SITES — every site-scoped tool takes an optional `site` argument that falls back to the
configured Default Site. With more than one site in play (`list_sites`), pass `site`
explicitly on every call. Machine names are lowercase letters, digits, dashes and
underscores; a name with spaces or capitals fails with a hint — `create_site` rejects it
before anything is written.

VERIFY — after a build step, read the result back: `get_outline` for structure,
`get_page_blocks` for the block sequence, `get_page_content` for raw HTML, and the
resource haxcms://sites/{{site}}/pages/<slug> for the stored page. Trust what you read
back, not what you meant to write.

SHARE — to hand a finished site over, use `export_site` (zip archive, markdown dump,
skeleton template), `download_site_zip`, or `save_site_as_template` to keep it on the
server for reuse via `create_site_from_skeleton`.

{_ARTIFACTS}"""

    @mcp.prompt
    def build_page_from_brief(
        site: str, page_title: str, brief: str, media: list[str] | None = None
    ) -> str:
        """Turn a written brief (plus optional media list) into one finished page."""
        media = media or []
        media_lines = "\n".join(f"  {index}. {item}" for index, item in enumerate(media, 1))
        media_section = (
            f"\nMEDIA (use in order, matching each item to the brief):\n{media_lines}\n"
            "Local paths go through `add_image_from_file` (it uploads and embeds in one\n"
            "call); remote image URLs go through `add_image`; video/audio URLs go through\n"
            "`add_video` / `add_audio`.\n"
            if media
            else ""
        )
        return f"""\
Build the page "{page_title}" on the site "{site}" from this brief:

{brief}
{media_section}
Follow the tutorial sequence — structure first, then media, then verify:

1. `create_page` (title="{page_title}", site="{site}") — note the returned id and slug.
2. If the brief implies a description or a specific slug, set them now with
   `update_page_details`.
3. Lay down the prose: one `add_paragraph` per paragraph, in order (the default append
   placement keeps sequence). Inline markup inside the text is parsed as HTML.
4. Add section headings with `add_heading` (level 2 by default). To place a heading above
   an existing paragraph, anchor on that paragraph's text with placement "before" — or
   follow the tutorial trick: `add_paragraph` after the anchor, then `replace_block` to
   turn it into the heading.
5. Place the media where the brief calls for it, anchoring on the neighbouring text
   (placement "after"/"before"). {_A11Y}
6. External links: `add_link` (anchor on the sentence the link belongs to, with its
   `text` and `url`; set the new-tab flag for external destinations).
7. VERIFY with `get_page_blocks`: the block sequence must match the brief — count the
   paragraphs, check heading levels and media order. Fix drift with `update_block`
   (attributes), `set_block_text` (text) or `move_block` (order), then re-verify.
8. Read the stored page back through haxcms://sites/{site}/pages/<slug> and summarize
   what was built.

{_DISCIPLINE}

{_ANCHORS}"""

    @mcp.prompt
    def scaffold_course_from_outline(
        site_name: str, outline_text: str, theme: str = "clean-one"
    ) -> str:
        """Scaffold a whole course site from a plain-text outline."""
        return f"""\
Scaffold the course site "{site_name}" (theme "{theme}") from this outline:

{outline_text}

1. PARSE the outline into a tree first: indentation (or markdown heading levels) marks
   nesting; reading order marks sequence. Top-level entries become root pages.
2. CHECK for a ready-made journey: `list_skeletons` — if a skeleton matches the course
   shape, `create_site_from_skeleton` (skeleton, name="{site_name}") builds the demo
   outline in one call; otherwise `create_site` (name="{site_name}", theme="{theme}").
   Read the returned name — on a duplicate request the server silently creates
   "<name>-1". Machine names must be lowercase letters, digits, dashes and underscores.
3. CREATE the pages in ONE bulk `create_pages` call: a list of {{title, parent, order}}
   objects where `parent` may reference an earlier entry's id — that is how the tree is
   built in a single request (one git commit). Give every page its outline order.
4. VERIFY the structure with `get_outline`: titles, nesting and order must match the
   outline. Only if something is wrong, fix it with `reorder_pages` — it is a
   full-manifest rewrite (destructive): read `get_outline`, change what is wrong, and
   submit the COMPLETE ordered list back.
5. If you started from a skeleton and need the theme changed, `set_site_theme` (valid
   machine names come from `list_themes`).
6. Fill the first page if the brief asks for content now — otherwise stop here: the
   scaffold is the deliverable. Report the site name, the page tree, and suggest the
   build-page-from-brief prompt for filling individual pages.

{_DISCIPLINE}"""

    @mcp.prompt
    def import_and_polish_document(site_name: str, source: str) -> str:
        """Import a document into a new site, then polish structure and metadata."""
        return f"""\
Import the document "{source}" into a new site named "{site_name}", then polish it:

1. `create_site_from_document` (name="{site_name}", source="{source}") — supported
   sources: .docx, .pptx, .html/.htm, .xlsx, .pdf documents (local path, http(s) URL,
   data: or base64:). The heading structure of the document becomes the site outline;
   inline images become site files. READ the returned name — a duplicate request
   silently creates "<name>-1".
2. `get_outline` on the new site: the document's heading tree, with the imported pages
   in outline order. Note every page id.
3. POLISH each page:
   - `get_page_blocks` and check heading levels — documents often carry several h1s or
     skip levels; a page should read top-down (one leading heading, then h2/h3
     sections). Fix a heading with `replace_block` (keep its text, change the tag).
   - Images that arrived without usable alt text: `update_block` with
     set={{"alt": <description from the surrounding text>}} — plus `caption`/`citation`
     where the document provides them. {_A11Y}
   - Broken or empty paragraphs: `remove_block` (destructive — confirm the block first).
4. SITE METADATA: `update_site_info` (title, description) and `update_seo_settings`
   (description, lang) so the site is presentable and findable.
5. VERIFY: `search_site` for a key phrase from the document; read a page back through
   haxcms://sites/<site>/pages/<slug>; `list_files` shows the materialized images.
6. HAND OFF: `export_site` (format "zip") archives the polished site into the Output
   Directory; `save_site_as_template` keeps it server-side as a reusable skeleton
   (visible via `list_skeletons` afterwards).

{_DISCIPLINE}

{_ARTIFACTS}"""
