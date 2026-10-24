# Blocks inside a page are addressed by text anchors and selectors, not by index

An agent editing Page Content must say where a new Block goes. We chose Anchors: a text snippet the
target Block contains, or a tag selector (`h2`, `media-image[alt*=Songline]`), plus an optional
occurrence (`first`, `last`, n). Zero matches and multiple matches without an occurrence are errors
that list candidate Blocks. We rejected index-only addressing because indices shift after every
insert and force the agent to re-list blocks between calls, and rejected whole-page rewrites as the
only mechanism because they make small edits expensive and error-prone for a language model.
`get_page_blocks` still returns indices for orientation, and `set_page_content` remains available for
full rewrites.

## Consequences

- Every block tool carries `anchor`, `occurrence`, `placement` parameters; the resolution rules live
  in one module (`services/content/anchors.py`) and are pinned by unit tests.
- Text matching is case-insensitive substring on normalised block text and on media attribute values,
  so "Songline_1" finds an image by its source or alt.
