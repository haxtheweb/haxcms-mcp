"""Hand-written support for the generated converter functions (PLAN T7.4, ADR-0002).

Every function in `src/haxcms_mcp/generated/converters.py` funnels through the helpers
here — the only hand-written place that knows the ConversionResult shape, the output-
directory write rules for binary results, and the upstream extras passthrough
(xlsxToCsv's sheetNames/selectedSheet, pptxToHtml's files map).
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.imports import ConversionResult

MAX_UNIQUE_SUFFIX = 1000


def _extras(data: dict[str, Any]) -> dict[str, Any]:
    """Upstream keys other than `contents`, never shadowing a declared field."""
    return {
        key: value
        for key, value in data.items()
        if key != "contents" and key not in ConversionResult.model_fields
    }


def text_result(data: Any, mimetype: str) -> dict[str, Any]:
    """Envelope `data` `{contents: str, ...}` -> dumped ConversionResult with `text`."""
    if not isinstance(data, dict):
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            f"converter returned a non-object data ({type(data).__name__})",
        )
    contents = data.get("contents")
    if not isinstance(contents, str):
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            "converter data.contents is not a string",
            details={"data_keys": sorted(str(key) for key in data)},
        )
    return dump_model(ConversionResult(text=contents, mimetype=mimetype, **_extras(data)))


def safe_filename(name: Any, fallback: str) -> str:
    """Upstream filenames are untrusted: strip any directory part, fall back when empty."""
    candidate = Path(str(name or "").replace("\\", "/")).name.strip()
    return candidate or fallback


def _unique_path(output_dir: Path, filename: str) -> Path:
    """The first free `<stem>-<n><suffix>` slot, so conversions never overwrite."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    if not path.exists():
        return path
    for index in range(1, MAX_UNIQUE_SUFFIX):
        candidate = output_dir / f"{path.stem}-{index}{path.suffix}"
        if not candidate.exists():
            return candidate
    raise HaxcmsMcpError(
        ErrorCode.UPSTREAM_ERROR,
        f"no free filename for {filename!r} under {output_dir}",
        hint="the output directory holds too many same-named results; clear it",
    )


def _write(raw: bytes, *, filename: str, mimetype: str, output_dir: Path) -> dict[str, Any]:
    path = _unique_path(output_dir, filename)
    path.write_bytes(raw)
    return dump_model(
        ConversionResult(
            path=str(path),
            bytes=len(raw),
            mimetype=mimetype,
            filename=filename,
        )
    )


def write_base64(
    data: Any,
    *,
    mimetype: str,
    fallback_filename: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Envelope `data` `{contents: <base64>, filename?}` -> a file in the Output Directory."""
    if not isinstance(data, dict) or not isinstance(data.get("contents"), str):
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            "converter did not return base64 contents",
        )
    try:
        raw = base64.b64decode(data["contents"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            f"converter returned invalid base64: {exc}",
        ) from exc
    filename = safe_filename(data.get("filename"), fallback_filename)
    return _write(raw, filename=filename, mimetype=mimetype, output_dir=output_dir)


def write_bytes(
    content: bytes,
    *,
    mimetype: str,
    filename: str,
    output_dir: Path,
) -> dict[str, Any]:
    """RAW binary converter response (docxToPdf) -> a file in the Output Directory."""
    return _write(
        content,
        filename=safe_filename(filename, "converted.bin"),
        mimetype=mimetype,
        output_dir=output_dir,
    )
