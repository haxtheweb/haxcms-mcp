"""File Source resolution (PLAN Phase 5 T5.2; §2.3 "File Sources").

`resolve_source(source, settings) -> SourceFile(data, filename, mimetype)` understands
four source forms:

* `http://` / `https://` URLs — fetched with httpx (size cap = the HAXcms upload limit,
  50mb by default); the filename comes from the URL path.
* `data:` URLs — decoded (base64 or percent-encoded); cap `HAXCMS_MCP_MAX_INLINE_BASE64_MB`.
* `base64:<name>:<payload>` — the inline form that carries a filename; same cap.
* anything else — a local path that must resolve INSIDE one of `HAXCMS_MCP_INPUT_ROOTS`
  (default: the working directory) or raise FILE_SOURCE_ERROR. Relative paths are tried
  against each root in order; `..` segments that escape a root are rejected.

MIME sniffing (T5.2): magic bytes for png/jpg/gif/webp/pdf; ZIP containers inspected for
the OOXML office formats (docx/pptx/xlsx); `mimetypes` plus URL Content-Type / data-URL
headers as fallbacks. Every failure mode raises FILE_SOURCE_ERROR with an actionable hint.
"""

from __future__ import annotations

import base64
import binascii
import io
import mimetypes
import re
import zipfile
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlparse

import httpx

from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

# the HAXcms upload limit (HAXCMS_UPLOAD_LIMIT default, API-REF §6) — sources larger than
# this can never be uploaded, so they are rejected before any transfer
UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024

FALLBACK_MIMETYPE = "application/octet-stream"

# data:[<mime>][;base64],<payload>
_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]*)(?P<params>[^,]*),(?P<payload>.*)$", re.S)

# base64:<filename>:<payload>
_INLINE_BASE64_RE = re.compile(r"^base64:(?P<name>[^:]+):(?P<payload>.+)$", re.S)

# OOXML marker directory inside a ZIP container -> mimetype
_OOXML_MIME_BY_PREFIX = (
    ("word/", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("ppt/", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("xl/", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
)


class SourceFile(NamedTuple):
    """The resolved source: raw bytes plus the filename and MIME to upload them as."""

    data: bytes
    filename: str
    mimetype: str


def sniff_mimetype(data: bytes) -> str | None:
    """Magic-byte MIME detection for the T5.2 formats (None when unrecognised).

    Covers png/jpg/gif/webp/pdf by signature and docx/pptx/xlsx by inspecting the ZIP
    container's entry names; plain ZIPs report `application/zip`.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile:
            return "application/zip"
        for prefix, mimetype in _OOXML_MIME_BY_PREFIX:
            if any(name.startswith(prefix) for name in names):
                return mimetype
        return "application/zip"
    return None


def _guess_from_name(filename: str) -> str | None:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed


def _source_error(message: str, hint: str | None = None) -> HaxcmsMcpError:
    return HaxcmsMcpError(
        ErrorCode.FILE_SOURCE_ERROR,
        message,
        hint=hint
        or "sources are an http(s) URL, a data: URL, base64:<name>:<payload>, or a path "
        "inside HAXCMS_MCP_INPUT_ROOTS",
    )


def _check_upload_cap(size: int, what: str) -> None:
    if size > UPLOAD_LIMIT_BYTES:
        raise _source_error(
            f"{what} is {size} bytes, over the HAXcms upload limit of "
            f"{UPLOAD_LIMIT_BYTES} bytes (50mb)",
            hint="the instance's HAXCMS_UPLOAD_LIMIT caps every upload; split or shrink "
            "the source first",
        )


def _check_inline_cap(size: int, settings: Settings) -> None:
    cap = settings.max_inline_base64_mb * 1024 * 1024
    if size > cap:
        raise _source_error(
            f"inline source decodes to {size} bytes, over the "
            f"{settings.max_inline_base64_mb}mb inline cap",
            hint="raise HAXCMS_MCP_MAX_INLINE_BASE64_MB, or point source at a local path "
            "or http(s) URL instead of inline base64",
        )


def _decode_base64(payload: str, what: str) -> bytes:
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _source_error(f"{what} is not valid base64 ({exc})") from exc


def _extension_for(mimetype: str | None) -> str:
    if not mimetype:
        return ""
    # guess_extension returns e.g. '.png'; '.jpe' quirks are acceptable for uploads
    return mimetypes.guess_extension(mimetype.split(";")[0].strip()) or ""


async def _resolve_url(source: str, settings: Settings) -> SourceFile:
    try:
        async with httpx.AsyncClient(timeout=settings.timeout_s, follow_redirects=True) as fetcher:
            response = await fetcher.get(source)
    except httpx.HTTPError as exc:
        raise _source_error(f"could not fetch {source} ({exc})") from exc
    if response.status_code >= 400:
        raise _source_error(f"fetching {source} returned HTTP {response.status_code}")

    content_length = response.headers.get("content-length")
    if content_length and content_length.isdigit():
        _check_upload_cap(int(content_length), f"the file at {source}")
    data = response.content
    _check_upload_cap(len(data), f"the file at {source}")

    basename = unquote(Path(urlparse(source).path).name)
    filename = basename or "download"
    content_type = response.headers.get("content-type", "")
    mimetype = (
        sniff_mimetype(data)
        or (content_type.split(";")[0].strip() if content_type else None)
        or _guess_from_name(filename)
        or FALLBACK_MIMETYPE
    )
    if not basename and filename == "download":
        filename = f"download{_extension_for(mimetype)}"
    return SourceFile(data, filename, mimetype)


def _resolve_data_url(source: str, settings: Settings) -> SourceFile:
    match = _DATA_URL_RE.match(source)
    if match is None:
        raise _source_error("malformed data: URL", hint="form: data:[<mime>][;base64],<payload>")
    header_mime = match.group("mime").strip() or None
    payload = match.group("payload")
    if "base64" in match.group("params").lower():
        data = _decode_base64(payload, "the data: URL payload")
    else:
        data = unquote(payload).encode("utf-8")
    _check_inline_cap(len(data), settings)
    mimetype = header_mime or sniff_mimetype(data) or FALLBACK_MIMETYPE
    filename = f"upload{_extension_for(mimetype)}"
    return SourceFile(data, filename, mimetype)


def _resolve_inline_base64(source: str, settings: Settings) -> SourceFile:
    match = _INLINE_BASE64_RE.match(source)
    if match is None:
        raise _source_error(
            "malformed base64: source",
            hint="form: base64:<filename>:<payload>, e.g. base64:photo.png:iVBORw0K...",
        )
    filename = match.group("name").strip()
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise _source_error(
            f"invalid filename {filename!r} in the base64: source",
            hint="the name is a plain filename with an extension, e.g. photo.png",
        )
    data = _decode_base64(match.group("payload"), "the base64: payload")
    _check_inline_cap(len(data), settings)
    mimetype = sniff_mimetype(data) or _guess_from_name(filename) or FALLBACK_MIMETYPE
    return SourceFile(data, filename, mimetype)


def _resolve_path(source: str, settings: Settings) -> SourceFile:
    candidate = Path(source)
    roots = [Path(root).resolve() for root in settings.input_roots] or [Path.cwd()]
    tried: list[Path] = []
    resolved: Path | None = None
    if candidate.is_absolute():
        resolved_candidate = candidate.resolve()
        tried.append(resolved_candidate)
        if any(_is_inside(resolved_candidate, root) for root in roots):
            resolved = resolved_candidate
    else:
        for root in roots:
            resolved_candidate = (root / candidate).resolve()
            tried.append(resolved_candidate)
            if _is_inside(resolved_candidate, root) and resolved_candidate.is_file():
                resolved = resolved_candidate
                break
            # exists but escapes the root after resolution (.. or a link) — keep looking
    if resolved is None:
        raise _source_error(
            f"path {source!r} does not resolve to a file inside the input roots",
            hint="input roots (HAXCMS_MCP_INPUT_ROOTS): "
            + ", ".join(str(root) for root in roots)
            + f"; tried: {', '.join(str(path) for path in tried)}",
        )
    if not resolved.is_file():
        raise _source_error(f"{source!r} is not a file", hint="point source at a regular file")
    size = resolved.stat().st_size
    _check_upload_cap(size, f"the file {resolved.name}")
    data = resolved.read_bytes()
    mimetype = sniff_mimetype(data) or _guess_from_name(resolved.name) or FALLBACK_MIMETYPE
    return SourceFile(data, resolved.name, mimetype)


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


async def resolve_source(source: str, settings: Settings) -> SourceFile:
    """Resolve any supported source form to `(data, filename, mimetype)` (PLAN §2.3)."""
    text = (source or "").strip()
    if not text:
        raise _source_error("source must not be empty")
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        return await _resolve_url(text, settings)
    if lowered.startswith("data:"):
        return _resolve_data_url(text, settings)
    if lowered.startswith("base64:"):
        return _resolve_inline_base64(text, settings)
    return _resolve_path(text, settings)
