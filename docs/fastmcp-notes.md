# FastMCP notes (verified against fastmcp 4.0.10)

Pinned in `pyproject.toml` as `fastmcp>=4,<5`; the version these notes were verified against is
**4.0.10** (pulls `mcp` SDK v2: `mcp_types` module, snake_case field names with camelCase
compat shims). Every snippet below was executed on this machine with that version (probe script,
Phase 0). Where the API differs from fastmcp 2.x tutorials you may find online, trust this file.

## 1. Creating the server

```python
from fastmcp import FastMCP

mcp = FastMCP("haxcms-mcp")
```

## 2. Registering a tool

`@mcp.tool` accepts `name`, `description`, `annotations`, `tags`, `title`, `timeout`, and more
(full kwarg list: `name_or_fn, name, version, title, description, icons, tags, output_schema,
annotations, meta, app, task, timeout, auth, run_in_thread`). The docstring is used as the
description when `description` is not passed. The parameter JSON schema is derived from the
function signature (pydantic v2 under the hood), so plain typed parameters and pydantic models
both work.

```python
import mcp_types


@mcp.tool(
    description="Read a thing.",  # optional; docstring is the fallback
    annotations=mcp_types.ToolAnnotations(
        title="Read thing",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def read_thing(name: str, count: int = 1) -> dict[str, object]:
    """Read a thing by name."""
    return {"name": name, "count": count}
```

**Annotations field names are snake_case** in mcp SDK v2:
`title, read_only_hint, destructive_hint, idempotent_hint, open_world_hint`
(camelCase aliases like `readOnlyHint` also work through fastmcp's `_compat` shim, but this
project uses snake_case). `ToolAnnotations` is imported from `mcp_types`, not `mcp.types`
(`mcp.types` still re-exports it; `fastmcp.tools.base` imports it from `mcp_types`).

Returning a `dict` produces both text content and `structured_content` on the wire (an output
schema is inferred). Tool results therefore come back to the client as
`CallToolResult.data` (structured dict) — see §9.

## 3. Raising a tool error visible to the client

```python
from fastmcp.exceptions import ToolError


@mcp.tool
async def write_thing(name: str) -> str:
    raise ToolError("[INVALID_ARGUMENT] nope. hint here")
```

Verified: the client's `call_tool` re-raises `ToolError` with the exact message. Raising
`ToolError` from inside middleware `on_call_tool` (before `call_next`) propagates the same way.

**Important (verified)**: any *other* exception raised inside a tool body — e.g. our
`HaxcmsMcpError` — is caught by `FastMCP.call_tool` **below** the middleware chain and masked
into `ToolError("Error calling tool '<name>': <original str>")` with the original exception
attached as `__cause__` (server.py ~L1532-1565; it also logs the traceback via
`logger.exception`). Middleware never sees the raw exception. Our `ErrorTranslationMiddleware`
therefore catches the masked `ToolError`, checks `exc.__cause__` for `HaxcmsMcpError`, and
re-raises a clean `ToolError(cause.formatted)`. Alternative not used: raising `ToolError`
directly from tool functions.

## 4. Reading the request context

Add a parameter annotated `Context`; fastmcp injects it and keeps it out of the tool schema:

```python
from fastmcp import Context


@mcp.tool
async def ctx_tool(x: int, ctx: Context) -> str:
    await ctx.info("...")  # MCP logging capability (DEPRECATED upstream, SEP-2577)
    server = ctx.fastmcp  # the FastMCP server instance
    return "ok"
```

Note: `ctx.info/debug/warn` use the MCP logging capability which mcp SDK v2 marks deprecated
(warns at runtime). This project logs to **stderr** via `haxcms_mcp.logging` instead and only uses
`Context` for server access / session info.

## 5. Middleware (runs before every tool call, can read annotations)

```python
import mcp_types
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext


class ReadOnlyGate(Middleware):
    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, "ToolResult"],
    ):
        params = context.message  # CallToolRequestParams: .name, .arguments
        fctx = context.fastmcp_context  # the Context (may be None in edge cases)
        tool = await fctx.fastmcp.get_tool(params.name)  # fastmcp Tool object
        ann = tool.annotations  # ToolAnnotations | None
        if ann is not None and not (ann.read_only_hint or False):
            raise ToolError("[READ_ONLY] ...")
        return await call_next(context)


mcp.add_middleware(ReadOnlyGate())
```

Verified: `on_call_tool` fires for every tool call (3 calls → 3 hits). Other hooks on the base
class: `on_message, on_request, on_notification, on_initialize, on_discover, on_read_resource,
on_get_prompt, on_list_tools, on_list_resources, on_list_resource_templates, on_list_prompts`.
`MiddlewareContext` fields: `message, fastmcp_context, source, type, method, timestamp` plus
`.copy(**kw)`.

Getting the tool's annotations from middleware requires the async
`await context.fastmcp_context.fastmcp.get_tool(name)` lookup (there is no annotations field on
the request params). Cache per-tool decisions if this ever gets hot.

## 6. Resources and resource templates

```python
@mcp.resource("haxcms://catalog/blocks")
def catalog_resource() -> str:
    return '["p", "h2"]'


@mcp.resource("haxcms://sites/{site}/outline")  # {param} -> function argument
def outline_resource(site: str) -> str:
    return f"outline of {site}"
```

URIs with `{param}` segments become **resource templates** (listed under
`client.list_resource_templates()` as `uri_template`); static URIs are plain resources. Return
`str` for text content (or bytes for blob). Reading a template instance URI
(`haxcms://sites/demo/outline`) routes through the template function.

## 7. Prompts with arguments

```python
@mcp.prompt
def journey(site_name: str, theme: str = "clean-one") -> str:
    """Build a course."""
    return f"Create site {site_name} with theme {theme}"
```

Typed parameters become prompt arguments (name, description from docstring not required).
Client: `await client.get_prompt("journey", {"site_name": "demo"})` →
`GetPromptResult.messages[0].content.text`.

## 8. Running stdio and streamable HTTP

```python
mcp.run(transport="stdio")
mcp.run(transport="http", host="127.0.0.1", port=8765, path="/mcp")
```

`run(transport=None|... , show_banner=None, **transport_kwargs)`; transports: `"stdio"`,
`"http"`, `"streamable-http"`, `"sse"`. Async variant: `await mcp.run_async(...)`; HTTP variant
`run_http_async(show_banner=True, transport='http', host=None, port=None, log_level=None,
path=None, ...)` (full kwargs verified via inspect). `path` sets the streamable-HTTP endpoint
path. Do **not** call `run()` at import time — guard with `if __name__ == "__main__"` / CLI main.
FastMCP configures its own logging on import (`FASTMCP_*` settings); our CLI sets stderr logging
explicitly and fastmcp's banners go to stderr, keeping stdout clean for stdio transport.

## 9. In-memory client for tests

```python
from fastmcp import Client

async with Client(mcp) as client:  # mcp is the FastMCP instance -> memory transport
    tools = await client.list_tools()  # list[mcp_types.Tool]
    result = await client.call_tool("read_thing", {"name": "a", "count": 2})
    assert result.data == {"name": "a", "count": 2}  # structured content
    assert result.structured_content == {"name": "a", "count": 2}
    resources = await client.list_resources()  # .uri
    templates = await client.list_resource_templates()  # .uri_template
    await client.read_resource("haxcms://catalog/blocks")
    prompts = await client.list_prompts()  # .name, .arguments
    await client.get_prompt("journey", {"site_name": "demo"})
```

Client-side `list_tools()` items are wire types (`mcp_types.Tool`) with fields:
`name, title, description, input_schema, execution, output_schema, icons, annotations, meta`.
A tool that raised `ToolError` makes `call_tool` raise `ToolError` client-side (message intact).

## 10. Getting each tool's JSON schema (for snapshot tests)

Server-side, richer objects:

```python
tools = await mcp.list_tools()  # Sequence[fastmcp FunctionTool]
tool = await mcp.get_tool("read_thing")  # single
tool.name
tool.description
tool.parameters  # JSON schema dict: {"type": "object", "properties": {...}, "required": [...], "additionalProperties": false}
tool.annotations  # ToolAnnotations | None
```

Verified `tool.parameters` output:
`{"additionalProperties": false, "properties": {"name": {"type": "string"}, "count":
{"default": 1, "type": "integer"}}, "required": ["name"], "type": "object"}`.
The snapshot test serialises `{name, description, parameters, annotations}` per tool with
`json.dumps(sort_keys=True)`.

## 11. Gotchas / deviations recorded

- There is **no** `mcp.get_tools()`; use `await mcp.list_tools()` (all) or
  `await mcp.get_tool(name)` (one).
- mcp SDK v2 renamed the wire module to `mcp_types`; `mcp.types` still works. Field names are
  snake_case (`read_only_hint`), camelCase accepted via compat shim.
- `Context.info()` etc. emit a deprecation warning (MCP logging capability, SEP-2577). Log to
  stderr instead.
- Accessing `model_fields` on a pydantic **instance** is deprecated (pydantic 2.11+); use the
  class.
- fastmcp installs `fastmcp-slim` as its runtime core; both report version 4.0.10.
- `@mcp.tool` decorator default `run_in_thread=True` — async tools are unaffected (they run on
  the event loop); it only matters for sync functions.
