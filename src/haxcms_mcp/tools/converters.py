"""Registration of the twelve generated converter tools (PLAN T7.5, ADR-0002).

The converter functions live in `src/haxcms_mcp/generated/converters.py` (emitted by
scripts/gen_tools.py from the vendored spec — do not hand-edit them). This module binds
the shared client — and the settings for the multipart ops that resolve Sources — into
each function with `functools.partial` and registers the partials as tools:

* FastMCP's ParsedFunction supports partials explicitly and reads them through
  `inspect.signature`, so the bound parameters vanish from the tool schema while the
  remaining ones keep their spec-derived types and defaults;
* `mcp.tool(...)` rejects partials as its first argument, so registration goes through
  `Tool.from_function(...) -> mcp.add_tool(...)` (the same path the decorator takes
  internally);
* the tool description is passed explicitly from the generated docstring (FastMCP
  captures descriptions at registration time, and partials carry no `__doc__`).

Converters are READ-ONLY (PLAN annotation matrix): they mutate nothing on the HAXcms
instance; binary results are written under the LOCAL Output Directory.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import Tool

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.generated import converters as generated
from haxcms_mcp.tools._common import tool_annotations

# Tool name -> human title, in the generator's CONVERTERS order.
TITLES: dict[str, str] = {
    "convert_docx_to_html": "Convert DOCX to HTML",
    "convert_html_to_docx": "Convert HTML to DOCX",
    "convert_md_to_html": "Convert Markdown to HTML",
    "convert_html_to_md": "Convert HTML to Markdown",
    "convert_pretty_html": "Pretty-print HTML",
    "convert_json_to_yaml": "Convert JSON to YAML",
    "convert_yaml_to_json": "Convert YAML to JSON",
    "convert_html_to_pdf": "Convert HTML to PDF",
    "convert_xlsx_to_csv": "Convert XLSX to CSV",
    "convert_pdf_to_html": "Convert PDF to HTML",
    "convert_pptx_to_html": "Convert PPTX to HTML",
    "convert_docx_to_pdf": "Convert DOCX to PDF",
}


def _bind(
    fn: Callable[..., Any], client: HaxcmsClient, settings: Settings
) -> functools.partial[Any]:
    """Pre-bind client (plus settings for the multipart ops) out of the tool schema."""
    if "settings" in inspect.signature(fn).parameters:
        return functools.partial(fn, client, settings)
    return functools.partial(fn, client)


def register_converter_tools(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register all twelve generated converters as read-only tools."""
    for name, title in TITLES.items():
        fn: Callable[..., Any] = getattr(generated, name)
        mcp.add_tool(
            Tool.from_function(
                _bind(fn, client, settings),
                name=name,
                description=inspect.getdoc(fn) or title,
                annotations=tool_annotations(title, read_only=True),
            )
        )
