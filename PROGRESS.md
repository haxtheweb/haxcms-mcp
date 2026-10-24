# PROGRESS.md: Handoff log

This file is the only memory that survives between Sessions. The implementing agent appends one
section per Phase when the Phase's exit checklist (PLAN.md §0.5) is complete. Never delete earlier
sections. `PLAN.md` is read-only; deviations are recorded here.

Read order at the start of a Session: PLAN.md §0 → CONTEXT.md → this file → the Phase section.

## Status board

| Phase | Title | Status | Tag | Commit |
|---|---|---|---|---|
| 0 | Scaffold and CI | done | `phase-00` | see tag |
| 1 | Core client and session tools | done | `phase-01` | see tag |
| 2 | Site lifecycle tools | done | `phase-02` | see tag |
| 3 | Outline and page tools | done | `phase-03` | see tag |
| 4 | Content and block tools | done | `phase-04` | see tag |
| 5 | Files | done | `phase-05` | see tag |
| 6 | Site settings | done | `phase-06` | see tag |
| 7 | Imports and generated converters | done | `phase-07` | see tag |
| 8 | Exports | done | `phase-08` | see tag |
| 9 | Prompts, docs, hardening, e2e | done | `phase-09` + `v0.1.0` | see tag |

## Verified facts (cumulative)

Facts that PLAN.md or docs/haxcms-api-reference.md asked to "verify". One bullet each, with the
Phase that verified it and how (file:line in haxcms-nodejs, or a live-instance observation).

- (Phase 0, live) HAXcms 26.8.1 boots from the API-REF §11 recipe on Windows: `HAXCMS_ROOT` with
  trailing slash + `PORT` + `HOME`/`USERPROFILE` + git identity env vars, `node dist/app.js` from
  the npm package; ready = any HTTP status from `GET /system/api/v1/status`.
  `tests/harness/haxcms_runtime.py` implements it; proven by `tests/integration/test_p00_harness.py`.
- (Phase 0, live) `POST /system/api/v1/session/login` returns `{status:200, jwt}` (jwt has 2 dots)
  and sets the `haxcms_refresh_token` cookie; wrong password → 401.
- (Phase 0, live + spec) **`GET /system/api/v1/sites` requires bearer AND `X-HAXCMS-User-Token`.**
  Bearer-only returns 403 `{"status":403,"data":{"message":"X-HAXCMS-User-Token header is required
  for this endpoint"}}`. The 26.8.1 spec (`specs/system-spec.yaml` L322-330, `listSites`) declares
  `security: [bearerAuth, userTokenHeader]`; API-REF §2.6's "System admin reads ... user token: no"
  row is OUTDATED for list sites. The server builds its route→policy map from the bundled OpenAPI
  spec and fails closed to `authenticated` (`haxcms-nodejs src/app.js` L2034-2077,
  `readSystemApiAuthPoliciesFromOpenApiSpec` / `enforceSystemApiUserTokenPolicy`). **Phase 1+:
  treat `specs/*.yaml` security blocks, not API-REF §2.6, as the source of truth for headers.**
- (Phase 0, live) `GET /system/api/v1/session/connection-settings` with `Accept:
  application/javascript` and NO Referer returns `window.appSettings = {...}` including a valid
  `userToken` on a fresh instance with zero sites (`userToken = getRequestToken(activeUser)` is
  site-independent, `connectionSettings.js` L208). Parse: index of `window.appSettings`, then
  `json.JSONDecoder().raw_decode` from the first `{`.
- (Phase 0, live) Fresh instance: `GET /system/api/v1/sites` (bearer + user token) → `{status:200,
  data:{items: []}}`.
- (Phase 0, probes + unit tests) fastmcp 4.0.10: exceptions other than `ToolError` raised in tool
  bodies are masked BELOW the middleware chain into `ToolError("Error calling tool '<name>':
  <original str>")` with the original as `__cause__`; the error-translation middleware must unwrap
  `__cause__` (`src/haxcms_mcp/middleware/errors.py`). No `mcp.get_tools()`; use `await
  mcp.list_tools()` / `await mcp.get_tool(name)`. Details in `docs/fastmcp-notes.md`.
- (Phase 1, live probe) `GET /system/api/v1/session` with bearer → 200 with TOP-LEVEL
  `{status, authenticated, jwt, user}` — no `data` key; anonymous → 401 with top-level `message`.
  `unwrap()` therefore falls back to the whole body when `data` is absent.
- (Phase 1, spec + live) `session/user`, `status`, `system/version` all require bearer AND
  `X-HAXCMS-User-Token` per their `security:` blocks in `specs/system-spec.yaml`; anonymous → 401
  "Authentication required". `GET system/version` → `data: {"version": "26.8.0"}` — the instance
  self-reports 26.8.0 although it is installed from npm `@haxtheweb/haxcms-nodejs@26.8.1`;
  `status` reports `haxcmsVersionCurrent: "26.8.0"` and a newer `haxcmsVersionLatest`.
- (Phase 1, live probe) `GET session/refresh` returns an IDENTICAL jwt when called within the same
  second as the previous issuance — tests must assert on refresh-call counts / route hits, never on
  token inequality.
- (Phase 1, live probe) `POST session/logout` → `{status: 200, data: "loggedout"}`.
- (Phase 1, live test, T1.4 verification) `siteToken` differs per site: two created sites got
  different tokens via connection-settings + per-site Referer; a `POST items` write to site B
  carrying site A's token → 403. The same write with the correct bearer+site token → 200.
- (Phase 1, live test) Login rate limiter: repeated wrong-password logins for a THROWAWAY username
  hit 429 "Too many failed login attempts" within ≤7 attempts; the envelope mapper surfaces it as
  RATE_LIMITED with "(retry after Xs)". Use a throwaway user in tests — the limiter is per
  IP+username and would otherwise lock out the real test user for 15 minutes.
- (Phase 1, live test) Raw create-site per API-REF §3.3 (theme `clean-one`, build type `skeleton` /
  `from-skeleton`, one inline home item) works with bearer+user; raw createNode
  `POST /_sites/{site}/x/api/v1/items` accepts the single-form payload
  `{site:{name}, node:{id:null,title,location:null,duplicate:null,contents}, parent:null,
  order:null, indent:null, description:"", metadata:null}` with bearer+site token.
- (Phase 2, live probe) `POST sites` IGNORES a `site.title` key — the created site's title equals
  its machine name. The response `data` is the site's first JSONOutlineSchemaItem; the ACTUAL
  name is at `data.metadata.site.name` (also parseable from `location`/`slug`
  `/_sites/<name>/index.html`). Blank create defaults observed: license `by-sa` honoured, server
  fills `metadata.site.settings{lang:"en-US", publishPagesOn, canonical, pathauto}` and
  `logo:"assets/banner.jpg"`.
- (Phase 2, live probe) Duplicate `POST sites` name → 200: the server silently creates
  `<name>-1` (no error, does NOT return the existing site). Services must read the created name
  back from the response.
- (Phase 2, live probe) `POST sites` with an unknown theme → 400
  `{"status":400,"data":{"message":"Invalid theme supplied for site creation"}}` — but the site
  is STILL registered afterwards (phantom `_sites/<name>` appears in list sites). The MCP
  service validates against `GET themes` before the POST, so the phantom case is unreachable
  through our tools.
- (Phase 2, live probe, T2.5) `POST sites/{name}/clone` → `data:{detail:"/_sites/<new>",
  name:"<new>"}` — the new Site Name is `data.name` (detail is a fallback). `POST
  sites/{name}/archive` → `data:{name, archivedName, detail:"Site archived"}`; the archived
  folder moves to `<root>/_archived/<name>` (asserted on disk in integration).
- (Phase 2, live probe, T2.5) `GET sites/{name}` DOES include item counts: `metadata.pageCount`
  (plus `created`/`updated` ISO strings) and
  `links{self, clone, archive, download, downloadSkeleton, saveAsTemplate, siteApi}`.
- (Phase 2, live probe, T2.5 → needed in Phase 8) `POST sites/{name}/download-skeleton` →
  `data:{skeleton:{meta, site, build}}` — the skeleton JSON INLINE, not a link. `POST
  sites/{name}/save-as-template` → `data:{saved:true, name, filename:"<name>.json",
  path:"<root>\\_config\\user\\skeletons\\<name>.json", link:"/system/api//v1/skeletons/<name>"}`
  — it DOES return a link (note the double-slash quirk); the body `name` param is ignored (the
  site's own name is used); the saved skeleton then appears FIRST in `GET skeletons`.
- (Phase 2, live probe) System `GET themes` and `GET skeletons` return LISTS (API-REF §3.5 said
  "map"). Theme records carry BOTH `machineName` and `machine-name` plus
  `element/path/thumbnail/category/hidden/priority/terrible/scope/enabled/supportedPalettes`.
  Skeletons list = the 8 bundled records (`title/description/image/category/attributes/scope/
  demo-url/skeleton-url/enabled`); `default-starter` (mentioned in API-REF §9) is NOT among them
  in 26.8.1. Skeleton detail = `{meta{name, description, version, created, type, priority,
  useCaseTitle, useCaseDescription, useCaseImage, category, tags, attributes}, site{name,
  description, theme}, build{type, structure, items}}`.
- (Phase 2, live probe) Site-level reads are ANONYMOUS (site-spec.yaml global `security: []`,
  confirmed live): `GET /_sites/{site}/x/api/v1/site` (summary with
  `counts{items, publishedItems, tags, regions, files}`, `language`, `basePath`, `theme`,
  `updated`, links), `/themes` (ThemeCollection `{count, total, page, themes[]}` — active-theme
  records add `supportedPalettes`), `/themes/active`, and `/items` (public outline).
- (Phase 2, live probe) Create-from-skeleton `online-course-clean-one` → 5 pages: Syllabus,
  Lesson 1, Lesson 1: Introduction, Lesson 1: Content, Lesson 1: Conclusion; the site's
  description/theme/license come from the skeleton regardless of the requested values.
- (Phase 3, source + live) Single `POST items` (createNode.js → `itemFromParams`, HAXCMS.js
  L1815): honours `node.id`, REPLACES `metadata` wholesale (published/tags ride in the POST
  body) and always slugifies from title/location, ignoring any slug (an explicit slug needs the
  `setSlug` follow-up). **Omitting `order` leaves the prototype default 0 — every un-ordered
  single create ties and the outline falls back to title order (caught by the live suites)** —
  so `create_page` computes the append position (max sibling order + 1) itself.
- (Phase 3, source) Bulk `POST items` (`addPage`, HAXCMS.js L980): honours client-supplied ids
  (parents can be calculated ahead of time), defaults `order` to `manifest.items.length`
  (append), defaults missing slugs to `welcome`, passes `content || contents`, and with a
  string `parent` sets `page.indent` to whatever was sent (absent → the manifest omits indent).
  Response `data` is only the LAST created item (absent when every entry is `delete:true`);
  one git commit per batch; `delete:true` entries are skipped — `create_pages` therefore fills
  ids/slugs client-side and re-lists the manifest to return every created page in input order.
- (Phase 3, source) `PATCH site/outline` (saveOutline.js): items OMITTED from the payload are
  NOT deleted (only an explicit `delete:true` entry removes a page) but keep their old order —
  always send the COMPLETE manifest; response `data = {items: <full manifest>}`; Pathauto
  regenerates the slugs of every SENT item unless `metadata.overridePathauto`; client-supplied
  ids are remapped through an itemMap; `order` comes from `item.order` else the array index;
  `location` is server-controlled (under `pages/`); 403 without the outlineDesigner feature.
- (Phase 3, source + live) `setSlug` sets `metadata.overridePathauto=true`; `setTitle`
  regenerates the slug only while Pathauto is on AND overridePathauto is unset → an explicit
  slug STICKS across later title changes (asserted live); slug changes cascade to descendants;
  the `setOverridePathauto` operation's field is `overridePathauto` (boolean).
- (Phase 3, source + live) `setParent` defaults `order` to 0 (nodeDetailOperations.js) — the
  service appends (max sibling order + 1) when order is omitted. `moveUp`/`moveDown` swap order
  with the adjacent sibling; `indent` reparents under the PREVIOUS sibling; `outdent` moves to
  the grandparent right after the parent — all four verified in the live outline suite.
- (Phase 3, source) `GET items` filters (siteRouteUtils.js filterItems L1265-1310 +
  parseBooleanFromInput L450-485): `filter.published` accepts 1/true/yes/on and 0/false/no/off;
  `filter.depth` applies ONLY together with `filter.ancestor`; `filter.tags` is CSV matched
  lowercase; `filter.parent` is an exact string match against `item.parent` (an ID — resolve
  slugs first). Pagination: default `page.limit` 25, MAX 200 → callers must paginate.
- (Phase 3, source, T3.6) pageType values from the page boilerplate dirs: `default, course,
  lesson, glossary, collection, portfolio, init`; the Notion importer additionally uses
  `reading/discuss/activity/connection`.
- (Phase 3, source) Revisions (revisions.js): `{revisionId}` must be a 7-64 char hex git hash
  (revision NUMBERS are rejected); the list clamps `page.limit` to 1-200, newest first; restore
  takes no body, lands as a NEW commit and returns `{nodeId, nodeSlug, nodeTitle,
  restoredFromHash, jsonVariantLocation, hasItemMetadata, itemMetadataRestored, links}`.
- (Phase 3, source + live) `GET search` (search.js): `q` required (400 when empty), max 256
  chars; live case-insensitive substring scan per item (no index lag); default scanned fields
  `title,slug,description,tags,content`; results `{id, title, slug, location, score, snippet,
  matches, links}` sorted `-score`; anonymous callers see published items only. **The `fields`
  CSV both narrows the scanned fields AND projects the output records down to those keys
  (`projectCollection`) — with `fields` set, results carry ONLY the requested keys.**
- (Phase 3, source) `GET tags` (tags.js): `{count, total, page, tags: [{tag, count, items: []}]}`
  sorted `-count`; `items` populated only with `include=items`; pagination default 100, max 1000.
- (Phase 3, source + live) `{idOrSlug}` route params are single-segment Express params that the
  server `decodeURIComponent`s (findItemByIdOrSlug) — nested slugs (`unit-1/lesson-1`) must
  travel percent-encoded (`quote(..., safe="")`).
- (Phase 3, live) `GET content/{idOrSlug}?format=html` returns the JSON envelope HTML-wrapped in
  `<pre>` (not the raw body) — read with `format=json`; `data.body` never contains the
  `<page-break>` (stripped on save). The §5.2 Page Break rule is confirmed live: saves WITH the
  minimal `<page-break item-id title slug published="published">` prefix write and commit; per
  saveNode.js source a body WITHOUT it writes nothing and still returns 200.
- (Phase 4, live test, T4.7) The no-envelope save is a SILENT no-op: a raw `PATCH content/{id}`
  whose body lacks the `<page-break>` prefix returns a 200 item record but writes NOTHING — the
  stored body stays byte-identical (`test_p04_content_roundtrip.py`). This justifies the envelope
  guard in `set_page_content`.
- (Phase 4, live test, T4.7) An envelope WITHOUT the `published` attribute CLEARS the flag:
  `metadata.published` is False after such a save — the envelope builder must replay the item's
  current flag on every content save (it does; `build_page_break` emits `published="published"`
  only when the item's flag is truthy).
- (Phase 4, live test, T4.7) `card="card"` is stored byte-identical — no sanitisation rewrite of
  the boolean-style attribute form.
- (Phase 4, live tests, T4.7) saveNode sanitisation contract, golden-captured: every Core Block
  TAG survives storage unchanged, and the GET body equals the on-disk `pages/<id>/index.html`
  byte-for-byte. Exactly four attribute-form rewrites occur: (a) `target="_blank"` on `<a>` is
  DROPPED; (b) `preserve-content` on `<template>` (code-sample) is DROPPED; (c) the bare boolean
  `correct` on assessment `<input>`s is DROPPED (multiple-choice/true-false/short-answer/matching/
  mark-the-words/tagging lose their correctness markers in STORED content); (d) attribute VALUES
  are entity-decoded then re-escaped with only `&`→`&amp;` and `"`→`&quot;` — single-quoted JSON
  attributes (vocab-term `links`, lrndesign-timeline `events`) come back double-quoted with
  `&quot;` and raw `<p>` inside, `&lt;` inside plain values becomes raw `<`, `&amp;` stays
  `&amp;`; TEXT nodes keep their escaping. `stored_form()` in
  `tests/integration/test_p04_typed_blocks_live.py` encodes this rewrite exactly — reuse it.
- (Phase 4, live probe, T4.7) `GET schemas?filter.kind=haxProperties&filter.webcomponentName=
  self-check` DOES return data on the test instance: `{count: 1, schemas: [{id: "hax-properties",
  kind: "haxProperties", schema: {tag: "self-check", gizmo: {...}}}], links}`; `GET
  blocks/{tag}?include=haxProperties` also returns a `haxProperties` key — both live-merge routes
  work.
- (Phase 4, live) A FRESH page starts with one empty `<p></p>` block, and an empty
  `set_page_content("")` save re-seeds `<p></p>` — block indices on fresh pages are baseline+1 per
  insert (the typed-tools live suite asserts this baseline before inserting).
- (Phase 4, live) Renaming a page REGENERATES its slug from the new title (pathauto, matches the
  Phase 3 setTitle fact): the slug returned by `create_page` is stale after
  `update_page_details(title=...)` — use the rename result's slug for later slug-addressed reads.
- (Phase 5, source, CRITICAL) **The npm-published `@haxtheweb/haxcms-nodejs@26.8.1` dist is STALE**
  — it predates spec commit e969655c (`specs/VERSION` pins "26.8.1 e969655c") and lacks the whole
  files datastore/enrichment: NO uuid/width/height on upload, NO `files.json`, NO `compress` or
  `duplicate` operations, and scale/convert/sepia/black-and-white write NEW
  `files/imgops/<base>-<W>x<H>.jpg` instead of transforming in place. The sibling checkout
  `../haxcms-nodejs` is at EXACTLY e969655c and has the full API. **Every Phase 5 fact below is
  against e969655c (the sibling), NOT the npm dist.** Target the spec + sibling source, never the
  dist. See Phase 5 Deviations for the runtime-resolution change this forced.
- (Phase 5, live, e969655c) `POST files` (multipart field `file-upload`; multer `.any()` also takes
  `upload`/`file`/`files[]`) → `{file:{path, url, fullUrl, type, name, size, uuid, width, height,
  mimetype, dateCreated}}`. The uuid is REAL (deterministic `sha256(siteName:canonicalPath:size)`
  rendered in uuid form, `src/lib/siteFileUuid.js`) and width/height come from sharp — the 120x80 and
  100x60 fixture PNGs return those exact dimensions. `url`/`path` are site-relative (`files/<name>`).
  A `nodeId` multipart field loads the page but upload NO LONGER appends to `page.metadata.files`
  (#3043).
- (Phase 5, source, e969655c) `fullUrl` is ROOT-RELATIVE via `buildFilePublicUrl`
  (`src/lib/siteFileUrl.js`): single-site → `/<relPath>`; multisite →
  `<basePath><sitesDirectory>/<siteName>/<relPath>`. On the multisite test runtime that is
  `/_sites/<site>/files/<name>` (basePath `/`, sitesDirectory `_sites`). It is absolute (`http…`)
  ONLY if the instance is configured with an absolute basePath. The upload response fullUrl is bare;
  `buildFileRecord` (list/get/rename/scale/...) appends `?t=<dateCreated>` (or `&t=` if already
  queried).
- (Phase 5, source + live, e969655c) `GET files` (list) reads the `files.json` datastore (envelope
  `{schema:"HAXCMS-FILE-SCHEMA-V1", data:{path:"files", files:[...]}}`), auto-indexes on-disk files
  missing from it before returning (`reconcileMissingFromDisk`), and flags records whose disk file is
  gone in a NON-destructive `orphans` array (`flagOrphans`; files.json is not mutated for orphans).
  Records carry width/height/mimetype/dateCreated and the `?t=` fullUrl. Filters: `filter.type`,
  `filter.extension` (leading dot stripped, case-insensitive), `filter.nameContains`,
  `filter.startsWith`, plus pagination/sort/fields.
- (Phase 5, source + live, e969655c) File identity is STABLE across content changes:
  `upsertFileRecordInDataStore` (`src/siteRoutes/v1/files.js` L1005) looks up the existing uuid (by
  OLD path for rename, same path for in-place ops), rebuilds the record from disk, then overwrites
  `record.uuid = existingUuid` — "files.json owns identity, uuid stable across content changes". The
  deterministic `sha256(path:size)` uuid is only used for genuinely NEW paths (upload, duplicate).
- (Phase 5, source + live, e969655c) `PATCH files/{uuid}` (`{operation, newName?, size?, level?}`):
  `rename` → `fs.moveSync`, uuid PRESERVED (re-keyed to the new path, old record scrubbed), basename
  SANITIZED by `sanitizeFileRenameBaseName` (lowercase, `[^a-z0-9-]`→`-`, collapse runs, trim) so
  "Renamed_1"→"renamed-1", extension LOCKED (change → HTTP 400), response `{operation, source, path,
  file}`. `duplicate` → `fs.copySync` to `<base>-copy.<ext>` (collision: `-copy-2`, ...), NEW uuid,
  `{operation, source, path, file}`. `scale` (`size` xs150/sm480/md800/lg1200/xl1920, default md) →
  IN PLACE (`scaleImageInPlace`, sharp `fit:inside, withoutEnlargement:true`, re-encode same format,
  `moveSync` overwrite same path), uuid preserved; a 120x80 png scaled to `sm` stays 120x80 png.
  `compress` (`level` light90/medium70/heavy50/maximum30, default medium) → in place, uuid preserved.
  `convert-jpg` → `<base>.jpg` in the SAME dir (collision-safe `<base>_1.jpg`; jpg source re-encodes
  in place). `sepia`/`black-and-white`/`rotate-90` → in place, format/filename preserved, uuid
  preserved. NONE of the in-place ops create a `files/imgops/` file (that is the stale-dist
  behaviour). In-place responses are `{operation, path, file}`.
- (Phase 5, source + live, e969655c) `DELETE files/{uuid}` → `fs.removeSync` + git commit, then
  `FileStorage.delete(uuid)` scrubs the files.json record AND removes the uuid from every page's
  `page.metadata.files` (one manifest save); a later `get`/`list` → NOT_FOUND / absent.
- (Phase 5, live, e969655c) Error mapping: a disallowed extension on upload → HTTP 500 'File type not
  allowed' (→ UPSTREAM_ERROR), NOT 400; a rename that changes the extension → HTTP 400 (→
  INVALID_ARGUMENT).
- (Phase 5, live, e969655c) The `add_image_from_file` composite is the path that DOES populate
  `page.metadata.files`: upload (which alone no longer touches metadata.files) → insert a
  `media-image` whose `source` is the uploaded `files/<name>` url → the block insert SAVES the page →
  `saveNode` rebuilds `metadata.images` (from the media schema = the set of source urls) AND
  `metadata.files` (from a content path-scan, `FileContentScanner.rebuildPageFilesUuids`, resolving
  each `files/...` reference to its files.json uuid). Verified live: after placing two images,
  `metadata.images == {url_1, url_2}` and `metadata.files == {uuid_1, uuid_2}`.

- (Phase 6, source + live probes, e969655c) **The full saveManifest form path is UNREACHABLE at
  runtime.** `PATCH site` has two paths: the scoped-details path (body `manifest` OBJECT with the
  dash-keyed admin-UI keys) writes ONLY `manifest-title`, `manifest-metadata-site-homePageId`,
  `manifest-metadata-site-settings-sw`, `manifest-metadata-site-settings-forceUpgrade`; everything
  else falls to the full form path requiring `haxcms_form_token`, which `validateRequestToken`
  accepts only when `process.env.haxcms_middleware === "node-cli"` (`isCLI()`, HAXCMS.js L3675-3677)
  — false under any live server. Live probes: a git/tags-only manifest body → 403
  `{data:{message:'Authentication required'}}` with site.json byte-identical; git keys smuggled
  alongside `manifest-title` → 200, title written, git keys SILENTLY IGNORED. Consequence:
  `metadata.site.tags` and `metadata.site.git` are not writable through the 26.8.1 API →
  `update_site_info(tags=...)` and `configure_site_git` fail fast UNSUPPORTED.
- (Phase 6, source + live) `GET /_sites/{site}/site.json` serves the raw JSON manifest PUBLICLY (no
  `{status, data}` envelope) — the only complete settings read and the source of the `SiteSettings`
  view.
- (Phase 6, T6.5, golden-captured in `settings_payloads.json`) Wire shapes: `PATCH site/seo` takes
  TOP-LEVEL `seo` + `author` wrappers beside `site.name` (NOT `manifest.seo`), short keys inside
  (`gaID`, `publishPagesOn`, `socialLink`; `license` inside the author wrapper → stored on the
  TOP-LEVEL manifest `license`); `PATCH site/platform` takes `platform.features` NESTED (not flat);
  `PATCH site/editor` takes `platform.audience`; `PATCH site/blocks` takes `platform.allowedBlocks`
  (JSON `null` = unrestricted); scoped `PATCH site` takes `manifest.site` dash keys; `PATCH
  site/appearance` takes ONLY `manifest-metadata-theme-*` keys. `update_site_info(home_page=...)`
  needs the ITEM ID on the wire (the service pre-resolves slug → id).
- (Phase 6, source + live) `saveAppearanceSettings` normalisation: palette trimmed + lowercased; a
  bare accent color is stored as `--simple-colors-default-theme-<color>-7`; region arrays
  Set-deduped; **a theme ELEMENT change REPLACES the whole `metadata.theme` with the registry
  theme's defaults** (palette/accent/icon/banner/regions ALL reset — `set_site_theme` warns and
  takes everything in one call).
- (Phase 6, source + live) pathauto: `saveNode` regenerates the slug from the title only when
  `metadata.site.settings.pathauto === true` (STRICT) and the page has no
  `metadata.overridePathauto`; the live toggle steers a later rename both ways
  (`test_p06_settings.py`).
- (Phase 6, source + live) `saveAllowedBlocks` stores arrays deduped + SORTED, `null` as JSON null,
  and always ensures the platform container `{audience:'expert', features:{}, allowedBlocks:[]}`.
  `savePlatformSettings` REPLACES the whole features object → the service merges the passed flags
  over the current ones. `deletePage: false` → `delete_page` 403 'Delete is disabled for this site'
  → FEATURE_DISABLED (live-verified, T6.5).
- (Phase 6, live) Feature-gate 403s vary the verb but share the suffix `disabled for this site`
  ('Delete is disabled for this site', '...are disabled for this site') — the envelope mapper
  matches the suffix (commit 982960f broadened it from 'are disabled for this site').
- (Phase 6, live) `POST site/updateAlternativeFormats` takes an optional `{format}` ∈ {rss,
  sitemap, search, llms, service-worker} (omitted = regenerate ALL) → `data: true`; not
  feature-gated.
- (Phase 6, live dump-probe) Fresh-site site.json defaults: top-level keys include the JSON Outline
  Schema `author` set to `""` (NAME-COLLIDES with the parsed metadata.author view — extras must
  skip declared field names) and `location`; `metadata.site` = {created, git: {vendor: 'github',
  branch: 'gh-pages'}, license, logo, name, settings: {lang: 'en-US', publishPagesOn: true,
  canonical: true, pathauto: true}, updated} — **`homePageId` is ABSENT until the first manifest
  write** (read it with `.get()`); `metadata.theme` = the FULL registry copy (element, path, name,
  thumbnail, description, category, hidden, priority, terrible, supportedPalettes, variables {icon,
  hexCode, cssVariable}) WITHOUT `regions`; `metadata.author` = {}; `metadata.platform` =
  {audience: 'expert', features: {}, allowedBlocks: []}. Every manifest write bumps
  `metadata.site.updated` (epoch seconds) and git-commits.
- (Phase 7, live probes, e969655c) Import responses: every `actions/import-<kind>` returns
  `{items, filename}` (xlsx adds `selectedSheet` = the FIRST sheet, or the `sheet` QUERY param).
  docx method=site → one record per H1/H2 with nested `parent-slug/child-slug` slugs (H3 folds
  into its H2's content stream); method=branch → the flat H1 records only; method=page → ONE
  record titled with the filename stem holding the whole document. xlsx parent-column slugs
  resolve to the parent's server-fresh id.
- (Phase 7, T7.7, live) `build.type` strings: the service composes `"<kind> import"` and ALL five
  kinds accept it; createSite persists site.json `metadata.build` = {version: the SERVER's own
  build string ("26.8.0" on this checkout — assert structure/type only), structure: "import",
  type: "<kind> import"}. An imported site's outline is EXACTLY the document tree — no Home page
  is added.
- (Phase 7, T7.7, live) DOCX inline images materialize on BOTH import paths (import_document into
  an existing site AND create_site_from_document): the data-URI PNG lands as
  `files/<child-slug>.jpg` (server re-encodes to JPEG, 120×80 kept), is registered in
  `files/files.json` (HAXCMS-FILE-SCHEMA-V1), the body references it as `<media-image
  source="files/...">`, and the item's `metadata.files` carries the record uuid.
- (Phase 7, live) Bulk createPages stores the importer's records verbatim → branch-imported pages
  keep `indent: 0` (nesting lives in the parent refs only). `get_outline` returns a NESTED TREE;
  each bucket sorts by (order, title), so an imported order-0 root precedes the site's Home page.
- (Phase 7, T7.3, live) SSRF guard: `site/import/{platform}` with a repoUrl resolving to
  loopback/private/reserved/link-local/metadata space → 400 INVALID_ARGUMENT "Unable to fetch
  URL: URL target resolves to a private, reserved, loopback, link-local, or metadata address";
  NO env override exists. The html platform's only reachable LOCAL mode is the multipart upload.
- (Phase 7, T7.4, source + live) Spec-vs-reality (26.8.1), pinned as generator OVERRIDES:
  htmlToDocx and htmlToPdf are multipart .html/.htm uploads contra their spec JSON bodies;
  xlsxToCsv's `sheet` rides as a QUERY param; docxToPdf streams raw application/pdf with no JSON
  envelope. Chrome ops (htmlToPdf, docxToPdf) 400 with "No Chrome/Chromium executable found.
  Install Chrome or set PUPPETEER_EXECUTABLE_PATH." when Chrome is absent.
- (Phase 7, live) Exact 26.8.1 converter outputs (asserted in test_p07_converters.py): mdToHtml →
  `<h1>Title</h1>\n<p>Some <em>emphasis</em>.</p>\n`; htmlToMd uses SETEXT headings (`Title\n=====`);
  prettyHtml → 2-space indent; htmlToDocx names the file after the source stem; pptxToHtml → one
  `<div class="slide" data-slide-number="N">` per slide + a `files: {}` extra; xlsxToCsv echoes
  originalFilename/sheetNames/selectedSheet/format extras.
- (Phase 7, live) Import/converter 400s carry the message at `data.error` (not `data.message`);
  422 (openstax/plone converters) maps to INVALID_ARGUMENT with the upstream message. Legacy
  binary formats (.doc/.xls/.ppt) are refused LOCALLY at `detect_import_kind` — the server's
  OOXML importers enforce .docx + zip magic, so the upload would be doomed.
- (Phase 8, T8.5, source e969655c + live probe) `GET site/export/{format}` binary-vs-descriptor
  split: pdf/docx/epub/html → RAW binary (Content-Type + Content-Disposition attachment);
  zip/markdown/skeleton → a DESCRIPTOR JSON `{format, supportedFormats, export{rel, mediaType,
  href}, links}` whose `export.href` names the route that really produces the artifact. An
  unsupported format → 400 `{message: Unsupported site export format "<f>", supportedFormats}`.
- (Phase 8, T8.5, live) The zip two-step: `POST sites/{name}/download` → `{link:
  "/_published/<site>.zip", name}`; `/_published/` is a STATIC, UNAUTHENTICATED mount (app.js
  sendFile) → the bytes are fetched with auth="none". A two-page site zips to ~277KB / 75 entries
  (whole site folder incl. site.json, boilerplate and assets; minus node_modules/.git), PK magic.
- (Phase 8, T8.5, source) `download-skeleton` returns the skeleton INLINE `{skeleton, filename:
  "<machineName>.json"}` — API-REF §3.4 guessed `{link, name}`. Shape: `{meta{name, machineName,
  type: skeleton, ...}, site, build{type: skeleton, structure: from-skeleton, items[{id, title,
  slug, order, parent, indent, content, metadata}] with CONTENT inline, files: []}, theme,
  _skeleton}`.
- (Phase 8, T8.5, live) `save-as-template` → `{saved: true, name: machineName, filename, path
  (SERVER fs), link "/system/api//v1/skeletons/<name>"}` (the double-slash quirk Phase 2 already
  noted); it writes `<config>/user/skeletons/` which skeletonsList scans → the template appears
  in list_skeletons AND get_skeleton IMMEDIATELY.
- (Phase 8, T8.5, live) Chrome-less conversion failures on the export routes are **502** (PLAN
  T8.3 guessed 500) with `data.message` = `No Chrome/Chromium executable found. Install Chrome or
  set PUPPETEER_EXECUTABLE_PATH.` — WITHOUT the converter actions' `Unable to complete ...
  conversion:` prefix. The service re-maps any error containing "No Chrome" to UNSUPPORTED with
  the PLAN hint. docx and epub exports need NO Chrome (live-verified); only pdf does.
- (Phase 8, T8.5, source + live) `GET items/{idOrSlug}/export/{format}` — ALL eight formats
  (pdf/docx/html/md/json/yaml/xml/epub) are raw binary downloads; md/html/json/yaml/xml contain
  the page title verbatim; json/yaml/xml serialize the item summary + content string (xml root
  `<response>`, json is JSON.stringify(..., 2)). Bearer sees unpublished items; anonymous 404s.
- (Phase 8, live) The markdown site export's descriptor href → `GET v1/content?mode=concat&
  format=md` (raw text/markdown, no envelope): every page renders as `# {title}` followed by its
  content VERBATIM — raw HTML (`<p></p>`) appears inside the .md, it is not turndown-converted
  at site level (item-level md IS turndown).
- (Phase 8, live) Site html export = a single-file rendering whose `<title>` is the siteBase
  (sanitized metadata.site.name → title → site.name fallback order).
- (Phase 9, live) fastmcp Prompts API surface for tests: `client.get_prompt(name, args)` →
  `result.messages[0].content.text`; `list_prompts()` items carry `.name` and `.arguments` with
  `.required` (False for defaulted params).
- (Phase 9, source) The in-memory transport enters the server lifespan PER CONNECTION (fastmcp
  `memory.py::_enter_server_lifespan`), so a lifespan that closes the httpx client is safe under
  the fresh-server + single-connection test pattern; over stdio the lifespan shutdown runs at EOF.
- (Phase 9, live) ReadOnlyMiddleware fires BEFORE argument validation: all 84 non-read-only tools
  (derived from the LIVE registry annotations — 117 tools, 33 read-only) called with EMPTY
  arguments answer `[READ_ONLY] <tool>` with no validation error and no HTTP.
- (Phase 9, live) `StdioTransport` passes `env` wholesale to `StdioServerParameters` — on Windows
  the spawned server needs the FULL `os.environ` (`SystemRoot`); `server_env()` copies os.environ
  and layers the `HAXCMS_MCP_*` settings over it.
- (Phase 9, live) The full Appendix D replay works end-to-end over both real transports: the stdio
  subprocess completes site → page → uploads → media → links → zip export in ~18s, and the HTTP
  variant answers whoami/list_sites; the zip the subprocess wrote has PK magic and holds site.json
  under the test's OUTPUT_DIR.
- (Phase 9, measured) Unit-only coverage is 87.0% (609 tests at measurement); CI gates at 80% on
  the lint-unit job so the gate runs on both matrix legs.
- (Phase 9) PLAN §5's DEBUG request line (`METHOD path status ms`) was promised by the logging
  docstring since Phase 0 but unimplemented until the Phase 9 hardening pass — it lives in
  `HaxcmsClient._send`, logs `url.raw_path` (%2F logs as sent) and never headers; a respx-mocked
  login/echo/logout cycle at DEBUG proves password, JWT, access token and refresh cookie never
  reach a log record.

## Environment notes

- HAXcms install time / boot time on this machine: npm install of
  `@haxtheweb/haxcms-nodejs@26.8.1` ≈ 35s (warm npm cache) into `.haxcms-runtime/`; first boot of
  a session ≈ 35s (cold node + boilerplate copy), subsequent boots ≈ 1.7s; full integration suite
  (4 tests, two boots) ≈ 38s cached / ~77s including the first install.
- Phase 1 timings: live `integration or functional` (14 tests, incl. two site
  create/archive cycles) ≈ 13s warm; full `uv run pytest -m "not e2e"` (92 tests) ≈ 17s.
- Phase 3 timings: unit + regression (210 tests) ≈ 17s; live `integration or functional`
  (26 tests, ~10 site create/archive cycles) ≈ 51s warm; full `uv run pytest -m "not e2e"`
  (236 tests) ≈ 70s warm.
- Phase 4 timings: full `uv run pytest -m "not e2e"` (446 tests) ≈ 205s — 388 unit/regression +
  58 live; the Phase 4 live suites (31 integration + 1 functional, each integration test on its
  own throwaway site) dominate.
- Phase 7 timings: unit + regression (602 tests) ≈ 76s; live integration + functional (114 tests:
  110 passed, 4 skipped) ≈ 252s; registry now 112 tools.
- Phase 8 timings: unit + regression (641 tests) ≈ 93s; live integration + functional (123 tests:
  119 passed, 4 skipped) ≈ 284s; the Phase 8 live suites alone (8 integration + 1 functional)
  ≈ 32s warm; registry now 117 tools.
- Node version used: v22.23.3 (npm 10.9.9); system Python 3.13.6, project pinned 3.12
  (`.python-version`), uv 0.8.4.
- fastmcp version pinned: `==4.0.10` (pyproject), mcp SDK v2 types via `fastmcp.mcp_types`.
- Windows/PowerShell: multi-line commit messages go through `.git/COMMIT_MSG_TMP` + `git commit -F`
  because PowerShell 5.1 mangles embedded double quotes in native-exe args. Keep `"` out of commit
  messages. Write the message file with the editor/Write tooling, NOT `Set-Content -Encoding utf8`
  (PS 5.1 adds a BOM that ends up inside the commit subject; amend with `git commit --amend -F` if
  it happens).
- Shell: the Bash tool (Git Bash) is the reliable workhorse for git/pytest one-liners — it was
  rejected once early in the Phase 0 session but every session since has used it throughout.
  PowerShell 5.1 cannot chain with `&&` (parse error; use `;` + `if ($?)` or the Bash tool), and
  the Bash tool blocks foreground `sleep` (use run_in_background / Monitor for waits). Throwaway
  probe scripts at the repo root ARE picked up by `ruff check .` — delete them before the gates.
- Python `subprocess.run(..., text=True)` decodes child output with the locale codepage
  (cp1252 here) unless `encoding="utf-8"` is passed — UTF-8 pytest output comes back as
  phantom mojibake. The harness always passes `encoding="utf-8"`.
- pytest-asyncio: with `asyncio_default_fixture_loop_scope = "session"`, async TESTS must also run
  on the session loop (`asyncio_default_test_loop_scope = "session"` in pyproject). A
  function-loop test awaiting a session-loop-bound fixture (the fastmcp in-memory `Client` task
  group in the `mcp` fixture) deadlocks with ZERO cpu usage and no error — diagnosed with
  `uvx py-spy dump --pid <pytest pid>`. py-spy is not a project dependency; use `uvx` on demand.
- httpx gotcha: `client.build_request(..., timeout=None)` DISABLES the timeout (the client-level
  default only applies when the argument is omitted). `HaxcmsClient.request` must only forward
  `timeout` when it is not None.
- A killed integration run orphans the harness node process and its `%TEMP%\haxcms-mcp-rt-*` /
  `haxcms-mcp-home-*` dirs; clean them up manually (taskkill /F /T /PID + remove the specific
  dirs). The auto-mode classifier denies wildcard TEMP sweeps — name the resolved paths.
- PowerShell `Start-Process -ArgumentList` splits `-m "integration or functional"` into separate
  arguments (pytest dies with `file or directory not found: or`). Run pytest directly via the
  PowerShell tool with run_in_background + `Out-File -Encoding utf8` instead.
- pytest-timeout is NOT installed: a `--timeout=N` flag fails pytest argument parsing. Hangs are
  guarded by the loop-scope settings (see above) and diagnosed with `uvx py-spy dump`.
- **Test runtime resolution (Phase 5+):** `tests/harness/haxcms_runtime.py::_test_haxcms_dir()` now
  auto-prefers the sibling checkout `../haxcms-nodejs` (at e969655c) over the npm dist when present,
  because the npm-published 26.8.1 dist is stale (see Verified facts). `HAXCMS_MCP_TEST_HAXCMS_DIR`
  still overrides; with no sibling (e.g. CI) it falls back to the npm dist. `ensure_haxcms()` runs
  `npm install` inside the sibling on first use (creates `../haxcms-nodejs/node_modules` +
  `package-lock.json`; 812 packages ≈ 41s once) — deps only, NO source edits (user-approved). Boot
  from the checkout ≈ 35s cold. The repo/CI never set `HAXCMS_MCP_TEST_HAXCMS_DIR`.
- Phase 5 timings: full `uv run pytest -m "not e2e"` (511 tests) ≈ 240s — 443 unit/regression + 68
  live (58 Phase 0-4 + 10 Phase 5); first e969655c run for Phases 0-4, no regressions. The Phase 5
  live suites alone (9 integration + 1 functional) ≈ 32s warm / ~64s including a cold boot.
- Phase 6 timings: full `uv run pytest -m "not e2e"` (596 tests) ≈ 281s — 513 unit/regression + 83
  live; the Phase 6 live suites alone (11 integration + 3 git + 1 functional) ≈ 43s warm.

---

## Phase template (copy for each Phase)

### Phase N: <title>

**Session:** fresh | shared with Phase M (compacted between)
**Completed:** YYYY-MM-DD, tag `phase-NN`, final commit `<sha>`

**Built**
- bullet per module or tool group, with paths

**Tests added**
- unit: files and count
- integration: files and count
- regression: snapshot files touched
- functional: files and count
- full regression rerun command and result

**Verified facts** (also copied into the cumulative list above)
- ...

**Deviations from PLAN.md**
- what, why, and what the next Phase must know

**Known gaps / follow-ups**
- ...

**Notes for the next Session**
- anything that saved time or cost time

---

### Phase 0: Scaffold and CI

**Session:** fresh (continued in-session after two context compactions; subagent-per-Phase protocol
replaced by sequential in-session execution — see Deviations)
**Completed:** 2026-09-30, tag `phase-00`, final commit: see tag

**Built**
- `pyproject.toml`: uv package, Python 3.12, `fastmcp==4.0.10`, httpx, pydantic v2,
  pydantic-settings, lxml, pyyaml, anyio; dev: pytest(+asyncio auto mode, +cov), respx, syrupy,
  ruff (line-length 100; E,F,W,I,UP,B,SIM), mypy strict + pydantic plugin; script
  `haxcms-mcp = haxcms_mcp.__main__:main`; markers unit/integration/functional/regression/e2e/
  needs_chrome/slow/network.
- `src/haxcms_mcp/config.py` — `Settings` (env prefix `HAXCMS_MCP_`, `.env`, extra=ignore), all
  PLAN §4 vars; BASE_URL normalisation (strip, require http(s)://, strip trailing /);
  `input_roots: Annotated[list[Path], NoDecode]` split on `os.pathsep` (default `[cwd]`).
- `src/haxcms_mcp/errors.py` — `ErrorCode(StrEnum)` (13 codes), `HaxcmsMcpError` with
  `.formatted` → `[CODE] message. hint`.
- `src/haxcms_mcp/logging.py` — stderr-only logging (stdio-safe; `Context.info()` is deprecated in
  fastmcp 4, SEP-2577), idempotent `configure_logging`, `get_logger`.
- `src/haxcms_mcp/server.py` — `build_server(settings)`; middleware order ReadOnly → ToolLogging →
  ErrorTranslation (first added = outermost); one tool `get_server_info` (read-only annotated).
- `src/haxcms_mcp/__main__.py` — argparse CLI (`--transport stdio|http`, `--host/--port/--path`,
  `--log-level`, `--version`); config errors → stderr + exit 2.
- `src/haxcms_mcp/middleware/{read_only,logging,errors}.py` — see verified facts for the
  `__cause__`-unwrapping requirement in errors.py. Logging middleware logs argument KEYS only
  (never values — credentials).
- `docs/fastmcp-notes.md` — 11 sections of empirically probed fastmcp 4.0.10 APIs.
- `scripts/sync_specs.py` (`--from <checkout>` | `--tag <ref>`) + vendored `specs/`:
  system-spec.yaml, site-spec.yaml from haxcms-nodejs 26.8.1 @ e969655c; `specs/VERSION`.
- `tests/harness/haxcms_runtime.py` — installs the npm package into `.haxcms-runtime/` (or uses
  `HAXCMS_MCP_TEST_HAXCMS_DIR`), boots an isolated instance per API-REF §11, records
  install/boot seconds, teardown via `taskkill /F /T` (win) / `killpg` (posix) + rmtree unless
  `HAXCMS_MCP_TEST_KEEP_RUNTIME`. Helpers: `site_dir`, `read_site_json`, `read_page_html`.
- `tests/harness/mcp_client.py` — `McpTestClient` (call/call_error/list_tool_names/read_resource)
  over the fastmcp in-memory `Client`.
- `tests/harness/snapshots.py` — canonical-JSON snapshots under
  `tests/regression/snapshots/*.json`; created on first run, updated with syrupy's
  `--snapshot-update` flag; mismatch → unified diff AssertionError.
- `tests/conftest.py` — fixtures `haxcms` (session), `settings`, `mcp`; `network`-marker skip
  unless `HAXCMS_MCP_TEST_NETWORK=1`.
- `.github/workflows/ci.yml` — `lint-unit` (ubuntu, py3.12+3.13: ruff, ruff format, mypy, unit +
  coverage), `integration` (node 22, `.haxcms-runtime` cache keyed on specs/VERSION +
  pyproject.toml, `pytest -m "not e2e and not unit"`), `e2e` (PRs to main only).
- `README.md` stub; directory placeholders for all PLAN §3 modules.

**Tests added**
- unit: `test_p00_settings.py`, `test_p00_errors.py`, `test_p00_server_boot.py` — 19 tests.
- integration: `test_p00_harness.py` — 4 tests (boot+disk layout, status, login/list-sites incl.
  user-token fact, teardown removes runtime dir).
- regression: `test_p00_snapshots.py` + `tests/regression/snapshots/tool_schemas.json`
  (`get_server_info` only).
- functional: none (PLAN: no user-facing feature yet).
- full rerun: `uv run pytest -m "not e2e"` → all green (see commit).

**Verified facts** — see cumulative list above (all Phase 0 bullets).

**Deviations from PLAN.md**
- §0.3 one-subagent-per-Phase protocol NOT followed: Agent spawning was denied by the permission
  system. All Phases run sequentially in this Session; this file remains the handoff record and
  gets a full entry per Phase regardless.
- Bash tool rejected by user → PowerShell for everything. Commit messages avoid `"` and go via
  `git commit -F .git/COMMIT_MSG_TMP`.
- `client`/`site`/`page` conftest fixtures deferred to Phases 1-3 (they wrap modules that do not
  exist yet); Phase 0 ships `haxcms`/`settings`/`mcp` only.
- Regression snapshots are plain JSON (PLAN §6.4 names one file,
  `tests/regression/snapshots/tool_schemas.json`), not syrupy `.ambr`; syrupy's `--snapshot-update`
  flag is reused (defining our own addoption collides with the plugin).
- `ErrorCode` is a `StrEnum` (ruff UP042), not `(str, Enum)`.

**Known gaps / follow-ups**
- API-REF §2.6 header matrix is wrong for `listSites` (needs user token). Later Phases must check
  each route's `security:` block in `specs/system-spec.yaml` / `specs/site-spec.yaml` before coding
  the header matrix into `HaxcmsClient.request(auth=...)`.
- e2e workflow exists but the e2e suite is empty until Phase 9.
- `.haxcms-runtime/` npm cache is gitignored; first CI/local run pays the install cost.

**Notes for the next Session**
- Run integration with `uv run pytest -m integration -q -s` to see `[harness]` install/boot timings
  on stderr.
- The permission classifier intermittently times out ("qwen ... temporarily unavailable"); retry
  the same command after a minute, or do Write/Edit work meanwhile.
- fastmcp masking gotcha (see verified facts) will bite any middleware work in Phase 1 — read
  `docs/fastmcp-notes.md` §3 first.

---

### Phase 1: Core client and session tools

**Session:** shared with Phase 0 (compacted several times)
**Completed:** 2026-09-30, tag `phase-01`, final commit: see tag

**Built**
- `src/haxcms_mcp/client/budget.py` — `OutboundBudget` token bucket (rate/capacity/max_wait from
  settings, injectable clock+sleep, negative-reservation queueing, `BudgetStats`
  tokens/waits/denials); denial → RATE_LIMITED with `details.retry_after_s` and a hint naming the
  `HAXCMS_MCP_RATE_*` env vars.
- `src/haxcms_mcp/client/retry.py` — `RetryPolicy` + `with_retry`: 429 sleeps Retry-After
  (cap 60s, default 2s) up to retry_max; 502/503/504 + connection errors retry GET/HEAD only on
  0.5/1/2s backoff; POST/PATCH/DELETE never retried on transient; TimeoutException → TIMEOUT,
  other TransportError → UPSTREAM_ERROR; `on_retry` hook re-charges the budget between attempts.
- `src/haxcms_mcp/client/envelope.py` — `response_message`, `is_invalid_bearer`,
  `error_from_response` (exact upstream messages kept verbatim, full mapping table per PLAN §2.3,
  429 appends "(retry after Xs)"), `unwrap` (falls back to the whole body when there is no `data`
  key — GET /session is shaped that way) and `unwrap_full` (keeps jwt/link/id/slug extras).
- `src/haxcms_mcp/client/auth.py` — `parse_app_settings` + `AuthManager`: login stores jwt and
  `haxcms_refresh_token` cookie; proactive refresh at 12 of 15 minutes; reactive refresh once on
  403 "Invalid bearer token"; refresh never sends Origin/Referer and rotates the cookie; explicit
  logout sets a `_logged_out` flag suppressing auto-login until an explicit login; userToken
  cached once, siteTokens per site via connection-settings + Referer `{base}/_sites/{site}/`.
- `src/haxcms_mcp/client/__init__.py` — `HaxcmsClient`: one `httpx.AsyncClient(base_url,
  timeout)` + AuthManager + budget + policy; `request(method, path, auth=none|bearer|bearer+user|
  bearer+site, site, timeout, accept, headers, no_retry)`; `sys()` / `site_path()` builders;
  `get_json/post_json/patch_json/delete_json` (unwrapped), `*_full` variants, `download()` bytes.
- `src/haxcms_mcp/client/system_api.py` — typed helpers: login/refresh/logout (auth=none,
  no_retry), session (bearer), session_user/status/version/list_sites (bearer+user).
- `src/haxcms_mcp/models/common.py` (`Envelope`, `PageInfo`), `models/site.py` (`SiteListEntry`,
  `SiteList` with `from_api` mapping the `metadata.site` shape).
- `src/haxcms_mcp/tools/_common.py` (`tool_annotations`, `resolve_site`), `tools/auth.py` —
  the four Session Tools; `server.py` registers them. `get_server_info` probes live version and
  status best-effort (`version_error`/`status_error` instead of failing).

**Tests added**
- unit: `test_p01_budget.py` (8), `test_p01_retry.py` (11), `test_p01_envelope.py` (16),
  `test_p01_auth.py` (13, respx + captured fixture), `test_p01_client.py` (10) — 58 new;
  `test_p00_server_boot.py` updated for the four-tool registry.
- integration: `test_p01_live_auth.py` (7) — lifecycle incl. forced refresh and logout,
  session/status/version/list endpoints, whoami tool, live get_server_info, wrong password,
  rate limiter (throwaway username), per-site tokens + wrong-site 403 (creates/archives two sites
  with raw calls per API-REF §3.3).
- regression: `test_p01_snapshots.py` + `auth_header_matrix.json` (headers per auth mode);
  `tool_schemas.json` regenerated for four tools.
- functional: `test_p01_login_journey.py` (3) — login journey, env-credentials whoami, read-only
  mode blocks login but allows whoami.
- fixtures: `tests/fixtures/connection_settings.js` captured from the live 26.8.1 instance.
- full rerun: `uv run pytest -m "not e2e"` → green (92 tests; see tag).

**Verified facts** — see the cumulative list (all Phase 1 bullets), including the T1.4
site-token verification (differs per site; wrong-site token → 403).

**Deviations from PLAN.md**
- login/refresh/logout use `no_retry=True`: PLAN's retry policy would sleep the Retry-After of a
  429 (up to 15 min on the login limiter) inside an interactive tool call; surfacing RATE_LIMITED
  immediately with the retry-after in the message is the usable behaviour. Data calls keep the
  full policy.
- `whoami` after explicit `logout` fails AUTH_REQUIRED even with env credentials (the
  `_logged_out` flag) — required to satisfy both PLAN Phase 1 stories (integration: logout →
  whoami fails; functional: env credentials → whoami works without login).
- `get_server_info` payload grew `haxcms` (version/status probe) and `no_auth` keys vs the Phase 0
  stub; tool-schema snapshot updated deliberately.
- One extra fix commit beyond PLAN's list: `fix(core): enforce client timeout and align event
  loop scopes` — `build_request(timeout=None)` disabled all httpx timeouts, and pytest-asyncio
  needed `asyncio_default_test_loop_scope = "session"` (function-loop tests deadlocked silently
  against the session-loop `mcp` fixture; diagnosed with `uvx py-spy dump`).
- Commit ordering follows PLAN exactly; note the auth-commit unit tests import `HaxcmsClient`, so
  the tree is only fully green from the pipeline commit onward (PLAN's own order entangles them).

**Known gaps / follow-ups**
- The live suite creates and archives two sites per run (test_site_tokens...); if a run is killed
  mid-test, orphan node processes/temp dirs remain (see Environment notes).
- `resolve_site` exists but is unused until Phase 2 tools arrive.

**Notes for the next Session**
- Phase 2 imports: `HaxcmsClient.request/get_json/post_json/...`, `system_api`, `models`,
  `tools/_common.py` helpers, and the conftest `client`/`mcp` fixtures — all ready.
- Check each site route's `security:` block in `specs/site-spec.yaml` before choosing the auth
  mode (API-REF §2.6 was already wrong once for listSites).
- The permission classifier ("qwen ... temporarily unavailable") still times out intermittently;
  retry after a minute or do Write/Edit work meanwhile.

---

### Phase 2: Site lifecycle tools

**Session:** shared with Phases 0-1 (compacted several times)
**Completed:** 2026-09-30, tag `phase-02`, final commit: see tag

**Built**
- `src/haxcms_mcp/models/theme.py` — `Theme`: one flexible record covering both the system
  registry shape (`element/path/thumbnail/category/hidden/priority/terrible/scope/enabled`) and
  the site-level shape (`machineName/name/description/active/screenshot/supportedPalettes`);
  machine-name fallback chain `machineName` → `machine-name` → `element`; string `category`
  normalised to a list.
- `src/haxcms_mcp/models/skeleton.py` — `SkeletonMeta` (maps BOTH the flat list record and the
  detail `meta` object; `title` falls back to `useCaseTitle`; `image` to `useCaseImage`;
  `demo-url`/`skeleton-url` → snake_case) and `Skeleton` (`meta`/`site`/`build`/`theme`,
  tolerant of missing sections).
- `src/haxcms_mcp/models/site.py` — added `SiteCounts`, `SiteSummary` (public `GET site`),
  `SiteInfo` (`GET sites/{name}`, `page_count` property over `metadata.pageCount`) and
  `SiteDetail` (the merged get_site view, plus an optional `warnings` list used by create/get);
  `SiteListEntry.from_api` now strips the heavy nested site.json keys
  (`theme/build/node/platform/metadata`) from list results but keeps scalars (author, license).
- `src/haxcms_mcp/models/common.py` — `dump_model` (`mode="json"`, `exclude_none=True`): the
  single place implementing the PLAN §5 result-serialisation convention.
- `src/haxcms_mcp/client/system_api.py` — `site_info`, `create_site`, `clone_site`,
  `archive_site`, `list_themes` (all bearer + user token), `list_skeletons`, `get_skeleton`
  (bearer only) — exactly per the spec `security:` blocks.
- `src/haxcms_mcp/client/site_api.py` — NEW module: `site_summary`, `list_site_themes`,
  `active_theme`, all `auth="none"` (public reads; verified anonymous 200s).
- `src/haxcms_mcp/client/envelope.py` — `unwrap_dict` / `unwrap_list` typed unwrappers
  (UPSTREAM_ERROR on shape drift) keeping mypy strict honest about `data` shapes.
- `src/haxcms_mcp/services/sites.py` — `validate_site_name` (tutorial hint verbatim: names
  cannot contain spaces; use - or _), pure `build_home_item` / `build_create_payload` (injectable
  item ids → deterministic goldens), `list_sites`, `get_site` (info+summary merge; summary
  failure degrades to a warning), `create_site` (theme validated against the LIVE registry
  before any POST; hidden allowed with warning; actual name read back from
  `metadata.site.name`; title pass-through with an upstream-ignores warning),
  `create_site_from_skeleton` (name defaults to the skeleton machine name), `clone_site`
  (`data.name`, detail-path fallback, UPSTREAM_ERROR when neither), `archive_site`,
  `list_themes`, `list_skeletons`, `get_skeleton`. Module docstring records every live quirk it
  depends on.
- `src/haxcms_mcp/tools/sites.py` — the nine tools, registered in `server.py` (13 tools total):
  reads read-only-annotated; create/create-from-skeleton/clone `idempotent=False`;
  `archive_site` `destructive=True`. Docstrings are the agent manual (machine-name rules,
  duplicate-name warning contract, CC license codes, skeleton categories as journey types,
  archive semantics). `site` args fall back to the Default Site via `resolve_site`.
- `tests/harness/site_reads.py` — `public_items` / `public_titles`: anonymous outline reads used
  by the live suites until Phase 3 page tools exist.

**Tests added**
- unit: `test_p02_site_name_validation.py` (22), `test_p02_create_payload.py` (10),
  `test_p02_models.py` (11), `test_p02_sites_service.py` (20, respx mocks built from the probe
  shapes) — 63 new; `test_p00_server_boot.py` gained the 13-tool registry assertion and the
  Phase 2 annotation-matrix test.
- integration: `test_p02_sites.py` (5) — full lifecycle incl. the `_archived/` disk assertion,
  duplicate `<name>-1` behaviour, invalid theme rejected before any write (no phantom),
  theme/skeleton reads, skeleton journey pages.
- regression: `test_p02_snapshots.py` + `create_site_payloads.json` (blank defaults / blank
  custom / from-skeleton goldens); `tool_schemas.json` regenerated for 13 tools.
- functional: `test_p02_new_user_journey.py` (1) — the Appendix D tutorial through Tool calls
  only, ending with clone + archive through the destructive tool path.
- full rerun: `uv run pytest -m "not e2e"` → 163 passed in ~38s (live suites ~25s warm).

**Verified facts** — see the cumulative list (all Phase 2 bullets): title ignored on create;
duplicate → silent `-1` suffix; invalid-theme 400 + phantom registration; clone `data.name`;
archive → `_archived/`; `GET sites/{name}` has `metadata.pageCount`; download-skeleton inline
skeleton (Phase 8); save-as-template link + double-slash quirk (Phase 8); themes/skeletons are
lists; site-level reads anonymous; skeleton create → 5 course pages, skeleton wins.

**Deviations from PLAN.md**
- `McpTestClient.call`/`call_error` now take the tool name POSITIONAL-ONLY — `create_site`'s
  `name` argument collided with the harness keyword signature (TypeError in the functional run).
- `get_site` degrades a failing public-summary read into a `warnings` entry instead of failing
  (the system info alone is still a useful answer); `create_site` surfaces hidden-theme,
  duplicate-name and ignored-title situations the same way.
- `create_site` sends `site.title` verbatim when given but warns that upstream ignores it;
  setting a real title needs the Phase 6 PATCH-site (update_site_info) route — until then the
  title parameter is effectively decorative.
- `license=None` (PLAN signature) resolves to `by-sa` in the service — the value the dashboard
  sends on create (API-REF §3.3 payload).
- `unwrap_dict`/`unwrap_list` extend the envelope module (not named in PLAN §2.3) — required for
  mypy strict and for the list-shaped themes/skeletons responses.
- `clone_site` returns `{name, site}` and `archive_site` `{name, archived_name, detail}`
  (snake_case-normalised) instead of the raw upstream dicts; `list_sites` tool returns
  `{count, sites}` wrappers for cheap agent sanity checks.
- PLAN's blank-payload default `first_page_content="<p></p>"` kept exactly (an earlier
  friendlier default was reverted before commit to stay PLAN-exact).

**Known gaps / follow-ups**
- `client/site_api.py`'s `list_site_themes` / `active_theme` helpers exist but are not exposed
  as tools — PLAN's Phase 2 inventory has only the system-level `list_themes`; revisit in
  Phase 6 (settings) if a site-theme tool is wanted.
- The upstream phantom-site quirk (invalid-theme 400 still registers the site) is only AVOIDED
  by client-side validation; a raw 400 from a future code path could still leave one behind.
- Site names are validated client-side but the server also accepts other characters; if a future
  HAXcms relaxes machine names, `SITE_NAME_RE` is the single place to adjust.

**Notes for the next Session**
- The services/sites.py pattern is the template for Phases 3-4: pure payload builders (goldened)
  + async service functions returning models/snake_case dicts + thin tools that `dump_model`.
- Phase 3 writes (`POST/PATCH items`) need `auth="bearer+site"` with `site=` (per-site token
  verified Phase 1); anonymous outline reads for test assertions live in
  `tests/harness/site_reads.py`.
- The PLAN §6.2 `site`/`page` conftest fixtures are still absent; Phase 2 used per-test unique
  names + archive-in-finally (integration) and fixed tutorial names (functional, fresh instance
  per session makes that safe). Phase 3 should finally add the `site` fixture.
- Live-instance counts to remember: 16 themes, 8 bundled skeletons (no `default-starter`),
  version self-reports 26.8.0.

---

### Phase 3: Outline and page tools

**Session:** shared with Phases 0-2 (compacted several times)
**Completed:** 2026-09-30, tag `phase-03`

**Built**
- `models/item.py` (`Item`, `ItemCollection`), `models/revision.py` (`Revision`,
  `RevisionDetail`) — snake_case models with `from_api` constructors.
- `client/site_api.py` Phase 3 helpers: `list_items`, `get_item`, `create_item`,
  `update_item` (single-operation PATCH), `delete_item`, `save_outline`, `list_revisions`,
  `get_revision`, `restore_revision`, `search`, `list_tags`.
- `services/outline.py` — `fetch_all_items` (paginates GET items, max limit 200),
  `resolve_parent_id`, `build_outline` (tree sorted by `(order, title)`), pure
  `build_reorder_payload` (complete-manifest PATCH body; goldened).
- `services/pages.py` — `find_page` (NOT_FOUND + did-you-mean hints), `list_pages`,
  `create_page` (computes append order; setSlug/setPublished follow-ups), `create_pages`
  (bulk, client-side ids/slugs, re-lists the manifest), pure `build_detail_operations`
  (setSlug LAST; goldened), `update_page_details`, `delete_page`, revisions
  (list/get/restore with hex-hash validation), `search_site`, `list_tags`.
- `tools/outline.py` (5 tools: get_outline, reorder_pages, move_page, set_page_parent,
  indent/outdent via move_page) and `tools/pages.py` (11 tools: list_pages, get_page,
  create_page, create_pages, update_page_details, delete_page, list_page_revisions,
  get_page_revision, restore_page_revision, search_site, list_tags) → `server.py` now
  registers 29 tools.
- `tests/conftest.py` gained the PLAN §6.2 fixtures: `site` (function-scoped throwaway
  `mcp-t-<8 hex>` clean-one site, archived on teardown) and `page` (fresh "Test Page" Item
  in `site`).

**Tests added**
- unit: `test_p03_outline_tree.py` (14), `test_p03_reorder_payload.py` (15),
  `test_p03_pages_service.py` (24, respx) — 53 new; `test_p00_server_boot.py` updated for
  the 29-tool registry + Phase 3 annotation matrix.
- integration: `test_p03_pages.py`, `test_p03_outline.py`, `test_p03_revisions.py`,
  `test_p03_search_tags.py` (4 files, 4 tests — full lifecycle each).
- regression: new goldens `reorder_payload.json`, `detail_operations.json`;
  `tool_schemas.json` regenerated for 29 tools.
- functional: `test_p03_add_and_rename_page.py`, `test_p03_structure_course.py` (2 files,
  2 tests — the Appendix D tutorial stories).
- full rerun: `uv run pytest -m "not e2e"` → 236 passed in 69.53s (210 unit/regression;
  26 live).

**Verified facts** — see the cumulative list (all Phase 3 bullets): itemFromParams
order-0/metadata-wholesale/slug-ignore behaviour; addPage bulk defaults; saveOutline
complete-manifest rule; setSlug → overridePathauto; setParent order 0; move/indent/outdent
semantics; GET items filter quirks; pageType vocabulary; revision hash rules; search
fields-projection quirk; tags shape; percent-encoded nested slugs; format=html `<pre>`
envelope + Page Break rule confirmed live.

**Deviations from PLAN.md**
- One EXTRA commit beyond PLAN's list: `30750b3 fix(pages): create_page appends after
  siblings` — the live suites caught that omitting `order` on single creates leaves the
  prototype default 0 (all pages tie → outline goes alphabetical); `create_page` now
  fetches the manifest and computes max-sibling-order + 1. Cost: one extra GET per single
  create (bulk path unaffected).
- `create_page`'s setPublished follow-up only fires for `published=False` (the POST body
  already carries `metadata.published`; skipping it for the default `True` avoids a
  redundant git commit per page).
- The revisions integration test reads content with `format=json` — `format=html` returns
  the JSON envelope `<pre>`-wrapped (live discovery).

**Known gaps / follow-ups**
- `create_pages` (bulk) does not fill `indent` for nested entries — upstream `addPage`
  leaves it undefined when `parent` is a string id, so the manifest omits the key. Tree
  building uses parent links, so tools are unaffected; Phase 4's page-break serializer
  writes `depth="<indent>"` — revisit there if indent fidelity matters.
- `move_page` covers moveUp/moveDown/indent/outdent; a direct "move to arbitrary position"
  is `reorder_pages`/`set_page_parent` territory (documented in the tool docstrings).

**Notes for the next Session**
- Phase 4 content saves should reuse the raw `PATCH content` pattern from
  `tests/integration/test_p03_revisions.py` (minimal `<page-break item-id title slug
  published="published">` prefix; API-REF §5.2) until the page-break builder lands.
- The `site`/`page` conftest fixtures exist now — Phase 4+ integration tests get a clean
  site per test for free (each costs one create/archive cycle ≈ 4s).
- Search results with `fields` set are PROJECTED (only the requested keys come back) —
  tool docstrings must not promise full records when `fields` is passed.

---

### Phase 4: Content and block tools

**Session:** shared with Phases 0-3 (compacted several times)
**Completed:** 2026-10-01, tag `phase-04`

**Built** (8 commits, exactly the PLAN Phase 4 list)
- `services/content/page_break.py` — pure `build_page_break(item)` (§5.2 attribute set:
  item-id/title/slug always; `published="published"` only when the item's flag is truthy; depth,
  parent, description, hide-in-menu, page-type, tags list→CSV, related-items, image, icon,
  accent-color, developer-theme, override-pathauto; values HTML-escaped) + `save_content`
  (fresh get_item → envelope + body → PATCH content → re-GET).
- `services/content/parser.py` / `serializer.py` — lxml block parsing (`parse_blocks` →
  `Block{index, tag, attributes, text, html}`; bare top-level text wrapped; slotted children
  preserved; boolean attributes kept) and serialisation; round-trip goldens vs the five fixture
  pages in `tests/fixtures/pages/` (tutorial_finished, grid_plate, quiz, bare_text, empty).
- `services/content/anchors.py` — anchor resolution: text substring, selector (`tag`,
  `tag[attr*=value]`), auto-detection, `occurrence` disambiguation; NOT_FOUND payloads carry
  did-you-mean candidates, ambiguous anchors return the match list.
- `services/content/service.py` + `blocks.py` + `services/locks.py` — `get_page_content`,
  `set_page_content` (per site+page async lock, envelope from a FRESH item, media schema, PATCH,
  re-GET), `get_page_blocks`; block ops `insert_block` (append/prepend/before/after × anchors),
  `replace_block`, `remove_block`, `move_block`, `update_block_attributes`, `set_block_text`,
  `wrap_text_with_link` — every op saves through the envelope path and returns
  `BlockOpResult{operation, saved, affected, block_count, html, blocks}`; one git revision per
  op (live-asserted via `list_page_revisions` totals).
- `services/catalog/` — 31 bundled `bundled/<tag>.json` records (one per Appendix B Core Block,
  extracted from the haxcms-nodejs public build with `scripts/extract_hax_properties.py`),
  `hax_properties.py` normaliser, `CatalogService` with `list_blocks` (summaries + category),
  `get_block_schema` (merged record) and `validate(tag, attributes)` (unknown attributes
  rejected WITH the known list); live merge via `GET blocks`, `GET blocks/{tag}?include=
  haxProperties`, `GET schemas?filter.kind=haxProperties`.
- `tools/content.py` — the 12 generic tools: get_page_content, set_page_content (destructive),
  get_page_blocks, add_block, replace_block, remove_block, move_block, update_block,
  set_block_text, add_link, list_blocks, get_block_schema.
- `tools/blocks_typed.py` — the 37 typed tools: 31 `add_<block>` mirroring the Appendix B
  signatures + 6 native (add_paragraph, add_heading, add_list, add_table, add_blockquote,
  add_divider); all accept the shared page/anchor/occurrence/placement/site tail; each builds
  attributes through the catalog + `validate` and inserts via `insert_block`.
- `resources/catalog.py` (`haxcms://catalog/blocks`, `haxcms://catalog/blocks/{tag}`) and
  `resources/sites.py` (`haxcms://sites`, `haxcms://sites/{site}`, `haxcms://sites/{site}/outline`,
  `haxcms://sites/{site}/pages/{id_or_slug}` — content HTML with `<!-- block N: tag -->` index
  comments).
- `client/site_api.py` extended (get_item include_content, patch_content, get_content,
  list_schemas, get_block); `models/content.py` (Block, PageContent, BlockOpResult); `server.py`
  now registers 78 tools and 6 resources.

**Tests added**
- unit: `test_p04_page_break.py` (10), `test_p04_parser.py` (24), `test_p04_anchors.py` (18),
  `test_p04_block_ops.py` (28), `test_p04_catalog.py` (32), `test_p04_content_tools.py` (18),
  `test_p04_typed_tools.py` (43) — 173 new; `test_p00_server_boot.py` grew by 2 (78-tool
  registry + Phase 4 annotation matrix).
- integration: `test_p04_content_roundtrip.py` (7), `test_p04_block_ops_live.py` (5),
  `test_p04_typed_blocks_live.py` (9: table-coverage guard + 8 category chunks),
  `test_p04_resources.py` (10).
- regression: `test_p04_snapshots.py` (3) + new goldens `page_break.json`, `serializer.json`,
  `catalog.json`; `tool_schemas.json` regenerated for 78 tools.
- functional: `test_p04_rebuild_tutorial_page.py` (1).
- full rerun: `uv run pytest -m "not e2e"` → 446 passed in ~205s (388 unit/regression, 58 live).

**Verified facts** — see the cumulative list (all Phase 4 bullets): the five T4.7 items
(no-envelope silent no-op still 200; published-absent clears the flag; `card="card"`
byte-identical; all tags survive sanitisation with exactly four attribute rewrites and
GET==disk; the schemas haxProperties route DOES return self-check data) plus the fresh-page
`<p></p>` baseline and pathauto slug regeneration on rename.

**Deviations from PLAN.md**
- The functional tutorial test follows the FIXTURE positions, not Appendix D's paragraph
  ordinals: `tests/fixtures/pages/tutorial_finished.html` (the T4.2 golden) is authoritative —
  "Designing in the Prairie Spirit" lands BEFORE the prairie paragraph (D says after paragraph
  6), "The First Secret is Noticing" BEFORE the noticing paragraph (D says after paragraph 3),
  and Songline_1 anchors AFTER paragraph 3 (D prepends it at the top of the page). D's ordinals
  describe the original course page; PLAN L851-852 asks to assert the final block sequence
  against the golden.
- The fixture's `target="_blank"` is an AUTHORED form that cannot survive a save (saveNode
  strips it) — the functional test asserts the stored form and that `target="_blank"` is absent
  from the body.
- Appendix B parameters that 26.8.1's elements do not have (the assessment `title`s,
  page-section `accent_color`) are KEPT in the tool signatures (PLAN signatures immutable) and
  pass through to catalog validation, which rejects them with the known-attribute list;
  `place-holder kind="code"` (Appendix B) fails validation — 26.8.1's enum is
  text|document|audio|video|image|math. Both behaviours are documented in the docstrings.
- `add_vocab_term(links=None)` — PLAN spells the default `[]`; None means the same thing and
  keeps the linter's mutable-default rule (B006).
- The catalog live merge is a UNION that keeps bundled-only attributes the live haxProperties
  lack; bundled `example_html` is slightly richer than Appendix B where the real 26.8.1 shapes
  need it (stop-note icon + `slot="message"` div, a11y-collapse `expanded`, video-player
  `accent-color`, image-compare-slider `title`) so every example passes `validate`.
- All Phase 4 tools take `site` as the LAST optional parameter (Phases 2-3 convention) even
  where PLAN Appendix B lists it first.
- `haxcms://sites/{site}/outline` renders ONE JSON payload with `text` (indented tree) and
  `outline` (structured) keys instead of two MIME parts.
- One shared `CatalogService` (single live-merge cache) is built in `server.py` and injected
  into both the catalog tools and the typed block tools.
- Failed resource reads surface on the wire as `MCPError` with the `[CODE] message. hint`
  formatted string (the in-memory Client re-raises these); `McpTestClient.read_resource`
  returns the text payload for successful reads.

**Known gaps / follow-ups**
- Assessment correctness does NOT survive storage on 26.8.1: saveNode drops the bare boolean
  `correct` on `<input>`s, so stored multiple-choice/true-false/short-answer/matching/
  mark-the-words/tagging blocks lose their answer keys (upstream behaviour, not ours). Phase 9
  e2e stories must not assert stored `correct` attributes.
- `wrap_text_with_link` wraps the FIRST occurrence of the text inside the anchored block; there
  is no per-occurrence targeting inside a block.
- The catalog live merge caches per server instance; a site that gains new element definitions
  mid-session would not be re-merged until restart.

**Notes for the next Session**
- `stored_form()` in `tests/integration/test_p04_typed_blocks_live.py` is the executable spec of
  saveNode sanitisation — reuse it whenever a later Phase compares authored vs stored HTML
  (Phase 5's "upload an image and place it on a page" composite touches media-image attributes).
- Revision totals via `list_page_revisions` are the cheapest proof a save actually wrote:
  a total that does not grow means the save silently no-oped (missing envelope).
- Phase 5 imports `services/content/blocks.insert_block` and the `media-image` catalog entry
  by import only (PLAN Phase 5 independence note); the `site`/`page` fixtures and
  `haxcms.read_page_html` cover its assertions.
- Scratch pytest files must NOT start with a leading dot (importlib rejects them at
  collection); use `probe_tmp.py` and delete after.

---

### Phase 5: Files

**Session:** shared with Phases 0-4 (compacted several times)
**Completed:** 2026-10-01, tag `phase-05`, final commit: see tag

**Built** (6 commits, exactly the PLAN Phase 5 list)
- `models/file.py` — `FileRecord` (extra=allow; `uuid:str=""`, `width/height:int|None=None`;
  `from_api` accepts mimetype-or-type and coerces width/height to int when truthy),
  `FileCollection` (`{count, total, page, files, orphans}`), `UploadResult` (`{file}`).
- `client/site_api.py` Phase 5 helpers — `list_files`, `upload_file` (multipart field `file-upload`,
  optional `nodeId` data), `get_file`, `update_file` (`{operation, **args}`), `delete_file`; all
  `auth="bearer+site"` per the spec `security:` blocks.
- `services/files/sources.py` — resolve a file source: a local path (under `input_roots`), an http(s)
  URL (fetched server-side by THIS MCP server), or `base64:<name>:<payload>` inline (rejected over
  `MAX_INLINE_BASE64_MB` → FILE_SOURCE_ERROR); sniffs the mimetype from the bytes.
- `services/files/service.py` — `upload_file` (resolve_source → optional page→node_id →
  site_api.upload_file → UploadResult), `list_files`, `get_file`, `rename_file`, `transform_file`
  (scale/compress/convert-jpg/sepia/black-and-white/rotate-90), `duplicate_file`, `delete_file`, and
  the `add_image_from_file` composite (upload → `catalog.validate("media-image")` →
  `build_block_html(source=record.url)` → `insert_block` → `{file, ...block-op result}`).
- `tools/files.py` — the eight files tools with agent-manual docstrings (source forms, uuid
  semantics, `files/<name>` url usage, transform-accumulation + rename/delete dangling-source
  warnings, orphans reporting). Annotations: list_files/get_file read-only;
  upload_file/transform_file/duplicate_file/add_image_from_file `idempotent=False`; rename_file
  idempotent; delete_file destructive. `server.py` registers them after the typed block tools (the
  composite shares the server-wide `CatalogService`) → **86 tools** total.

**Tests added**
- unit + regression: Phase 5 model/source/service/tool tests across commits 1-4 → unit+regression
  total **443** (388 at Phase 4 + 55 new); `tool_schemas.json` regenerated for 86 tools (the eight
  files schemas frozen).
- integration: `test_p05_files.py` (9) — the PLAN lifecycle (upload by path → list with width/height
  → get → rename → duplicate → scale → delete, disk + files.json asserted at each step), list filters
  (type/extension/name_contains), URL upload from a tiny local http server, base64 upload,
  oversize-inline rejection, and the T5.7 probes (alternate multipart field, disallowed extension →
  UPSTREAM_ERROR, rename extension-lock → INVALID_ARGUMENT, nodeId upload leaves metadata.files
  alone).
- functional: `test_p05_tutorial_images.py` (1) — place the tutorial's two images with
  add_image_from_file, golden media-image attributes vs `tutorial_finished.html`, and the
  metadata.images/files rebuild.
- fixtures: `tests/fixtures/images/Songline_1.png` (120x80), `Songline_2.png` (100x60).
- full rerun: `uv run pytest -m "not e2e"` → **511 passed in 239.69s** (443 unit/regression + 68
  live) — the FIRST e969655c run for Phases 0-4; no regressions.

**Verified facts** — see the cumulative list above (all Phase 5 bullets): the stale-npm-dist finding,
upload uuid/width/height, root-relative fullUrl, the files.json datastore + orphans, uuid stability
via upsertFileRecordInDataStore, rename sanitisation + extension lock, duplicate `-copy`, in-place
scale/compress/convert/sepia/bw/rotate (no imgops), delete scrubbing files.json + metadata.files, the
500-vs-400 error mapping, and the add_image_from_file metadata rebuild.

**Deviations from PLAN.md**
- **The npm-published `@haxtheweb/haxcms-nodejs@26.8.1` dist is STALE** (predates spec commit
  e969655c that `specs/VERSION` pins) and lacks the entire files datastore/enrichment (no
  uuid/width/height on upload, no files.json, no compress/duplicate, imgops-style non-in-place
  transforms). Phase 5's live suites FAIL against the dist on facts the spec (`specs/site-spec.yaml`)
  and PLAN Phase 5 REQUIRE. Root-caused by reading both builds — a runtime version skew, NOT an
  implementation bug (my models/service/tests were correct per spec).
  - **Resolution (user-approved):** `_test_haxcms_dir()` now auto-prefers the sibling checkout
    `../haxcms-nodejs` (PLAN §0.4 lists it as optional; it is at exactly e969655c) over the npm dist
    when present. `ensure_haxcms()` `npm install`s the sibling's dependencies
    (`../haxcms-nodejs/node_modules` + `package-lock.json`; deps only, NO source edits) to get an
    e969655c-matching runtime. The user explicitly approved installing into the otherwise read-only
    reference checkout. `HAXCMS_MCP_TEST_HAXCMS_DIR` still overrides; the harness falls back to the
    npm dist when there is no sibling.
  - The harness change is bundled INTO the `test(files)` commit (commit 5), not a separate
    `fix(harness)` commit: it is the runtime resolution that makes these very tests meaningful, and
    bundling keeps PLAN's Phase 5 commit list intact (5 = tests, 6 = docs).
- `site_api.upload_file`'s docstring was corrected to the live contract (field is `file-upload`;
  multer `.any()` also accepts upload/file/files[]; a disallowed extension is HTTP 500 'File type not
  allowed', not the 400 first assumed).
- PLAN Phase 5 lists the operations "convert-jpg|scale|sepia|black-and-white|rotate-90|compress" +
  `duplicate_file`; ALL exist in e969655c and are implemented. (The stale dist lacks compress +
  duplicate — another symptom of the skew.)

**Known gaps / follow-ups**
- **CI runs against the STALE npm dist.** `.github/workflows/ci.yml` sets only
  `HAXCMS_MCP_TEST_HAXCMS_VERSION: "26.8.1"` and has no sibling checkout, so `_test_haxcms_dir()`
  returns None and `ensure_haxcms()` npm-installs the stale dist → the Phase 5 live suites
  (integration + functional) would FAIL in CI on the missing uuid/width/height/compress/duplicate.
  **Fix options:** (a) CI checks out `haxcms-nodejs` at e969655c as a sibling and sets
  `HAXCMS_MCP_TEST_HAXCMS_DIR`, or (b) npm republishes a 26.8.1 build actually at e969655c, or (c)
  the Phase 5 live suites are gated/skipped in CI until then. NOT addressed in Phase 5 (out of
  scope); recorded for Phase 9 hardening / CI work.
- Phases 0-4 live suites all pass against e969655c (full rerun) — no version-skew regressions
  outside the files API. The stale dist and e969655c are behaviourally identical for everything
  Phases 0-4 touch; future Phases must still target e969655c/spec, not the dist.
- `add_image_from_file` places exactly ONE media-image per call; multi-image placement is multiple
  calls (each its own upload + insert + save + git revision).

**Notes for the next Session**
- Phase 6 (Site settings) targets the SAME e969655c runtime (the harness now auto-prefers the
  sibling). Verify each settings route against `specs/site-spec.yaml` + the sibling source, NOT the
  npm dist.
- Phase 6 carried notes (from earlier source reads, re-verify before coding): PATCH site saveManifest
  `{site, theme, author, seo}` wrapper; `site/appearance`, `site/seo`, `site/editor`
  (`{platform:{audience}}`), `site/blocks` (`{platform:{allowedBlocks|null}}`), `site/platform`
  (`{platform:{features:{key:bool}}}` — verify nesting); POST `site/updateAlternativeFormats`;
  manifest flat dash-separated keys; cssVariable `--simple-colors-default-theme-<color>-7` or bare;
  feature key false → 403 FEATURE_DISABLED; git settings live in `metadata.site.git` with NO v1 route
  → `configure_site_git` should return a clear "unsupported" after verification.
- The `files.json` datastore (`FilesDataStore`, envelope HAXCMS-FILE-SCHEMA-V1) is the source of truth
  for file identity — any later tool needing "which uuid is this file" must read files.json (via
  list/get), never recompute the deterministic sha256 (it shifts on size change).
- `upsertFileRecordInDataStore`, `buildFilePublicUrl` (`src/lib/siteFileUrl.js`) and
  `sanitizeFileRenameBaseName` (all in `../haxcms-nodejs/src/siteRoutes/v1/files.js` unless noted) are
  the executable spec of the file operations — re-read them if Phase 7+ (import/export) touches
  files.

---

### Phase 6: Site settings

**Session:** shared with Phases 0-5 (compacted several times)
**Completed:** 2026-10-01, tag `phase-06`, final commit: see tag

**Built** (PLAN's 6 commits plus 2 inserted fix commits — see Deviations)
- `models/settings.py` — `SiteSettings` (view over the PUBLIC site.json manifest), `ThemeSettings`,
  `SeoSettings`, `AuthorSettings`, `GitSettings` (read-only), `PlatformSettings` +
  `PlatformFeatures` (the 21 flags via `FEATURE_FIELD_MAP`); lenient `_flag` boolean mirroring the
  server's parseBooleanFromInput; every block `extra="allow"`; declared field names excluded from
  `**extras` (live-collision fix, commit 2c7f35b).
- `client/site_api.py` helpers — `fetch_site_manifest` (public raw site.json), `update_manifest`
  (scoped `manifest` object), `update_appearance`, `update_seo`, `update_editor`,
  `update_allowed_blocks`, `update_platform`, `update_alternative_formats`; all `auth="bearer+site"`.
- `services/settings.py` — pure payload builders (`build_scoped_manifest_payload`,
  `build_appearance_theme`, `build_seo_fields`, `build_author_fields`) + the eleven service
  functions: home_page/region slug→id pre-resolution; theme validated against the live registry
  (hidden themes pass with a warning); element-change warning; dashed allowed-block tags
  pre-validated against the WC registry (the server's 400 is generic — ours names the offender);
  platform features MERGED over current (the route REPLACES); tags + git fail fast UNSUPPORTED
  before any network call.
- `tools/settings.py` — the eleven T6.4 tools with agent-manual docstrings (element-reset warning,
  all 21 feature keys + the siteManifest self-lockout warning, tags/git UNSUPPORTED + Operator
  hints, null-unrestricts semantics); `server.py` registers them after the files tools → **97
  tools**.
- `client/envelope.py` — gate matching broadened to the shared suffix `disabled for this site`
  (commit 982960f).

**Tests added**
- unit: `test_p06_settings_models.py` (6), `test_p06_settings_service.py` (26, respx),
  `test_p06_payloads.py` (17 goldens/allow-lists) → unit+regression total **513**.
- integration: `test_p06_settings.py` (11 — every tool against the live runtime, asserting the
  returned view AND site.json on disk; the pathauto toggle steers a later rename; the deletePage
  gate → FEATURE_DISABLED → page survives → re-enable → delete works), `test_p06_git.py` (3 — the
  form-token-wall probe, the silently-ignored-keys probe, the UNSUPPORTED tool + still-reported git
  block).
- functional: `test_p06_theme_journey.py` (1 — create with clean-one → switch to learn-two-theme
  with palette+accent+icon in ONE call → assign the Welcome page to sidebarFirst AFTER the switch →
  view + disk).
- regression: `tool_schemas.json` regenerated twice (87 → 97 tools), each diff verified purely
  additive with a UTF-8-safe Python comparison; new golden `settings_payloads.json` (the ten wire
  payloads, respx-captured).
- full rerun: `uv run pytest -m "not e2e"` → **596 passed in 280.81s** (513 unit/regression + 83
  live). `ruff check` + `ruff format --check` + `mypy src` (70 files) clean.

**Verified facts** — see the cumulative list above (all Phase 6 bullets). T6.5 answers: the SEO
wrapper is the top-level `seo` + `author` pair with SHORT keys (not `manifest.seo`); platform
features are `platform.features` NESTED; `home_page` needs the item id on the wire (slugs
pre-resolved); `deletePage=false` → `delete_page` FEATURE_DISABLED, live-confirmed. T6.3 git
verification: NO route persists `metadata.site.git` → `configure_site_git` raises UNSUPPORTED
(both directions live-probed in `test_p06_git.py`).

**Deviations from PLAN.md**
1. T6.1: `SiteSettings` is a view over the PUBLIC `GET /_sites/{site}/site.json`, not
   `SiteSummary.metadata` — the public site summary carries no metadata block and the system
   `GET sites/{name}` metadata is only `{pageCount, created, updated}`.
2. `update_site_info(tags=...)` → UNSUPPORTED: PLAN lists tags among the writable site-info fields,
   but no reachable route persists `metadata.site.tags` (form-token wall). Fails before any other
   field is applied; the integration case asserts UNCHANGED site.json instead of PLAN's on-disk
   tags change. Operator recovery: edit site.json server-side.
3. `configure_site_git` → always UNSUPPORTED (T6.3's own verification branch, live-probed).
   `get_site_settings` still REPORTS the git block.
4. `set_platform_features` merges the passed flags over the current set before the PATCH —
   `savePlatformSettings` has REPLACE semantics, and the merge preserves PLAN's "only the flags you
   pass change" contract.
5. Commit list: PLAN names 6; 8 landed — inserted `fix(client)` 982960f (the gate-suffix mapping,
   discovered while wiring the Phase 6 services; benefits every phase), and commit 5 split into
   `fix(settings)` 2c7f35b + `test(settings)` 919b163 so the fixes stay reviewable.
6. The functional journey runs on its own throwaway site (created with clean-one, first page
   "Welcome") rather than the shared tutorial course — same coverage, isolated fixture.
7. Two live-caught bugs fixed in 2c7f35b (contract hazards for any future manifest parser): the
   fresh-site top-level JSON Outline Schema `author: ""` collided with `SiteSettings.author`
   through `**extras` (TypeError on EVERY real get_site_settings; unit fixtures lacked the key),
   and `update_author_info`'s `resolve_site` local was named `name`, shadowing the author-name
   parameter (wrote the site machine name into metadata.author.name).

**Known gaps / follow-ups**
- The CI stale-dist gap (Phase 5) stands. The Phase 6 routes predate the files-datastore work, so
  the live suites likely pass against the npm dist too — UNTESTED; still a Phase 9 hardening item.
- `siteManifest=false` self-lockout is documented (tool docstring warning) but not guarded
  programmatically — recovery is a server-side site.json edit. Per PLAN's design the warning is the
  contract.
- If a future HAXcms exposes tags/git writes, the UNSUPPORTED services are the swap-in points
  (interfaces + tests already exist).

**Notes for the next Session**
- Phase 7 (imports + generated converters): `gen_tools.py` generates from `specs/system-spec.yaml`
  per PLAN; verify the import routes against the e969655c source (`src/systemRoutes/v1/`), never
  the npm dist.
- The live-probe pattern that cracked the author collision in one shot: `uv run python - <<EOF`
  with HaxcmsRuntime + HaxcmsClient + create/try/finally archive — prefer it over source-chasing
  whenever a live shape is in doubt.
- `metadata.site.updated` bumping + the git commit on every manifest write are cheap on-disk
  assertion handles for future live tests.
- Fresh sites have NO `homePageId` key — always `.get()` it, on both sides of a comparison.

---

### Phase 7: Imports and generated converters

**Session:** shared with Phases 0-6 (compacted several times)
**Completed:** 2026-10-01, tag `phase-07`, final commit: see tag

**Built** (PLAN's 6 commits, exactly)
- `models/imports.py` + `client/system_api.py` (9c07784) — `detect_import_kind` (extension-first,
  mimetype fallback, legacy .doc/.xls/.ppt refused locally), `ImportedItem`/`ImportData`
  (files/siteFiles/site.license mapping + extras like selectedSheet)/`ImportResult`/
  `ConversionResult` (text inline OR {path, bytes, mimetype, filename}); `import_document`
  (multipart with method/type/parentId form fields), `import_platform` (JSON repoUrl + multipart
  file modes), generic `action()` keyed by spec operationId with a raw-bytes mode for docxToPdf's
  envelope-less stream; `envelope.py` learned `data.error` (the import/converter 400 key).
- `services/imports.py` + `tools/imports.py` (60b8432, 97 → 100 tools) — the three composites:
  resolve Source → detect kind → pre-resolve parent id-or-slug → `actions/import-<kind>` → bulk
  `create_pages` → re-fetched ImportResult with skipped/warnings; `create_site_from_document`
  (method=site import → createSite with build {type "<kind> import", structure "import", raw items
  passthrough}); `create_site_from_platform` (repoUrl mode; files/siteFiles ride along in build;
  SSRF/fetch 400s gain the private-or-unreachable hint). method/type/platform validated locally
  against the exact server sets. 422 → INVALID_ARGUMENT (openstax/plone converters).
- `scripts/gen_tools.py` + `services/conversion.py` (a8ae984) — deterministic generator over the
  vendored `specs/system-spec.yaml` (fixed CONVERTERS order, no timestamps, LF writes, `--check`
  exits 1 with a unified diff on drift); OVERRIDES pin the source-verified spec deviations;
  conversion helpers write binary results under `settings.output_dir` with never-overwrite
  `<stem>-<n>` naming and untrusted-filename sanitization.
- `generated/converters.py` + `tools/converters.py` (a1373f1, 100 → 112 tools) — the twelve
  `convert_*` tools, read-only hint true, descriptions = generated docstrings verbatim (DEVIATION
  and NEEDS CHROME notes included). Two FastMCP landmines defused: the generated module OMITS
  `from __future__ import annotations` (FastMCP resolves a partial-bound tool's string annotations
  outside the module namespace → NameError), and `mcp.tool` rejects partials as first arg →
  registration goes `Tool.from_function` + `mcp.add_tool`. CI lint job runs `gen_tools.py --check`;
  in-process twin `tests/regression/test_p07_generator.py`.
- `tests/fixtures/import/` (2afba4b) — `generate.py` + five committed fixtures with pinned
  timestamps: syllabus.docx (2 H1 roots, 2 H2 units, 1 H3, inline PNG), slides.pptx (3 titled
  slides), workbook.xlsx (Schedule + Roster, title/slug/parent/content header contract),
  onepage.pdf, page.html. Dev deps python-docx/python-pptx/openpyxl/fpdf2 are test-time only.

**Tests added**
- unit: `test_p07_kind_detection.py` + `test_p07_import_payloads.py` (45 — kind matrix, respx
  payload goldens for all three endpoint helpers, data.error mapping, model parsing),
  `test_p07_gen_tools.py` + `test_p07_conversion.py` (41 — determinism, ast-level parameter
  derivation for all 12 functions, override wiring, drift detection, LF-only; conversion helpers
  incl. base64 validation + unique-name saturation) → unit+regression total **602** (≈76s).
- regression: generator golden (committed module == fresh generation); `tool_schemas.json`
  regenerated twice (97 → 100 → 112), each diff verified purely additive; boot-test matrix gained
  the twelve converter names + schema and annotation checks (partial-bound params never leak into
  the schema).
- integration (27): import_document (method=site/branch/page incl. parent wiring, nested slugs,
  disk bodies, materialized image + files.json record, xlsx wiring + selectedSheet echo, html,
  pdf, content_type, legacy-.doc refusal), create_site_from_document (docx with the full T7.7
  assertions, pptx flat slides, duplicate-name suffix + warning), platform (html multipart at the
  API level, LIVE SSRF refusal with the composite's hint, unknown platform, env-URL-marked
  gitbook/pressbooks), converters (all twelve exact 26.8.1 outputs; htmlToDocx into a tmp Output
  Directory without overwrites; the two Chrome ops under needs_chrome with a probe-skip).
- functional (1): `test_p07_course_from_docx.py` — "Build a course from my syllabus.docx" through
  Tool calls only (site listed, outline tree mirrors the headings, first paragraph on page one,
  nested lesson reachable by slug, inline image in list_files).
- full live rerun: `uv run pytest tests/integration tests/functional -q` → **110 passed, 4
  skipped** (2 network + 2 needs_chrome, by design) in 251.55s. `ruff check` + `ruff format
  --check` + `mypy src` (73 files) clean.
- exit-gate note: the combined `pytest -m "not e2e"` confirmation rerun (after the docs-only
  PROGRESS.md edit) was killed ~3% in by OS memory pressure and deliberately NOT restarted
  (harness policy on memory kills). Equivalence: the identical test tree passed as
  unit+regression (602, 75.85s) and integration+functional (110+4 skipped, 251.55s, exit 0)
  minutes earlier, and no e2e tests exist yet — the two runs together ARE the full non-e2e suite.

**Verified facts** — see the cumulative list above (all Phase 7 bullets). T7.7 answers:
`build.type` = `"<kind> import"` for all five kinds, persisted at `metadata.build` with the
server's own version string; DOCX inline images DO become Files on both import paths (JPEG
re-encode + files.json record + media-image reference + metadata.files uuid); Chrome-needing
converters are exactly htmlToPdf + docxToPdf, skipped without it (this machine has no Chrome).

**Deviations from PLAN.md**
1. T7.6's "static two-page HTML site served by a local http server for the html platform import"
   is IMPOSSIBLE: the server's safeFetch SSRF guard refuses loopback URLs and no override exists.
   The local server still appears in `test_p07_create_site_from_platform.py` — as the refused
   target (live assertion of the guard message + the composite's create_site_from_document hint) —
   while the html platform's reachable local mode (multipart upload) is covered at the API level.
2. T7.6's gitbook/pressbooks "public samples": no URLs are hardcoded (they rot); the tests are
   `network`-marked and read `HAXCMS_MCP_TEST_GITBOOK_URL` / `HAXCMS_MCP_TEST_PRESSBOOKS_URL`,
   skipping when unset.
3. T7.4 spec-vs-reality (generator OVERRIDES, source-verified): htmlToDocx/htmlToPdf are multipart
   .html/.htm uploads contra their spec JSON bodies; xlsxToCsv's `sheet` rides as a QUERY param;
   docxToPdf returns raw application/pdf without an envelope.
4. T7.6 fixtures are committed BINARIES with a regenerator (`generate.py`) — regenerating varies
   ZIP-internal timestamps, so the binaries are refreshed deliberately, not casually.
5. Chrome skipping (T7.7 "skip those without it") is implemented as the `needs_chrome` marker + a
   runtime probe-skip matching the server's "No Chrome" 400 — green on Chrome-less machines, real
   assertions when Chrome exists.
6. The `gen_tools.py --check` CI step landed with commit 4 (not commit 3) so every commit stays
   green — the check needs the generated file it compares against.

**Known gaps / follow-ups**
- The CI stale-dist gap (Phase 5) stands: Phase 7 was developed against the e969655c sibling
  checkout; the import/converter routes likely exist in the npm dist too — UNTESTED; still a
  Phase 9 hardening item.
- The two needs_chrome converter tests and the two network platform tests have never executed
  their assertions on this machine (no Chrome, no sample URLs) — they probe-skip by design.
- content_type=course is shape-identical to the default on our fixture (every heading carries
  body text) — acceptance is asserted; the placeholder-content toggle is not observable.

**Notes for the next Session**
- Phase 8 (exports): PDF export will hit the same Chrome-less 400 → T8.3's UNSUPPORTED mapping
  ("instance has no Chrome for PDF rendering") is the expected local path; which
  `site/export/{format}` values answer binary vs descriptor is UNVERIFIED — live-probe first.
  The Output Directory patterns (never-overwrite naming, sanitized filenames, {path, bytes,
  mimetype} results) already exist in `services/conversion.py` — reuse, do not reinvent.
- Multipart converter signatures are `(client, settings, source, ...)`; JSON ops are
  `(client, <fields>)`. `HaxcmsMcpError` carries `.code`, not `.error_code`.
- The live-probe pattern remains the fastest path to ground truth: `uv run python - <<EOF` with
  HaxcmsRuntime + in-memory Client + create/try/finally archive; expect ONE fixup iteration for
  tree/sort semantics even after probing (get_outline's nested tree + root ordering surprised the
  first draft of the Phase 7 assertions).

### Phase 8: Exports and publishing artifacts

**Session:** shared with Phases 0-7 (compacted several times)
**Completed:** 2026-10-01, tag `phase-08`, final commit: see tag

**Built** (PLAN's 5 commits, exactly)
- `models/export.py` + endpoint helpers (d15e81b) — `ExportArtifact{site, page_id|None, format,
  path, bytes, mimetype, created_at}` (page_id dropped when None) + `TemplateResult.from_api`
  (extra="ignore"); the server's exact SITE_EXPORT_FORMATS / ITEM_EXPORT_FORMATS /
  EXPORT_MEDIA_TYPES tables copied from exports.js. `system_api`: download_site,
  download_site_skeleton (INLINE skeleton), save_site_as_template — all bearer+user with the
  export timeout — and fetch_published (the unauthenticated `_published` mount). `site_api`:
  site_export (bytes|dict via the Content-Type discriminator), item_export (always raw bytes,
  nested slugs percent-encoded through `_item_path`), site_markdown (concat mode). 15 unit
  goldens incl. the httpx `url.raw_path` gotcha (url.path DECODES %2F).
- `services/exports/` package (28454e6) — `output.py` is the PLAN §2.3 write rule:
  `HAXCMS_MCP_OUTPUT_DIR/<site>/<YYYYMMDD-HHMMSS>-<name>.<ext>`, site subfolder created on
  write, reusing `conversion.safe_filename` + `_unique_path` (never overwrite, `-<n>` slots,
  site names sanitized as path segments too). `service.py`: export_site (local allow-list
  validation → INVALID_ARGUMENT with the supported list BEFORE any HTTP; zip two-step with
  `<site>.zip` name fallback; markdown = descriptor GET validates + concat fetch; skeleton
  delegates; pdf/docx/epub/html direct bytes with a defensive descriptor-answer check),
  export_page (get_item first for the canonical page_id + early 404; nested slugs keep their
  last segment locally), save_site_as_template, download_site_skeleton (pretty JSON,
  ensure_ascii=False). `_chrome_reraise` re-maps any "No Chrome" error to UNSUPPORTED with the
  PLAN T8.3 hint — wired into BOTH site and page binary paths. The stray empty Phase 0
  `services/exports.py` was git-rm'd (the package shadows it at import time anyway).
- `tools/exports.py` (a63e2bb, 112 → 117 tools) — export_site (format default zip), export_page
  (page + format default md), download_site_zip (the PLAN-mandated discoverability alias),
  save_site_as_template, download_site_skeleton; all resolve the site through the Default Site
  convention and return dump_model artifacts — {path, bytes, mimetype}, never bytes, never a
  URL. Annotations per PLAN T8.4: read-only hint FALSE, non-destructive, idempotent (repeats
  land in new filename slots; the template overwrites itself). Docstrings carry the Operator
  caveats (Chrome for pdf; `path` lives on the MCP server host).
- live suites (80fb7d1) — written AFTER a full live probe of every export path (probe script
  deleted before the gates, per the env note).

**Tests added**
- unit: `test_p08_export_endpoints.py` (15 — respx goldens for every helper, auth headers/bodies,
  400/502 mappings, model dumps, allow-list goldens), `test_p08_output_paths.py` (6 — naming,
  sanitization, collision slots, subfolder creation, page_id), `test_p08_exports_service.py`
  (16 — zip two-step, binary/descriptor/skeleton paths, Chrome-less re-maps, local validation,
  nested slugs) → unit+regression total **641** (≈93s).
- regression: `tool_schemas.json` regenerated (112 → 117, diff reviewed: purely additive, 149
  insertions, five entries with the correct hints); NEW `export_output_path.json` golden freezes
  the §2.3 naming + the dumped artifact shape (the PLAN's "output path golden").
- integration (8, service level with output_dir=tmp_path): zip PK magic + site.json + 75-entry
  folder; markdown (# Home concat) + html non-empty; page md/html/json/yaml/xml contain the
  title and carry page_id; docx/epub are Chrome-free PK containers; site AND page pdf branch
  (UNSUPPORTED + hint here, %PDF on a Chrome server); save-as-template → list_skeletons +
  get_skeleton; skeleton parses with build.items[0].title == Home and inline content.
- functional (1): `test_p08_share_course.py` — "Export my course as a zip and the lesson as PDF"
  through Tool calls only, with a local mcp fixture whose output_dir is tmp_path.
- full live rerun: `uv run pytest tests/integration tests/functional -q` → **119 passed, 4
  skipped** (2 network + 2 needs_chrome, by design) in 283.73s — all earlier phases still green.
  `ruff check` + `ruff format --check` + `mypy src` (74 files) clean.

**Verified facts** — see the cumulative list above (all Phase 8 bullets). T8.5 answers:
binary = pdf/docx/epub/html (+ ALL eight item formats); descriptor = zip/markdown/skeleton;
zip magic PK + site.json inside; save-as-template returns {saved, name, filename, path, link}
and stores under `<config>/user/skeletons/` → immediately in list_skeletons.

**Deviations from PLAN.md**
1. T8.3 said "a 500 on pdf" for Chrome-less instances — reality (source + live) is **502**
   `{data.message}`. The envelope's ≥500 → UPSTREAM_ERROR mapping stands; the service re-maps
   the "No Chrome" substring to UNSUPPORTED with the PLAN's exact hint. The live message has no
   "Unable to complete PDF export conversion:" prefix (that is the CONVERTER actions' wording) —
   both unit goldens were corrected to the live wording in commit 4.
2. API-REF §3.4's `{link, name}` guess for download-skeleton is wrong — the skeleton arrives
   INLINE as `{skeleton, filename}` (source-verified in commit 1; matches the Phase 2 probe note).
3. T8.3's "others → GET site/export/{format}" is only literally true for pdf/docx/epub/html:
   the GET for zip/markdown/skeleton answers a DESCRIPTOR, so the service special-cases zip
   (the PLAN's own two-step), markdown (descriptor validation + concat fetch) and skeleton
   (direct POST). The descriptor GET is still issued for markdown so the server validates the
   route/format before the content fetch.
4. The functional journey's PDF leg: the PLAN scenario assumes a Chrome-equipped server; this
   machine has none, so the test asserts the `[UNSUPPORTED]` no-Chrome contract and falls back
   to docx — the operator still leaves with two files (.zip + .docx) with correct extensions in
   the Output Directory. On a Chrome server the same test takes the .pdf branch (branched, not
   skipped — it never depends on the environment to pass).
5. T8.3 named `services/exports.py`; the Phase 0 scaffold had BOTH that empty file and an empty
   `services/exports/` package (which shadows the module at import time). The stray module was
   deleted and the package implemented per the files/ precedent (docstring __init__, output.py,
   service.py) — §2.3 itself specifies `services/exports/output.py`.

**Known gaps / follow-ups**
- The CI stale-dist gap (Phase 5) stands: Phase 8 was developed against the e969655c sibling
  checkout; the export routes on the npm-published dist are UNTESTED — Phase 9 hardening item.
- The Chrome-server branches (site/page pdf → %PDF, the functional .pdf leg) have never executed
  here; the UNSUPPORTED branches have. docx/epub assertions DID run live (Chrome-free).
- save-as-template leaves the template in the session's `_config` (fresh per runtime spawn);
  no test asserts an exhaustive skeletons list (membership only), so residue is harmless.

**Notes for the next Session**
- Phase 9 (prompts, docs, hardening, e2e, release 0.1.0): the stdio subprocess e2e helper is
  promised in `tests/harness/mcp_client.py`'s docstring ("lands in Phase 9"); the CI stale-dist
  follow-up and the never-executed needs_chrome/network tests are listed above.
- Export service signatures: `export_site/export_page/download_site_skeleton` take
  `(client, settings, site, ...)`; `save_site_as_template` takes only `(client, site)` — it
  writes nothing locally, so it needs no settings.
- ReadOnlyMiddleware blocks ALL five export tools in Read-Only Mode (read_only_hint False per
  PLAN T8.4 — they create server-side artifacts): intentional, matches the PLAN's annotation
  matrix; only true reads stay available there.
- The `mcp` fixture's Settings use the DEFAULT output_dir (`haxcms-mcp-output`, relative) —
  any test that writes artifacts must build its own server with output_dir=tmp_path (the
  `_output_settings` / `mcp_out` patterns in the Phase 7/8 suites).

---

### Phase 9: Prompts, documentation, hardening, final end-to-end smoke

**Session:** shared with Phases 0-8 (compacted several times)
**Completed:** 2026-10-01, tags `phase-09` + `v0.1.0`, final commit: see tag

**Built** (the PLAN's 7 commits, exactly)
- `prompts/journeys.py` (428ed87) — the four Prompts: `hax_author` (persona, the save discipline
  — no autosave, one call is one save and one git revision — block discovery via list_blocks /
  get_block_schema / the catalog resources, anchor + occurrence rules, alt/caption/citation
  duties, the reserved `x/` route), `build_page_from_brief(site, page_title, brief, media)`,
  `scaffold_course_from_outline(site_name, outline_text, theme)`,
  `import_and_polish_document(site_name, source)`. All sync `@mcp.prompt`; every snake_case token
  in the rendered texts is cross-checked against the LIVE tool registry (no whitelist) — the check
  caught its one offender during development (deviation 1).
- `scripts/gen_tool_docs.py` + `docs/tools.md` (c3c461e) — renders all 117 tools (annotations
  line, parameter tables with type/required/default from the input schema, first docstring
  paragraph) into a deterministic 1758-line reference; `--check` mode with unified diff wired
  into CI next to the converters drift check; in-process twin test regenerates and compares.
- `README.md` (261372d) — full rewrite: intro (ADR-0001 typed HTTP client of a running
  instance), what the agent gets (117 tools / 6 resources / 4 prompts), install (`uv tool
  install` from clone or git, `uvx`), the complete PLAN §4 configuration table, run modes
  (stdio / http / `--version`), Claude Code `claude mcp add` (env flags + the http transport
  variant), Claude Desktop JSON, security notes, troubleshooting table, development commands,
  documentation links. Every claim verified against code before committing (two overstatements
  found and fixed — deviation 4).
- hardening (ede675f) — `build_server` owns a FastMCP lifespan that closes the httpx client on
  session end (stdio EOF, HTTP shutdown, in-memory disconnect); PLAN §5 DEBUG request line
  implemented in `HaxcmsClient._send` (`url.raw_path`, never headers); timeout wiring pinned
  (client-level `timeout_s` on every call, the seven long call sites pass `export_timeout_s`,
  the `timeout=None` kwargs guard can never DISABLE httpx timeouts); log redaction test;
  `--version` unit test; `tests/harness/mcp_process.py` (`stdio_client()` with keep_alive=False
  + `HttpMcpProcess` with TCP readiness and taskkill/killpg teardown — the pattern the
  mcp_client.py docstring promised since Phase 0); whole-registry read-only matrix; HTTP
  transport integration tests; CI coverage gate `--cov-fail-under=80`.
- `tests/e2e/test_tutorial_smoke.py` (08c67a2) — Appendix D replayed step by step over the real
  stdio subprocess (14 steps: whoami → "First" spaces rejection → create_site → outline →
  create/rename page with Pathauto slug → seven paragraphs → heading → paragraph→h2 conversion
  → two REAL image uploads via add_image_from_file → video → two add_link wraps → golden
  block-for-block comparison + resource + disk + zip export), plus the short HTTP variant T9.5
  asks for (whoami + list_sites).
- `CHANGELOG.md` (15b5e6f) — hand-written from `git log` (the option T9.6 allows; git-cliff is
  not a project dependency): Keep a Changelog format, one 0.1.0 section grouped by Conventional
  Commit type; every tool name, count and figure verified against docs/tools.md, the registry
  and config.py; the five pre-release fix commits cited by hash. Version 0.1.0 was already set
  in pyproject.toml + `__init__.py` since Phase 0 — verified, unchanged.

**Tests added**
- unit: `test_p09_prompts.py` (8 — registration, argument metadata, the registry cross-check,
  per-prompt content and ordering assertions), `test_p09_docs_current.py` (6 — committed docs
  current, deterministic, complete, annotated; first_paragraph/schema_type extraction cases),
  `test_p09_hardening.py` (5 — --version, lifespan close, timeout wiring, timeout=None guard,
  redaction) → unit total **610** (95s).
- integration: `test_p09_read_only_matrix.py` (86 — partition completeness + 84 parametrised
  empty-args refusals derived from live annotations + read-only pass-through),
  `test_p09_http_transport.py` (3 — registry/prompts list, read calls, create+outline+archive
  write round trip over the spawned HTTP subprocess).
- regression: `test_p09_snapshots.py` + NEW golden `snapshots/prompt_texts.json` (all four
  prompts rendered with sample args). `tool_schemas.json` UNCHANGED — Phase 9 adds no tools
  (verified: post-run `git status` clean, gen_tools --check green).
- e2e: `test_tutorial_smoke.py` (2).
- full exit rerun: `uv run pytest -m unit -q` → **610 passed** (95s);
  `uv run pytest -m "not unit and not e2e" -q` → **259 passed, 4 skipped** (2 network +
  2 needs_chrome, by design; 296s); `uv run pytest -m e2e -q` → **2 passed** (33s) — all
  earlier phases still green; 875 tests collected; `ruff check` + `ruff format --check` +
  `mypy src` (74 files) clean; both drift checks green; tree clean after the runs.

**Verified facts** — copied into the cumulative list above (all seven Phase 9 bullets).

**Deviations from PLAN.md**
1. The no-whitelist registry cross-check flagged `new_tab` — an add_link ARGUMENT mentioned in
   backticks in build_page_from_brief matched the tool-name regex. Reworded the prompt to "the
   new-tab flag" (journeys.py); the check worked exactly as designed.
2. PLAN §5's DEBUG request line was promised by logging.py's docstring since Phase 0 but never
   implemented — reality contradicted the plan for eight phases; implemented in the hardening
   commit (`_send`, raw_path, no headers) and pinned by the redaction test.
3. T9.4's `--version` flag and whoami budget stats ALREADY existed (Phase 0 / Phase 1) —
   verified, and newly pinned by unit tests instead of re-implemented.
4. Two README claims corrected against code before committing: there is no redaction FILTER
   (protection = nothing ever logs secrets; the redaction test pins it), and the machine-name
   hint restates the rules rather than naming the offending character.
5. The e2e replay rides three recorded allowances: anchors follow the `tutorial_finished.html`
   golden, not Appendix D's paragraph ordinals (the Phase 4 deviation note — the fixture is the
   authoritative finished page); the paste uses `set_page_content` (Appendix D step 5 explicitly
   allows it); the site name carries a random suffix so a leaked site from a failed run can
   never become a `<name>-1` collision. The literal tutorial name "First" is still exercised —
   as the spaces-hint rejection.
6. CHANGELOG hand-written from git log (T9.6 allows git-cliff OR hand-written); the v0.1.0 tag
   is created at the §0.5 exit gate together with phase-09, on the final phase commit.
7. The 80% coverage gate sits on the lint-unit job (runs on both matrix legs) — measured 87.0%
   for the unit-only run.

**Known gaps / follow-ups**
- The stale-dist gap (Phase 5 note, carried through Phase 8) stands and was NOT a T9.4 item:
  the test runtime is the sibling checkout with npm-installed dependencies (user-approved);
  the npm-published dist's export routes remain untested.
- The Chrome-server branches (pdf → %PDF on site and page exports) have never executed on this
  machine; the UNSUPPORTED branches have (Phase 8 + troubleshooting docs).
- The e2e HTTP variant is deliberately short (T9.5: whoami + list_sites); the HTTP write round
  trip lives in the integration suite.

**Notes for the next Session**
- **The PLAN is complete.** All ten phases done; tags phase-00 … phase-09 and v0.1.0; the repo
  ships 0.1.0: 117 tools, 6 resources, 4 prompts, stdio + streamable-HTTP.
- Maintenance pointers: `docs/tools.md` and `generated/converters.py` are CI drift-checked —
  regenerate with `uv run python scripts/gen_tool_docs.py` / `scripts/gen_tools.py` after any
  tool or spec change; the regression goldens (`tool_schemas.json`, `prompt_texts.json`, …)
  follow the `assert_or_update_snapshot(..., update=...)` flag pattern.
- Full local battery = three commands (`-m unit`, `-m "not unit and not e2e"`, `-m e2e`), each
  spawning its own HAXcms runtime — ~9 min total on this machine; running them separately keeps
  memory pressure low (the environment reaper kills heavy background shells).
- The read-only matrix derives its write set from the LIVE registry annotations — any new tool
  is automatically included; keep the annotations honest or the matrix lies.
- `server_env()` must always keep the full os.environ (Windows SystemRoot); `stdio_client`
  uses keep_alive=False so subprocesses die with their connection.
