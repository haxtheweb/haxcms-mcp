# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Conventional Commits](https://www.conventionalcommits.org/). This changelog was
hand-written from `git log` for the initial release (PLAN T9.6).

## [Unreleased]

### Added

- Security follow-ups:
  - Site zips and exports are streamed from HAXcms under `DOWNLOAD_MAX_MB` (decoded size, so
    compressed bombs are caught) instead of being read whole into memory; a `_published`
    link from HAXcms is only followed on the instance's own `/_published/` mount.
  - Per-caller HTTP mode: every user has their own outbound budget, and
    `RATE_LIMIT_TOTAL_RPS` caps all users together.
  - `URL_SOURCES_PROXY`: an explicit egress proxy for URL sources (for networks where the
    server only reaches the internet through a proxy).
  - The last hand-built API paths (login, refresh, logout, connection-settings, the spec
    check, token verification) use the generated routes too (ADR-0005).

- Security hardening from the October 2026 audit (local sources):
  - `INPUT_ROOTS` defaults to none: local-path sources are off until the operator names a
    folder (the working directory used to be the default, and it holds the server's `.env`).
  - Hidden files/folders and key/credential files are refused even inside a root.
  - Every URL source uses the guarded streaming fetch; with private addresses allowed (stdio)
    link-local and cloud-metadata addresses are still refused.
- Security hardening from the October 2026 audit (HTTP transport):
  - Host/Origin validation on every HTTP request (DNS-rebinding protection; `421`/`403`),
    with `HTTP_ALLOWED_HOSTS` / `HTTP_ALLOWED_ORIGINS` for extra names.
  - Per-caller mode: token verification uses its own outbound budget and caches refusals;
    `AUTH_FAILURES_PER_MINUTE` throttles addresses that keep presenting refused tokens; a
    non-loopback bind requires an `https://` `PUBLIC_URL`; error details are masked.
  - Per-caller results go to per-user folders with a quota and expiry, and are returned as
    signed, short-lived `download_url`s (`GET /downloads/<token>`) instead of server paths.
  - URL fetches: total deadline and a concurrency cap; refusals no longer reveal resolved
    addresses; connection errors no longer name the internal HAXcms host.
- Security hardening from the October 2026 audit (annotations, shared state, CI):
  - Tool annotations: the three converters that write a file (`convert_html_to_docx`,
    `convert_html_to_pdf`, `convert_docx_to_pdf`) are no longer read-only, so Read-Only Mode
    refuses them; every tool that takes a `source` (which may be a URL) is open-world;
    settings writers and other tools that overwrite existing values are destructive.
  - The block-catalog cache is scoped per caller, bounded, and remembers failures for 30 s
    instead of 10 minutes; the site-lock table is bounded.
  - CI: least-privilege `permissions: contents: read`, actions pinned to commit SHAs,
    `persist-credentials: false`, and Dependabot for actions and the uv lock.

- Generated route layer ([haxtheweb/issues#3137](https://github.com/haxtheweb/issues/issues/3137)
  stretch, ADR-0005): `scripts/gen_routes.py` writes one builder per spec operation
  (`generated/system_routes.py`, `generated/site_routes.py`). `system_api.py` and
  `site_api.py` take method, path and required auth from them through `client.call()`. CI
  checks drift, and the nightly workflow regenerates from `haxcms-nodejs` `main` and
  type-checks the client.
- Per-caller auth for the HTTP transport ([haxtheweb/issues#3140](https://github.com/haxtheweb/issues/issues/3140),
  ADR-0004, proposed):
  - `HAXCMS_MCP_HTTP_AUTH=haxcms` requires each caller's own HAXcms access token. Tokens are
    verified against HAXcms, and each caller gets an isolated session.
  - OAuth protected-resource metadata names HAXcms as the authorization server.
  - `login`/`logout` answer `UNSUPPORTED` in this mode.
- The HTTP transport refuses to bind beyond loopback without auth (fail closed).
- SSRF guard for URL sources over HTTP: public addresses only, DNS pinning, redirects
  re-validated, streamed size cap. Local-path sources are refused over HTTP. Both have
  operator overrides.
- HAXcms PHP support ([haxtheweb/issues#3139](https://github.com/haxtheweb/issues/issues/3139)):
  the live suites run against a PHP checkout with `HAXCMS_MCP_TEST_BACKEND=php` (PHP built-in
  server plus a router standing in for `.htaccess`, installed through the real `install.php`),
  and CI runs them against haxcms-php `master`. Known upstream parity gaps are listed in the README.
- Errors are mapped by the stable `data.code` first (`AUTH_INVALID_CREDENTIALS`,
  `AUTH_RATE_LIMITED`); a 401 on `session/login` is always `AUTH_FAILED`.
- The spec compatibility hash is computed over the parsed document (minus `info.version` and
  `servers`), so PHP's JSON rendering of the spec matches the vendored YAML.
- Nightly `upstream-drift` workflow: vendored specs vs `haxcms-nodejs` `main`, plus the live
  suites against a fresh `main` checkout ([haxtheweb/issues#3137](https://github.com/haxtheweb/issues/issues/3137)).
- `scripts/sync_specs.py --check --from <checkout>` prints a unified diff and exits 1 on drift;
  syncing also generates `src/haxcms_mcp/generated/spec_info.py` (spec hashes).
- Startup compatibility check: the instance's `GET system/api/v1/openapi` is hashed and compared
  with the vendored spec; a mismatch is logged once and reported by `get_server_info` as
  `spec_compatibility`. README documents the supported HAXcms range.
- `create_site_from_platform` accepts the `quarto` platform.

### Changed

- Dependencies: fastmcp 4.1.2; floors for opentelemetry-api 1.45.1 (CVE-2026-114603) and
  certifi 2026.10.19 (PYSEC-2026-4320); dev-only pillow 13.

- Vendored specs refreshed to HAXcms NodeJS `main` @ `ad82de48` (new `languages` routes, `idMap` on
  save responses, md site export, auth notes on exports).
- The Drupal importer id is `drupal` (HAXcms renamed it from `drupal-book`); the old name is still
  accepted and mapped.

## [0.1.0] - 2026-10-01

Initial release. An MCP server for a self-hosted HAXcms instance (NodeJS 26.8.1), built
with FastMCP: **117 tools** (33 read-only, 8 destructive), **6 `haxcms://` resources**
and **4 prompts** over the stdio and streamable-HTTP transports, wrapping a running
instance through a typed async HTTP client (ADR-0001 — the server never touches the
database or filesystem of the instance directly).

### Added

- **Core** (`feat(core)`, `feat(ratelimit)`) — pydantic-settings configuration with
  env-only credentials; error taxonomy formatted as `[CODE] message. hint`; structured
  logging that never records tokens or passwords; read-only, error and logging
  middleware; outbound token-bucket budget (4 requests/s, burst 8) with `RETRY_MAX`
  handling; retry policy for 429 and transient failures; response-envelope unwrapping
  and error mapping; `HaxcmsClient` request pipeline with per-call timeouts; FastMCP
  server assembly and CLI (`--transport`, `--host`, `--port`, `--path`, `--version`);
  graceful shutdown closing the httpx client via the server lifespan.
- **Auth** (`feat(auth)`) — login, token refresh and site/user token acquisition;
  `login`, `logout`, `whoami` (with session age and budget stats) and
  `get_server_info` tools.
- **Sites** (`feat(sites)`) — create (blank, from skeleton, from document, from
  platform), clone, archive, list, get; theme listing and switching; site, theme and
  skeleton models with endpoint helpers.
- **Pages** (`feat(pages)`, `feat(outline)`) — outline tree with reorder, move and
  reparent; page create (single and bulk from manifests), details update (including
  the publish toggle), delete; revision list, read and restore; search; tags.
- **Content & Blocks** (`feat(content)`, `feat(blocks)`, `feat(catalog)`,
  `feat(resources)`) — block parser/serializer with text anchors and `occurrence`
  disambiguation; generic `add_block`/`replace_block`/`update_block`/`remove_block`/
  `move_block` tools; typed tools for the core blocks (paragraph, heading, image,
  video, link, list, quote, place-holder and more); bundled core block catalog with
  live merge and validation; `haxcms://catalog/blocks` and
  `haxcms://catalog/blocks/{tag}` resources.
- **Files** (`feat(files)`) — uploads from local paths (confined to `INPUT_ROOTS`),
  URLs and base64; transform, rename and delete; `add_image_from_file` composite
  (upload + place + save in one call) populating `metadata.images`/`metadata.files`.
- **Settings** (`feat(settings)`) — site info, author, theme, regions, SEO, editor,
  block permissions, platform settings and git publishing tools.
- **Imports & converters** (`feat(imports)`, `feat(converters)`,
  `build(converters)`) — document and platform import composites; converter tools
  generated from the vendored HAXcms 26.8.1 OpenAPI specs (generator drift-checked in
  CI).
- **Exports** (`feat(exports)`) — site and page export to zip, markdown, skeleton,
  html and (with Chrome on the instance) pdf/docx/epub; site templates and reusable
  skeletons; Output Directory write rules returning `{path, bytes, mimetype}`
  records — never bytes over the wire.
- **Prompts** (`feat(prompts)`) — `hax_author` (persona, save discipline, anchor
  rules, accessibility duties) and three journey prompts: `build_page_from_brief`,
  `scaffold_course_from_outline`, `import_and_polish_document`.
- **Site resources** (`feat(resources)`) — `haxcms://sites`, `haxcms://sites/{site}`,
  `haxcms://sites/{site}/outline` and `haxcms://sites/{site}/pages/{slug}`.
- **Docs** (`docs`) — README with installation (`uv tool install` / `uvx`), the full
  configuration table, Claude Code and Claude Desktop setup, HTTP mode, security
  notes and troubleshooting; generated tool reference (`docs/tools.md`, CI-checked);
  PLAN/CONTEXT/PROGRESS workspace; three ADRs; vendored OpenAPI specs; fastmcp API
  notes.
- **Tests** (`test`) — 875 tests: unit (offline, respx-mocked), integration and
  functional suites against a spawned real HAXcms 26.8.1, regression snapshots (tool
  schemas, prompt texts, request payloads), the whole-registry read-only matrix, and
  an end-to-end replay of the tutorial ("A Designerly Engagement with the World")
  over real stdio and HTTP subprocess transports; harnesses for spawning HAXcms and
  MCP subprocesses on both platforms.
- **CI** (`ci`) — GitHub Actions: lint, strict mypy and unit tests with an 80%
  coverage gate on Python 3.12 + 3.13; integration/functional/regression against a
  live HAXcms on Node 22 with a cached runtime; e2e on pull requests; drift checks
  for generated converters and tool docs.

### Fixed

Fixes landed during development, before this first release:

- client timeout enforcement and aligned pytest event-loop scopes (`be9e841`)
- `create_page` appends after its new siblings (`30750b3`)
- `are-disabled` 403 gates mapped to `FEATURE_DISABLED` (`982960f`)
- settings manifest extras guarded; author name no longer shadowed (`2c7f35b`)
- hardening pass: graceful shutdown, PLAN §5 DEBUG request line, timeout guards, log
  redaction test, read-only matrix (`ede675f`)

[0.1.0]: https://github.com/Cloudhoppr/haxcms-mcp/releases/tag/v0.1.0
