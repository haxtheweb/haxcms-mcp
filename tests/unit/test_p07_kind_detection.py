"""Unit tests for import-kind detection (PLAN Phase 7 T7.1).

The server enforces extensions (importDocx regexes .docx + zip magic; the html platform
allow-lists .html/.htm), so detection is extension-first with a mimetype fallback for
data:/base64: sources, and legacy binaries (.doc/.xls/.ppt) are refused locally instead
of after a doomed upload.
"""

from __future__ import annotations

import pytest

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.imports import IMPORT_KINDS, detect_import_kind

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("filename", "kind"),
    [
        ("lesson.docx", "docx"),
        ("LESSON.DOCX", "docx"),
        ("deck.pptx", "pptx"),
        ("page.html", "html"),
        ("page.HTM", "html"),
        ("sheet.xlsx", "xlsx"),
        ("paper.pdf", "pdf"),
        ("C:\\Users\\me\\docs\\some.folder\\report.docx", "docx"),
        ("/tmp/exports/course outline.pdf", "pdf"),
    ],
)
def test_extension_detection(filename: str, kind: str) -> None:
    assert detect_import_kind(filename=filename) == kind


def test_extension_beats_mimetype() -> None:
    assert detect_import_kind(filename="report.pdf", mimetype="text/html") == "pdf"


@pytest.mark.parametrize(
    ("mimetype", "kind"),
    [
        ("application/pdf", "pdf"),
        ("APPLICATION/PDF", "pdf"),
        ("text/html", "html"),
        ("text/html; charset=utf-8", "html"),  # parameters stripped
        ("application/xhtml+xml", "html"),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        ),
        (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "pptx",
        ),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    ],
)
def test_mimetype_fallback(mimetype: str, kind: str) -> None:
    assert detect_import_kind(mimetype=mimetype) == kind


def test_mimetype_fallback_when_filename_has_no_suffix() -> None:
    assert detect_import_kind(filename="upload", mimetype="application/pdf") == "pdf"


@pytest.mark.parametrize(
    "filename",
    ["legacy.doc", "legacy.xls", "legacy.ppt", "notes.txt", "archive.zip", "Makefile"],
)
def test_unsupported_extension_raises(filename: str) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        detect_import_kind(filename=filename)
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert filename in error.message
    hint = error.hint or ""
    for kind in IMPORT_KINDS:
        assert kind in hint


def test_unknown_mimetype_raises() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        detect_import_kind(filename="data.bin", mimetype="application/octet-stream")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


def test_nothing_to_detect_raises() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        detect_import_kind()
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
