"""Unit tests for the converter result helpers (PLAN T7.4) — services/conversion.py."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services import conversion

pytestmark = pytest.mark.unit


def test_text_result_shape() -> None:
    result = conversion.text_result({"contents": "<p>hi</p>"}, "text/html")
    assert result == {"text": "<p>hi</p>", "mimetype": "text/html"}


def test_text_result_passes_upstream_extras() -> None:
    """xlsxToCsv's sheetNames/selectedSheet and pptxToHtml's files map ride along."""
    data = {
        "contents": "a,b\n1,2\n",
        "sheetNames": ["Sheet1", "Data"],
        "selectedSheet": "Data",
    }
    result = conversion.text_result(data, "text/csv")
    assert result["text"] == "a,b\n1,2\n"
    assert result["sheetNames"] == ["Sheet1", "Data"]
    assert result["selectedSheet"] == "Data"


def test_text_result_never_shadows_declared_fields() -> None:
    """An upstream key colliding with a ConversionResult field stays out of the extras."""
    result = conversion.text_result({"contents": "x", "path": "/etc/passwd"}, "text/plain")
    assert result == {"text": "x", "mimetype": "text/plain"}


def test_text_result_rejects_junk() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        conversion.text_result(["not", "a", "dict"], "text/html")
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR
    assert "non-object" in excinfo.value.message
    with pytest.raises(HaxcmsMcpError) as excinfo:
        conversion.text_result({"contents": 42}, "text/html")
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR
    assert excinfo.value.details == {"data_keys": ["contents"]}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.docx", "report.docx"),
        ("  spaced.pdf  ", "spaced.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\file.docx", "file.docx"),
        ("", "converted.pdf"),
        (None, "converted.pdf"),
    ],
)
def test_safe_filename(name: str | None, expected: str) -> None:
    assert conversion.safe_filename(name, "converted.pdf") == expected


def test_write_base64_writes_under_output_dir(tmp_path: Path) -> None:
    raw = b"PK\x03\x04 fake docx bytes"
    data = {"contents": base64.b64encode(raw).decode(), "filename": "made.docx"}
    result = conversion.write_base64(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        fallback_filename="converted.docx",
        output_dir=tmp_path,
    )
    written = tmp_path / "made.docx"
    assert written.read_bytes() == raw
    assert result == {
        "path": str(written),
        "bytes": len(raw),
        "mimetype": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "filename": "made.docx",
    }


def test_write_base64_uses_fallback_and_sanitizes(tmp_path: Path) -> None:
    data = {"contents": base64.b64encode(b"%PDF-1.4").decode(), "filename": "../../evil.pdf"}
    result = conversion.write_base64(
        data, mimetype="application/pdf", fallback_filename="converted.pdf", output_dir=tmp_path
    )
    # the directory part of an upstream filename is stripped, never walked
    assert result["filename"] == "evil.pdf"
    assert (tmp_path / "evil.pdf").exists()
    assert list(tmp_path.iterdir()) == [tmp_path / "evil.pdf"]

    no_name = {"contents": base64.b64encode(b"x").decode()}
    result = conversion.write_base64(
        no_name,
        mimetype="application/pdf",
        fallback_filename="converted.pdf",
        output_dir=tmp_path / "nested",
    )
    assert result["filename"] == "converted.pdf"
    assert (tmp_path / "nested" / "converted.pdf").read_bytes() == b"x"


def test_write_base64_rejects_invalid_payloads(tmp_path: Path) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        conversion.write_base64(
            {"contents": "not base64!"},
            mimetype="application/pdf",
            fallback_filename="converted.pdf",
            output_dir=tmp_path,
        )
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR
    assert "invalid base64" in excinfo.value.message
    with pytest.raises(HaxcmsMcpError):
        conversion.write_base64(
            "just a string",
            mimetype="application/pdf",
            fallback_filename="converted.pdf",
            output_dir=tmp_path,
        )


def test_write_never_overwrites(tmp_path: Path) -> None:
    conversion.write_bytes(
        b"one", mimetype="application/pdf", filename="out.pdf", output_dir=tmp_path
    )
    second = conversion.write_bytes(
        b"two", mimetype="application/pdf", filename="out.pdf", output_dir=tmp_path
    )
    third = conversion.write_bytes(
        b"three", mimetype="application/pdf", filename="out.pdf", output_dir=tmp_path
    )
    assert (tmp_path / "out.pdf").read_bytes() == b"one"
    assert second["filename"] == "out.pdf"  # the reported name is the requested one
    assert second["path"] == str(tmp_path / "out-1.pdf")
    assert third["path"] == str(tmp_path / "out-2.pdf")
    assert (tmp_path / "out-1.pdf").read_bytes() == b"two"
    assert third["bytes"] == 5


def test_write_bytes_falls_back_for_junk_filenames(tmp_path: Path) -> None:
    result = conversion.write_bytes(
        b"%PDF", mimetype="application/pdf", filename="   ", output_dir=tmp_path
    )
    assert result["filename"] == "converted.bin"
    assert (tmp_path / "converted.bin").read_bytes() == b"%PDF"


def test_unique_path_saturation_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversion, "MAX_UNIQUE_SUFFIX", 3)
    for name in ("out.pdf", "out-1.pdf", "out-2.pdf"):
        (tmp_path / name).write_bytes(b"x")
    with pytest.raises(HaxcmsMcpError) as excinfo:
        conversion.write_bytes(
            b"y", mimetype="application/pdf", filename="out.pdf", output_dir=tmp_path
        )
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR
    assert "no free filename" in excinfo.value.message
