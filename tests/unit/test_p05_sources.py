"""Unit tests for file source resolution (PLAN Phase 5 T5.2, test list).

Covers: local paths inside/outside the input roots (including `..` escapes), URL fetches
with respx (sniffing precedence, Content-Type fallback, basename-less URLs, HTTP and
connection failures, the upload size cap), `data:` URLs and the `base64:<name>:<payload>`
inline form (decode, caps, malformed inputs), and magic-byte MIME sniffing for
png/jpg/gif/webp/pdf plus the OOXML ZIP containers.
"""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

import httpx
import pytest
import respx

from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.files import sources
from haxcms_mcp.services.files.sources import resolve_source, sniff_mimetype

BASE = "http://localhost:9"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def make_settings(tmp_path: Path | None = None, **kwargs: object) -> Settings:
    roots = [tmp_path] if tmp_path is not None else [Path.cwd()]
    return Settings(base_url=BASE, input_roots=roots, **kwargs)  # type: ignore[arg-type]


def zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return buffer.getvalue()


# --- MIME sniffing ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG_BYTES, "image/png"),
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (b"GIF87abc", "image/gif"),
        (b"GIF89abc", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"%PDF-1.7 rest", "application/pdf"),
    ],
)
def test_sniff_magic_signatures(data: bytes, expected: str) -> None:
    assert sniff_mimetype(data) == expected


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("word/document.xml", DOCX_MIME),
        ("ppt/presentation.xml", PPTX_MIME),
        ("xl/workbook.xml", XLSX_MIME),
    ],
)
def test_sniff_ooxml_containers(marker: str, expected: str) -> None:
    assert sniff_mimetype(zip_bytes({marker: "<x/>", "[Content_Types].xml": "<t/>"})) == expected


def test_sniff_plain_zip_and_unknown() -> None:
    assert sniff_mimetype(zip_bytes({"readme.txt": "hi"})) == "application/zip"
    assert sniff_mimetype(b"\x00\x01\x02unknown") is None
    # a corrupt ZIP signature still reports zip rather than crashing
    assert sniff_mimetype(b"PK\x03\x04corrupt") == "application/zip"


# --- local paths ----------------------------------------------------------------------------


async def test_absolute_path_inside_root(tmp_path: Path) -> None:
    target = tmp_path / "photo.png"
    target.write_bytes(PNG_BYTES)
    resolved = await resolve_source(str(target), make_settings(tmp_path))
    assert resolved.data == PNG_BYTES
    assert resolved.filename == "photo.png"
    assert resolved.mimetype == "image/png"


async def test_relative_path_resolves_against_root(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "doc.html").write_bytes(b"<html></html>")
    resolved = await resolve_source("nested/doc.html", make_settings(tmp_path))
    assert resolved.filename == "doc.html"
    assert resolved.mimetype == "text/html"


async def test_sniffing_beats_extension(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_bytes(PNG_BYTES)
    resolved = await resolve_source(str(target), make_settings(tmp_path))
    assert resolved.mimetype == "image/png"


async def test_unknown_extension_falls_back_to_octet_stream(tmp_path: Path) -> None:
    target = tmp_path / "blob.qqq"
    target.write_bytes(b"\x00\x01")
    resolved = await resolve_source(str(target), make_settings(tmp_path))
    assert resolved.mimetype == "application/octet-stream"


async def test_path_outside_root_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG_BYTES)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(str(outside), make_settings(root))
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "input roots" in excinfo.value.message


async def test_relative_escape_from_root_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.png").write_bytes(PNG_BYTES)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source("../outside.png", make_settings(root))
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR


async def test_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source("nope.png", make_settings(tmp_path))
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR


async def test_directory_rejected(tmp_path: Path) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(str(tmp_path), make_settings(tmp_path.parent))
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR


async def test_oversize_local_file_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "UPLOAD_LIMIT_BYTES", 10)
    target = tmp_path / "big.png"
    target.write_bytes(b"x" * 11)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(str(target), make_settings(tmp_path))
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "upload limit" in excinfo.value.message


# --- http(s) URLs -----------------------------------------------------------------------------


@respx.mock
async def test_url_fetch_sniffing_beats_content_type() -> None:
    respx.get("http://files.test/media/photo.png").mock(
        return_value=httpx.Response(200, content=PNG_BYTES, headers={"content-type": "text/plain"})
    )
    resolved = await resolve_source("http://files.test/media/photo.png", make_settings())
    assert resolved.data == PNG_BYTES
    assert resolved.filename == "photo.png"
    assert resolved.mimetype == "image/png"


@respx.mock
async def test_url_fetch_content_type_fallback() -> None:
    respx.get("http://files.test/media/notes.json").mock(
        return_value=httpx.Response(
            200, content=b"{}", headers={"content-type": "application/json; charset=utf-8"}
        )
    )
    resolved = await resolve_source("http://files.test/media/notes.json", make_settings())
    assert resolved.mimetype == "application/json"
    assert resolved.filename == "notes.json"


@respx.mock
async def test_url_fetch_without_basename_gets_download_name() -> None:
    respx.get("http://files.test/").mock(
        return_value=httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
    )
    resolved = await resolve_source("http://files.test/", make_settings())
    assert resolved.filename == "download.png"


@respx.mock
async def test_url_fetch_http_error_rejected() -> None:
    respx.get("http://files.test/gone.png").mock(return_value=httpx.Response(404))
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source("http://files.test/gone.png", make_settings())
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "404" in excinfo.value.message


@respx.mock
async def test_url_fetch_connection_error_rejected() -> None:
    respx.get("http://files.test/x.png").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source("http://files.test/x.png", make_settings())
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "could not fetch" in excinfo.value.message


@respx.mock
async def test_url_fetch_over_upload_cap_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "UPLOAD_LIMIT_BYTES", 10)
    respx.get("http://files.test/big.png").mock(
        return_value=httpx.Response(200, content=b"x" * 11, headers={"content-type": "image/png"})
    )
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source("http://files.test/big.png", make_settings())
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "upload limit" in excinfo.value.message


# --- data: URLs ---------------------------------------------------------------------------------


async def test_data_url_base64_with_header() -> None:
    resolved = await resolve_source(f"data:image/png;base64,{PNG_B64}", make_settings())
    assert resolved.data == PNG_BYTES
    assert resolved.mimetype == "image/png"
    assert resolved.filename == "upload.png"


async def test_data_url_without_header_sniffs() -> None:
    resolved = await resolve_source(f"data:;base64,{PNG_B64}", make_settings())
    assert resolved.mimetype == "image/png"


async def test_data_url_percent_encoded_text() -> None:
    resolved = await resolve_source("data:text/plain,hello%20world", make_settings())
    assert resolved.data == b"hello world"
    assert resolved.mimetype == "text/plain"
    # the extension rides guess_extension('text/plain'), which varies by platform
    assert resolved.filename.startswith("upload.")


async def test_data_url_malformed_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source("data:image/png", make_settings())
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "malformed data: URL" in excinfo.value.message


async def test_data_url_over_inline_cap_rejected() -> None:
    settings = make_settings().model_copy(update={"max_inline_base64_mb": 0})
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(f"data:image/png;base64,{PNG_B64}", settings)
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "inline cap" in excinfo.value.message
    assert "MAX_INLINE_BASE64_MB" in str(excinfo.value.hint)


async def test_data_url_invalid_base64_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source("data:image/png;base64,!!!not-base64!!!", make_settings())
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "not valid base64" in excinfo.value.message


# --- base64:<name>:<payload> ----------------------------------------------------------------------


async def test_inline_base64_form() -> None:
    resolved = await resolve_source(f"base64:photo.png:{PNG_B64}", make_settings())
    assert resolved.data == PNG_BYTES
    assert resolved.filename == "photo.png"
    assert resolved.mimetype == "image/png"


async def test_inline_base64_name_fallback_mime() -> None:
    payload = base64.b64encode(b"{}").decode("ascii")
    resolved = await resolve_source(f"base64:notes.json:{payload}", make_settings())
    assert resolved.mimetype == "application/json"


async def test_inline_base64_malformed_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(f"base64:photo.png{PNG_B64}", make_settings())
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "malformed base64" in excinfo.value.message


async def test_inline_base64_path_name_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(f"base64:../evil.png:{PNG_B64}", make_settings())
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "invalid filename" in excinfo.value.message


async def test_inline_base64_over_cap_rejected() -> None:
    settings = make_settings().model_copy(update={"max_inline_base64_mb": 0})
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(f"base64:photo.png:{PNG_B64}", settings)
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "inline cap" in excinfo.value.message


# --- misc -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["", "   "])
async def test_empty_source_rejected(source: str) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(source, make_settings())
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "must not be empty" in excinfo.value.message
