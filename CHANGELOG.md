# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Conventional Commits](https://www.conventionalcommits.org/). This changelog was
hand-written from `git log` for the initial release (PLAN T9.6).

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
