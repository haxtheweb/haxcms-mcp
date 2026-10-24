"""Fixed sample arguments for rendering the Phase 9 prompts (unit checks + goldens).

Shared so the regression goldens and the unit assertions always render the SAME texts.
Sample values are deliberately token-clean (no snake_case that is not a tool name).
"""

from __future__ import annotations

from typing import Any

PROMPT_NAMES: list[str] = [
    "build_page_from_brief",
    "hax_author",
    "import_and_polish_document",
    "scaffold_course_from_outline",
]

SAMPLE_ARGS: dict[str, dict[str, Any]] = {
    "build_page_from_brief": {
        "site": "demo",
        "page_title": "Lesson One",
        "brief": (
            "Three paragraphs on prairie design; one section heading; "
            "close with a link to the field guide."
        ),
        "media": ["files/songline.png", "https://video.example/lecture"],
    },
    "scaffold_course_from_outline": {
        "site_name": "demo-course",
        "outline_text": "- Home\n- Unit One\n  - Lesson One\n  - Lesson Two",
        "theme": "clean-one",
    },
    "import_and_polish_document": {
        "site_name": "bio-101",
        "source": "files/syllabus.docx",
    },
}


def render_args(name: str) -> dict[str, Any]:
    """Sample arguments for one prompt (hax_author takes none)."""
    return dict(SAMPLE_ARGS.get(name, {}))
