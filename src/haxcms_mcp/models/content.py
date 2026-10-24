"""Content models (PLAN Phase 4).

`Block` is the §2.3 block record the parser produces and the anchor resolver searches.
`PageContent` is the read shape (record + body + blocks); `BlockOpResult` is the §2.5
result every block write returns.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from haxcms_mcp.models.item import Item


class Block(BaseModel):
    """One top-level content block: `{index, tag, attributes, text, html, preview}`.

    `text` is the whitespace-collapsed text of the whole subtree; `html` is the block's
    serialized outer HTML; `preview` is the first 80 characters of `text`, falling back to
    `html` for text-less blocks (media) so anchor errors stay informative.
    """

    model_config = ConfigDict(extra="allow")

    index: int
    tag: str
    attributes: dict[str, str] = {}
    text: str = ""
    html: str = ""
    preview: str = ""


class PageContent(BaseModel):
    """A page's stored record, raw body HTML and parsed blocks (T4.3 read shape)."""

    item: Item
    html: str = ""
    blocks: list[Block] = []


class BlockOpResult(BaseModel):
    """Result of a block write (§2.5).

    `affected` lists the blocks the operation created/changed (for `remove_block` the
    removed block at its OLD index); `block_count` is the post-save number of top-level
    blocks; `saved` is True once the PATCH returned (upstream committed one git revision).
    """

    site: str
    page_id: str
    page_slug: str
    operation: str
    affected: list[Block] = []
    block_count: int = 0
    saved: bool = True
