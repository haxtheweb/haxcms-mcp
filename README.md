# haxcms-mcp

An MCP (Model Context Protocol) server that lets an AI agent operate a self-hosted
[HAXcms NodeJS](https://github.com/haxtheweb/haxcms-nodejs) instance the way a human author does
through the HAX dashboard and editor: create and manage sites, build outlines, author page content
with the full block catalog, upload files, change themes, import documents, convert formats, and
export artifacts.

It is a typed HTTP client of a **running** HAXcms instance (pinned 26.8.1) — the system API and
the per-site API are the contract ([ADR-0001](docs/adr/0001-http-wrapper-over-running-haxcms.md)).

**What the agent gets**

- **117 tools** — sites, outline, pages, blocks (typed `add_*` tools for the Core Blocks plus the
  generic catalog-driven `add_block`), files, settings, imports, twelve format converters, and
  exports. Full reference: [`docs/tools.md`](docs/tools.md).
- **Resources** — `haxcms://sites`, `haxcms://sites/{site}`, `haxcms://sites/{site}/outline`,
  `haxcms://sites/{site}/pages/{id_or_slug}`, `haxcms://catalog/blocks`,
  `haxcms://catalog/blocks/{tag}`.
- **Prompts** — `hax_author` (the authoring discipline) and three journey prompts:
  `build_page_from_brief`, `scaffold_course_from_outline`, `import_and_polish_document`.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# as a tool, from a clone of this repo
git clone <repo-url> && cd haxcms-mcp
uv tool install .

# or straight from git
uv tool install git+<repo-url>

# or run it once without installing
uvx --from git+<repo-url> haxcms-mcp
```

`uv tool install` puts the `haxcms-mcp` command on your PATH.

## Configure

All settings come from environment variables (prefix `HAXCMS_MCP_`) or a `.env` file in the
working directory.

| Variable | Default | Meaning |
|---|---|---|
| `BASE_URL` | **required** | Instance root, e.g. `http://localhost:3000` (trailing slash optional) |
| `USERNAME`, `PASSWORD` | unset | Credentials for auto-login; if unset, the agent must call `login` |
| `DEFAULT_SITE` | unset | Site used by site-scoped tools when no `site` argument is passed |
| `NO_AUTH` | `false` | Instance runs with `HAXCMS_DISABLE_JWT_CHECKS`; send no auth headers |
| `READ_ONLY` | `false` | Read-Only Mode: every non-read-only tool is rejected |
| `RATE_LIMIT_RPS` | `4` | Outbound Budget refill rate (requests/second to HAXcms) |
| `RATE_LIMIT_BURST` | `8` | Outbound Budget capacity |
| `RATE_LIMIT_MAX_WAIT_S` | `30` | Longest a request waits for a budget token before `RATE_LIMITED` |
| `RETRY_MAX` | `3` | Retries on upstream 429 |
| `TIMEOUT_S` | `60` | HTTP timeout for normal calls |
| `EXPORT_TIMEOUT_S` | `300` | HTTP timeout for export/import/converter calls |
| `OUTPUT_DIR` | `./haxcms-mcp-output` | Where exports and converted files are written (on the **server** host) |
| `INPUT_ROOTS` | cwd | `os.pathsep`-separated directories local file sources may come from |
| `MAX_INLINE_BASE64_MB` | `10` | Cap for inline `base64:` sources |
| `TRANSPORT` | `stdio` | `stdio` or `http` (CLI flags override) |
| `HTTP_HOST`, `HTTP_PORT`, `HTTP_PATH` | `127.0.0.1`, `8765`, `/mcp` | HTTP transport bind address |
| `LOG_LEVEL` | `INFO` | stderr logging (stdout belongs to the stdio transport) |
| `CATALOG_LIVE_TTL_S` | `600` | Live block-catalog cache lifetime |

Test-only variables (`TEST_HAXCMS_DIR`, `TEST_HAXCMS_VERSION`, `TEST_KEEP_RUNTIME`) are documented
in [PLAN.md Section 4](PLAN.md).

## Run

```bash
export HAXCMS_MCP_BASE_URL=http://localhost:3000
export HAXCMS_MCP_USERNAME=admin
export HAXCMS_MCP_PASSWORD=secret

haxcms-mcp                     # stdio transport (default)
haxcms-mcp --transport http --host 127.0.0.1 --port 8765 --path /mcp
haxcms-mcp --version
```

### Claude Code

stdio (the usual setup):

```bash
claude mcp add haxcms \
  --env HAXCMS_MCP_BASE_URL=http://localhost:3000 \
  --env HAXCMS_MCP_USERNAME=admin \
  --env HAXCMS_MCP_PASSWORD=secret \
  -- haxcms-mcp
```

or against a server already running in HTTP mode:

```bash
claude mcp add --transport http haxcms http://127.0.0.1:8765/mcp
```

### Claude Desktop

Add to `claude_desktop_config.json` (stdio; env carries the credentials):

```json
{
  "mcpServers": {
    "haxcms": {
      "command": "haxcms-mcp",
      "env": {
        "HAXCMS_MCP_BASE_URL": "http://localhost:3000",
        "HAXCMS_MCP_USERNAME": "admin",
        "HAXCMS_MCP_PASSWORD": "secret"
      }
    }
  }
}
```

If `haxcms-mcp` is not on the PATH Desktop sees, use the absolute path (`uv tool dir` shows where
tools live) or `"command": "uvx", "args": ["--from", "git+<repo-url>", "haxcms-mcp"]`.

## Security notes

- **Credentials live in the environment only** — never in tool arguments or results.
  Access tokens are held in memory only, and no token or password ever reaches a log line
  (all logging goes to stderr).
- **Read-Only Mode** (`HAXCMS_MCP_READ_ONLY=true`) rejects every tool that is not annotated
  read-only, at the middleware level — a hard guarantee, not a convention.
- **Outbound Budget** rate-limits all traffic to the HAXcms instance (token bucket, default
  4 rps / burst 8) so a runaway agent cannot hammer the server; excess calls wait, then fail
  as `RATE_LIMITED`.
- **Local file reads are confined** to `INPUT_ROOTS`; exports and conversions are written under
  `OUTPUT_DIR` on the machine running the MCP server, and tools return `{path, bytes, mimetype}`
  records — file bytes never travel through the model context.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `[AUTH_REQUIRED]` / `[AUTH_FAILED]`, upstream 403 | Missing or expired session. Call `login`, or set `USERNAME`/`PASSWORD` for auto-login; check the account works in the HAX dashboard. On an instance started with `HAXCMS_DISABLE_JWT_CHECKS`, set `NO_AUTH=true` instead. |
| `[RATE_LIMITED]`, upstream 429 | The Outbound Budget (or HAXcms itself) throttled the call. Retries are automatic up to `RETRY_MAX`; raise `RATE_LIMIT_RPS`/`RATE_LIMIT_BURST` or `RATE_LIMIT_MAX_WAIT_S` if the agent legitimately needs more throughput. |
| `[UNSUPPORTED] ... No Chrome/Chromium executable found` | PDF exports (`export_site(format="pdf")`, `html_to_pdf`, ...) need Chrome **on the HAXcms server** (puppeteer-core). Install Chrome there or set `PUPPETEER_EXECUTABLE_PATH`; otherwise export as `html`, `docx` or `epub`, which need no Chrome. |
| `[ANCHOR_NOT_FOUND]` / `[ANCHOR_AMBIGUOUS]` | The anchor text does not (uniquely) match a block. Read `get_page_blocks` first and copy the anchor from the actual block text; disambiguate with `occurrence`. |
| `[INVALID_ARGUMENT]` on `create_site` | Site names are machine names: lowercase letters, digits, `-` and `_` only, no spaces. The call is rejected before anything is written; the hint restates the rules. |
| Server exits immediately with a configuration error | `BASE_URL` must be set and start with `http://` or `https://`. |

Errors always arrive as `[CODE] message. hint` — the hint names the next tool call or setting
in most cases.

## Development

```bash
git clone <repo-url> && cd haxcms-mcp
uv sync

uv run pytest -m unit                              # fast, no Node required
uv run pytest -m "integration or functional"       # spawns a real HAXcms (needs Node + npm)
uv run pytest -m regression                        # snapshots + golden outputs
uv run pytest -m e2e                               # full tutorial over a stdio subprocess
uv run ruff check . && uv run ruff format --check . && uv run mypy src

uv run python scripts/gen_tools.py --check         # converter drift (ADR-0002)
uv run python scripts/gen_tool_docs.py             # regenerate docs/tools.md
uv run pytest --snapshot-update                    # update regression snapshots deliberately
```

The generated tool reference in [`docs/tools.md`](docs/tools.md) and the generated converters in
`src/haxcms_mcp/generated/converters.py` are checked for drift in CI.

## More documentation

- [`docs/tools.md`](docs/tools.md) — every tool with annotations, parameters and defaults
- [`CONTEXT.md`](CONTEXT.md) — the domain model this server is built on
- [`PLAN.md`](PLAN.md) / [`PROGRESS.md`](PROGRESS.md) — the build plan and the session log
- ADRs: [0001 HTTP wrapper](docs/adr/0001-http-wrapper-over-running-haxcms.md),
  [0002 generated converters](docs/adr/0002-build-time-generated-converter-tools.md),
  [0003 text anchors](docs/adr/0003-text-anchor-block-addressing.md)
- [HAXcms NodeJS](https://github.com/haxtheweb/haxcms-nodejs) — the instance this operates
- [Model Context Protocol](https://modelcontextprotocol.io/) — the protocol it speaks
