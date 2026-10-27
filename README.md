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
| `HTTP_AUTH` | `none` | `haxcms`: every HTTP caller must send their own HAXcms access token (see [Serving over HTTP to other people](#serving-over-http-to-other-people)); required to bind beyond loopback |
| `PUBLIC_URL` | `http://<host>:<port>` | Public origin of this server, used in the OAuth protected-resource metadata |
| `AUTHORIZATION_SERVER_URL` | `BASE_URL` | OAuth authorization server advertised to clients |
| `ALLOW_PRIVATE_URL_SOURCES` | off over HTTP | Allow URL sources that resolve to loopback/private/link-local addresses |
| `ALLOW_LOCAL_SOURCES` | off over HTTP | Allow local-path sources (read from the server's disk) |
| `HTTP_ALLOWED_HOSTS`, `HTTP_ALLOWED_ORIGINS` | none | Extra `Host` names / browser origins the HTTP transport answers (comma-separated). Loopback, the bind address and the `PUBLIC_URL` host are always allowed; anything else gets `421`/`403` (DNS-rebinding protection) |
| `AUTH_FAILURES_PER_MINUTE` | `20` | Per client address: after this many refused bearer tokens in a minute, answer `429` without asking HAXcms (`0` disables; use the proxy's limit behind a reverse proxy) |
| `OUTPUT_TTL_S`, `OUTPUT_CALLER_QUOTA_MB`, `DOWNLOAD_TTL_S` | `3600`, `200`, `900` | Per-caller HTTP mode: results expire after `OUTPUT_TTL_S`, each user may keep `OUTPUT_CALLER_QUOTA_MB` on the server, and download links live `DOWNLOAD_TTL_S` |
| `LOG_LEVEL` | `INFO` | stderr logging (stdout belongs to the stdio transport) |
| `CATALOG_LIVE_TTL_S` | `600` | Live block-catalog cache lifetime |

Test-only variables (`TEST_HAXCMS_DIR`, `TEST_HAXCMS_VERSION`, `TEST_KEEP_RUNTIME`) are documented
in [PLAN.md Section 4](PLAN.md) and under [Which HAXcms the tests run against](#which-haxcms-the-tests-run-against).

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

### Serving over HTTP to other people

Bound to loopback, the HTTP transport behaves like stdio: one HAXcms identity for the whole
process. It only answers requests whose `Host` is loopback (and refuses foreign browser
`Origin`s), so a web page cannot reach it through DNS rebinding. To serve anyone else, turn on per-caller auth. The server refuses to bind a
non-loopback host without it:

```bash
export HAXCMS_MCP_BASE_URL=https://haxcms.example.org
export HAXCMS_MCP_HTTP_AUTH=haxcms
export HAXCMS_MCP_PUBLIC_URL=https://mcp.example.org
haxcms-mcp --transport http --host 0.0.0.0 --port 8765 --path /mcp   # no USERNAME/PASSWORD
```

Each request must carry `Authorization: Bearer <HAXcms access token>`. The server checks the
token with HAXcms and then acts as that user, with that user's permissions. Unauthenticated
requests get `401` plus OAuth protected-resource metadata naming HAXcms as the authorization
server ([ADR-0004](docs/adr/0004-haxcms-is-the-oauth-authorization-server.md)). Over HTTP:

- URL sources must resolve to public addresses (SSRF guard, redirects re-checked, at most 4
  fetches at once, 120 s per fetch).
- Local-path sources are refused.
- `login` and `logout` are unavailable.
- Read-Only Mode still applies.
- Exports and converter files land in the caller's own folder (quota, expiry) and come back
  as a short-lived signed `download_url` served by this server, not as a server path.
- A non-loopback bind needs `PUBLIC_URL=https://...`: put TLS in front of the server.
- Repeatedly refused tokens from one address are throttled (`429`), and token checks have
  their own budget, so made-up tokens cannot use up the budget real callers' tools draw on.
- Unexpected errors reach callers without internal detail (hosts, paths, resolved IPs).

The browser sign-in flow (OAuth authorize/token endpoints) has to land in HAXcms first. Until
then, only clients that can send a static header (`claude mcp add --transport http --header
"Authorization: Bearer <jwt>" ...`) can connect, and HAXcms tokens expire after 15 minutes.
Any valid HAXcms token is accepted; tokens are not yet audience-bound to this server.

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

## Supported HAXcms

This server is a typed client of the HAXcms HTTP API (NodeJS and PHP) and is built against the OpenAPI
specs vendored in [`specs/`](specs) (identity in [`specs/VERSION`](specs/VERSION), currently
**26.8.1 @ `ad82de48`**, i.e. `haxtheweb/haxcms-nodejs` `main` rather than the npm-published
26.8.1, which predates the file API).

| HAXcms NodeJS | Status |
|---|---|
| `main` at or after the vendored commit (spec hash matches) | supported, tested nightly |
| npm `@haxtheweb/haxcms-nodejs@26.8.1` | partly works: file upload and image-writing document imports fail |
| anything else (older builds, newer builds with API changes) | best effort; you will get a warning |
| HAXcms PHP `master` (same API contract) | supported with known gaps, see below ([haxtheweb/issues#3139](https://github.com/haxtheweb/issues/issues/3139)) |

On startup the server fetches the instance's `GET /system/api/v1/openapi` and compares its hash
with the vendored spec. A difference is logged once as a warning (stderr) and reported by
`get_server_info` under `spec_compatibility` (`match`, `mismatch` or `unavailable`). It never
blocks startup and never disables a tool: most upstream spec edits are descriptions and examples.

### HAXcms PHP

[HAXcms PHP](https://github.com/haxtheweb/haxcms-php) implements the same OpenAPI contract and
stable error codes (`data.code`), so the same tools work against it. The compatibility hash is
taken over the parsed spec, so PHP's JSON rendering (with its own `info.version` and `servers`)
compares equal to the vendored YAML. Errors are mapped by `data.code` first and the English
message second, because PHP words some errors differently (a failed login is a generic
`Access denied`, still reported as `AUTH_FAILED`).

Known differences (upstream parity gaps, not MCP behavior; the PHP test leg skips these):

- PHP builds before [haxtheweb/haxcms-php#704](https://github.com/haxtheweb/haxcms-php/pull/704)
  answer HTTP 500 to every page create (`HAXCMSSite::itemFromParams` metadata bug); use
  `master` or a release that includes it
- no login rate limiting (repeated wrong passwords never answer 429)
- content is stored as sent: the NodeJS sanitiser's rewrites (`target`, `preserve-content`,
  attribute re-quoting) do not happen
- converters and document imports produce different HTML/Markdown (heading style,
  pretty-printing, PDF/PPTX/DOCX structure), and file records carry no `uuid`

To run the live suites against PHP locally (needs only the `php` 8.3 binary with gd, curl,
mbstring, dom and zip; no Apache or Docker):

```bash
HAXCMS_MCP_TEST_BACKEND=php HAXCMS_MCP_TEST_HAXCMS_PHP_DIR=/path/to/haxcms-php \
  uv run pytest -m "integration or functional"
```

### Keeping up with HAXcms

A nightly workflow ([`upstream-drift.yml`](.github/workflows/upstream-drift.yml)) fails when the
vendored specs differ from `haxcms-nodejs` `main` or when the live suites fail against it. To
reconcile:

```bash
uv run python scripts/sync_specs.py --from ../haxcms-nodejs   # specs/, VERSION, generated spec_info.py
uv run python scripts/gen_routes.py                           # client routes (ADR-0005)
uv run python scripts/gen_tools.py                            # converters
uv run python scripts/gen_tool_docs.py                        # docs/tools.md
uv run python scripts/sync_specs.py --check --from ../haxcms-nodejs   # what the nightly runs
```

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
uv run python scripts/gen_routes.py --check        # client route drift (ADR-0005)
uv run python scripts/gen_tool_docs.py             # regenerate docs/tools.md
uv run pytest --snapshot-update                    # update regression snapshots deliberately
```

### Which HAXcms the tests run against

The live suites (`integration`, `functional`, `e2e`) boot a real HAXcms and target current
**`haxtheweb/haxcms-nodejs` `main`**, not the npm-published release. The MCP relies on the
`files.json` datastore, the image file operations and the page-break rejection, none of which
`@haxtheweb/haxcms-nodejs@26.8.1` on npm has, so against that package 7 file-upload and
document-import tests fail.

```bash
git clone https://github.com/haxtheweb/haxcms-nodejs ../haxcms-nodejs
export HAXCMS_MCP_TEST_HAXCMS_DIR=$PWD/../haxcms-nodejs   # explicit; never picked up implicitly
uv run pytest -m "integration or functional"
```

With the variable unset, the harness installs `@haxtheweb/haxcms-nodejs@$HAXCMS_MCP_TEST_HAXCMS_VERSION`
from npm (default `26.8.1`). CI sets the variable to a fresh `main` checkout; the ref lives in
`HAXCMS_NODEJS_REF` at the top of `.github/workflows/ci.yml`.

The generated tool reference in [`docs/tools.md`](docs/tools.md) and the generated converters in
`src/haxcms_mcp/generated/converters.py` are checked for drift in CI.

## More documentation

- [`docs/tools.md`](docs/tools.md) — every tool with annotations, parameters and defaults
- [`CONTEXT.md`](CONTEXT.md) — the domain model this server is built on
- [`PLAN.md`](PLAN.md) / [`PROGRESS.md`](PROGRESS.md) — the build plan and the session log
- ADRs: [0001 HTTP wrapper](docs/adr/0001-http-wrapper-over-running-haxcms.md),
  [0002 generated converters](docs/adr/0002-build-time-generated-converter-tools.md),
  [0003 text anchors](docs/adr/0003-text-anchor-block-addressing.md),
  [0004 OAuth via HAXcms](docs/adr/0004-haxcms-is-the-oauth-authorization-server.md) (proposed),
  [0005 generated routes](docs/adr/0005-generate-the-route-layer-not-the-client.md)
- [HAXcms NodeJS](https://github.com/haxtheweb/haxcms-nodejs) — the instance this operates
- [Model Context Protocol](https://modelcontextprotocol.io/) — the protocol it speaks
