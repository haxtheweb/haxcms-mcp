# HAXcms NodeJS 26.8.1 API reference for the MCP build

This is the HTTP contract the MCP server codes against. Every fact here was read from the
`haxcms-nodejs` source at version 26.8.1 (git `e969655c`, 2026-09-25). File references are relative
to that repository. Where this document says "verify", the implementing agent must confirm the fact
against the source or a running instance before relying on it, and record the result in
`PROGRESS.md`.

Vocabulary is defined in `../CONTEXT.md`. The two OpenAPI specs are vendored under `../specs/`
(copied from `src/openapi/system-spec.yaml` and `src/openapi/site-spec.yaml`); they are the
authoritative response schemas. This document adds the behaviour the specs leave implicit.

---

## 1. Base URLs and scopes

| Scope | Base path | Registered in |
|---|---|---|
| System API | `{base}/system/api/v1/` | `src/lib/SystemRoutesMap.js`, mounted in `src/app.js` ~L1448 |
| Site API (multi-site) | `{base}/_sites/{siteName}/x/api/` | `src/lib/SiteRoutesMap.js`, mounted with prefix `/_sites/*` in `src/app.js` ~L1560 |
| Site API (single-site) | `{base}/x/api/` | same map; site resolved from cwd |

`{base}` is the instance root, e.g. `http://localhost:3000`. The sites directory name is `_sites`
(`HAXCMS.sitesDirectory`). Published zips are served from `{base}/_published/`.

The MCP always uses the multi-site form for the Site API and puts the Site Name in the path. The
server resolves the site from the path first (`getSiteNameFromSiteApiRequestPath`, `src/app.js`
~L2350), then from `site.name` in the body, then from the Referer.

### Response envelope

Every JSON response is `{ "status": <int>, "data": <payload> }` (`ApiEnvelope`). Errors use the same
shape with `data.message`. Some legacy routes put extra keys at the top level (login returns
`{status, jwt}`; createSite returns `{status, data, id, slug, link}`).

Error status conventions:

| Status | Meaning |
|---|---|
| 400 | Invalid request shape (many settings routes reply `"Invalid request"` with no detail) |
| 401 | No credentials, invalid login, expired refresh token |
| 403 | Bearer present but invalid, missing or wrong Site Token, feature disabled for the site, cross-origin refresh |
| 404 | Site or item not found |
| 405 | Method not allowed; `Allow` header lists valid methods |
| 429 | Login limiter (5 failures per 15 min per IP+user, `Retry-After` set) or file-ops limiter (500 mutations per 5 min per user:site) |
| 500 | Server-side write failure (`"failed to write"`, `"Server error"`) |

---

## 2. Authentication

Source: `src/systemRoutes/v1/routes/login.js`, `refreshAccessToken.js`, `logout.js`,
`connectionSettings.js`; `src/lib/HAXCMS.js` `validateJWT` ~L4661, `getJWT` ~L4696,
`getRequestToken` ~L3852; `src/app.js` `validateSiteApiRouteAccess` ~L2480.

### 2.1 Login

```
POST {base}/system/api/v1/session/login
Content-Type: application/json
{"username": "<user>", "password": "<pass>"}

200 -> {"status":200, "jwt":"<access token>"}
      Set-Cookie: haxcms_refresh_token=<refresh jwt>; HttpOnly; SameSite=Lax; Path=/ (Secure when https)
401 -> {"status":401,"data":{"message":"Invalid username or password"}}
429 -> after 5 failures in 15 min; Retry-After header
```

The access token is an HS256 JWT with `exp = iat + 15 minutes` and a 60 second clock tolerance.
Send it as `Authorization: Bearer <jwt>` on every authenticated call. The `?jwt=` query form also
exists but the MCP must not use it.

Revalidation: `POST session/login` with body `{"jwt": "<existing>"}` returns the same token if still
valid, else 401.

### 2.2 Refresh

```
GET {base}/system/api/v1/session/refresh
Cookie: haxcms_refresh_token=<refresh jwt>

200 -> {"status":200,"jwt":"<new access token>"}  + rotated Set-Cookie
401 -> refresh invalid/expired/replayed; cookie cleared
403 -> Origin/Referer present and not same-origin
```

Rules for the MCP client: keep the cookie jar; do **not** send `Origin` or `Referer` on this call
(absent headers are allowed, mismatched ones are refused). Refresh proactively when the access token
is older than 12 minutes, and reactively on a 403 `"Invalid bearer token"` from any authenticated
route. If refresh fails, log in again with the configured credentials. Refresh tokens are rotated per
use and revoked on logout; a reused old token revokes the whole family, so never retry a refresh
with a stale cookie.

### 2.3 Logout

```
POST {base}/system/api/v1/session/logout   -> {"status":200,"data":"loggedout"}
```

### 2.4 Session check

```
GET {base}/system/api/v1/session          (bearer) -> 200 session details, or 401/403
GET {base}/system/api/v1/session/user     (bearer + X-HAXCMS-User-Token) -> user profile
```

### 2.5 Site Token and User Token (connection-settings)

Site writes require header `X-HAXCMS-Site-Token`. System writes that touch a site (create site,
imports) require `X-HAXCMS-User-Token` in addition to the bearer. Both tokens are HMACs computed
server-side (`getRequestToken(user + ':' + site)` and `getRequestToken(user)`) and are only
obtainable from:

```
GET {base}/system/api/v1/session/connection-settings
Accept: application/javascript
Referer: {base}/_sites/{siteName}/
```

The response is **JavaScript**, not JSON:

```js
window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};
window.appSettings ={"token":"...","siteToken":"...","userToken":"...","siteApiBasePath":"/_sites/<site>/x/api", ... };
```

The site is chosen from the **Referer** path segment after `/_sites/` (`connectionSettings.js`
L167-181). With no matching Referer the server falls back to the single-site context and the
`siteToken` is for the wrong site. Parse with: locate `window.appSettings =`, then
`json.JSONDecoder().raw_decode` from the first `{`. Cache the `siteToken` per Site Name and the
`userToken` per process; both are stable for the life of the instance's secret files. When
`HAXCMS_DISABLE_JWT_CHECKS` is on, the script also appends `window.appSettings.jwt = "..."` and all
token checks are bypassed server-side.

Route in `SystemV1OpenRoutes`: no bearer required for this call. The tokens are for the configured
Login User regardless of caller, because HAXcms NodeJS has a single user.

### 2.6 Header matrix

| Call class | Authorization: Bearer | X-HAXCMS-Site-Token | X-HAXCMS-User-Token | body `site.name` |
|---|---|---|---|---|
| System open routes (login, refresh, logout, connection-settings, connection-test, discovery) | no | no | no | no |
| System admin reads (list sites, site info, themes, skeletons, status) | yes | no | no | no |
| System site lifecycle writes (create/clone/archive/download/save-as-template) | yes | no | yes | yes |
| System import/convert actions | yes | no | yes | n/a |
| Site API reads (items, content, files, search, tags, blocks, themes, revisions) | yes (files, revisions, reports require it; items/content/search are public but return only published items without it) | no | no | no |
| Site API writes (items, content, outline, files, settings) | yes | yes | no | yes |

`assertSiteApiMutationRoutesAreSecured` in `src/app.js` guarantees every site mutation route requires
bearer + site token. Legacy handlers additionally re-check `body.site.name` against the token; always
include `{"site": {"name": "<siteName>"}}` in write bodies even though the v1 wrapper injects it.

### 2.7 Admin gate

System routes listed in `SystemV1AdminRoutes` (sites, themes, blocks, skeletons, status,
configuration/*) pass `validateSystemV1RouteAccess`. For `single-site` and `self-hosted-multi-site`
deployment profiles this is satisfied by a valid bearer. `haxiam-managed` is out of scope.

---

## 3. System API: sites

Source: `src/systemRoutes/v1/lifecycle.js` and `routes/*.js`.

### 3.1 List sites

```
GET /system/api/v1/sites  (bearer)
200 -> data = { id, title:"My sites", items:[ <site.json without items, plus location, slug, metadata.pageCount> ] }
```

Each item's `metadata.site.name` is the Site Name. `location` is `/_sites/<name>/`.

### 3.2 Site info

```
GET /system/api/v1/sites/{siteName}  (bearer)
200 -> data = { name, title, description, ..., links:{ self, clone, archive, download, downloadSkeleton, saveAsTemplate, siteApi } }
404 -> Site not found
```

### 3.3 Create site

```
POST /system/api/v1/sites  (bearer + user token)
{
  "site":  { "name": "<machine name>", "description": "", "theme": "clean-one", "license": "by-sa", "domain": null },
  "build": { "type": "skeleton", "structure": "from-skeleton",
             "items": [ { "id":"item-home-<uuid>", "title":"Home", "slug":"home", "order":0, "parent":null, "indent":0,
                          "content":"<p>Edit this page to get started on your HAX site!</p>",
                          "metadata": {"published":true, "hideInMenu":false, "tags":[]} } ] }
}
200 -> { status:200, data: <site JSONOutlineSchemaItem: id,title,location,slug,metadata,warnings?>, id, slug, link }
400 -> "Invalid theme supplied for site creation"
```

Facts from `routes/createSite.js` and the dashboard build (`app-hax/lib/v2/*.js`):

- `site.name` is passed through `generateMachineName` (lowercase, no spaces; the tutorial's "names
  cannot contain spaces" rule). The MCP must pre-validate and reject spaces with a helpful error
  rather than let the server silently rewrite the name.
- `site.theme` must be a key of `src/coreConfig/themes.json` (see §9). Default in the dashboard is
  `clean-one`.
- `site.license` accepts `by, by-sa, by-nd, by-nc, by-nc-sa, by-nc-nd`.
- `build.structure` values the server acts on: `from-skeleton` (uses `build.items`, or
  `build.skeletonMachineName` to load a named skeleton), `import` (uses `build.items` and
  `build.files`), and `build.type == "docx import"`. The current dashboard always sends
  `type:"skeleton", structure:"from-skeleton"` for a blank site with a one-item inline skeleton, and
  `type:<importType>, structure:"import", items, files` for imports.
- `build.skeletonMachineName`: file name (without `.json`), `meta.machineName`, or `meta.name` of a
  skeleton in `_config/user/skeletons`, `_config/skeletons`, or `src/coreConfig/skeletons`. When set,
  the skeleton's theme, description, license, and items win over the request.
- `build.files`: map of `files/<name>` to http(s) URL or staged path; best effort, skipped entries
  appear in `data.warnings`.
- Creating a site also `git init`s the site folder and commits.

### 3.4 Clone, archive, download, skeleton, template

All `POST /system/api/v1/sites/{siteName}/<op>` with body `{"site":{"name":"<siteName>"}}`, bearer +
user token.

| op | Effect | Response `data` |
|---|---|---|
| `clone` | copies folder to `getUniqueName(site.name)` (server picks the new name), new manifest id, rewrites file URLs | `{ detail: "/_sites/<cloneName>/..." }` (verify exact keys in `cloneSite.js` L135+) |
| `archive` | moves folder to `_archived/` | `{ name, detail: "Site archived" }` |
| `download` | zips the site to `_published/<site>.zip` | `{ link: "/_published/<site>.zip", name }`; then `GET {base}{link}` for bytes |
| `download-skeleton` | builds a skeleton JSON from the site | `{ link, name }` (verify) |
| `save-as-template` | stores the site as a skeleton under `_config/user/skeletons` | `{ ... }` (verify) |

### 3.5 Themes, skeletons, blocks (system level, bearer)

```
GET /system/api/v1/themes     -> data = map of themeMachineName -> { element, path, name, thumbnail, description, category[], hidden, priority, supportedPalettes }
GET /system/api/v1/skeletons  -> data = list/map of skeleton records (meta.name, meta.machineName, useCaseTitle, category, tags)
GET /system/api/v1/skeletons/{skeletonName} -> full skeleton { meta, site, build, theme }
GET /system/api/v1/blocks     -> available blocks and enabled flags
```

PATCH variants change instance configuration and are **out of scope** (admin settings).

### 3.6 Status and version

```
GET /system/api/v1/status          -> environment diagnostics (includes upload limit, default 50mb)
GET /system/api/v1/system/version  -> installed version
```

---

## 4. Site API: outline and items

Source: `src/siteRoutes/v1/items.js`, `routes/createNode.js`, `routes/deleteNode.js`,
`routes/saveOutline.js`, `src/lib/nodeDetailOperations.js`, `src/lib/JSONOutlineSchemaItem.js`.

All paths below are relative to `{base}/_sites/{siteName}/x/api/v1/`.

### 4.1 Item record

```
{ id, title, slug, parent|null, indent, order, location, description,
  metadata: { created, updated, published, locked, hideInMenu, pageType, tags, relatedItems, image, icon,
              accentColor, theme, files:[uuid], images:[], videos:[], overridePathauto },
  region|null, tags[], published, content?, links{}, exports{}, jsonld?, haxElementSchema?, related? }
```

Item ids look like `item-<uuid4>`. Default new page location is `pages/<id>/index.html` and default
content is `<p></p>`.

### 4.2 List and get

```
GET items?filter.parent=&filter.ancestor=&filter.depth=&filter.tags=&filter.published=&filter.pageType=&filter.region=
          &page.limit=&page.offset=&sort=&fields=&include=&format=json|md|yaml|xml|html
GET items/{idOrSlug}?include=content
```

Anonymous calls return only published, non-hidden items; send the bearer to see everything.
`include=content` adds the page body to each record. Response `data` for the list is an
`ItemCollection` `{ count, total, page:{...}, items:[...] }`.

### 4.3 Create page(s)

```
POST items  (bearer + site token)
single: { "site":{"name":s}, "node": { "id":null, "title":"page", "location":null, "duplicate":"<existing id>"|null, "contents":"<html>"|null },
          "parent": "<id>"|null, "order": <int>|null, "indent": <int>|null, "description": "", "metadata": {...}|null }
bulk:   { "site":{"name":s}, "items":[ { id?, title, slug?, parent?, indent?, order?, content|contents, metadata?, delete? } ] }
200 -> data = created item (single) or the last created item (bulk; verify) 
403 -> "Adding pages is disabled for this site" (platform feature addPage off)
```

- `node.contents` seeds the page body (sanitised, inline data-URI images are materialised into
  Files, `metadata.files` set).
- `node.duplicate` copies another page's content.
- The bulk form is what Document Import uses. Items with `delete:true` are skipped. One git commit
  for the batch.
- Tutorial mapping: "Add > Page" is the single form with `title:"page"`.

### 4.4 Update page details (operations)

```
PATCH items/{idOrSlug}  (bearer + site token)
{ "site":{"name":s}, "operation": "<op>", ...fields }
```

| operation | fields | effect (nodeDetailOperations.js) |
|---|---|---|
| `setTitle` | `title` | title; regenerates slug when Pathauto on and no override |
| `setDescription` | `description` | |
| `setTags` | `tags` (string or array) | |
| `setIcon` | `icon` | |
| `setMedia` / `setImage` | `media` / `image` | metadata.image |
| `setRelatedItems` | `relatedItems` | |
| `setLocked` | `locked` | |
| `setPublished` | `published` | |
| `setHideInMenu` | `hideInMenu` | |
| `setSlug` | `slug` | also sets `metadata.overridePathauto = true` |
| `setOverridePathauto` | (verify field) | |
| `moveUp` / `moveDown` | none | swap order with sibling |
| `indent` / `outdent` | none | reparent under previous sibling / to grandparent |
| `setParent` | `parent`, `order` | |

One operation per request; the MCP sequences several for a multi-field update. Response `data` is the
updated item.

### 4.5 Delete page

```
DELETE items/{idOrSlug}  (bearer + site token; body optional {"site":{"name":s}})
200 -> data = deleted item
403 -> "Delete is disabled for this site"
```

Orphaned children are re-parented to the root and pushed to the end. The page folder stays on disk.

### 4.6 Replace the whole outline

```
PATCH site/outline  (bearer + site token)
{ "site":{"name":s}, "items":[ { id, title, parent|null, indent, order, slug?, metadata? , duplicate?, contents? } ] }
200 -> data = { items:[...] }
403 -> "Outline operations are disabled for this site" (feature outlineDesigner)
```

Items whose `id` is unknown are created (server assigns a new id; the response maps them). Location
is server-controlled. Slugs follow Pathauto unless `metadata.overridePathauto`. Items **omitted**
from the array are not deleted (verify in `saveOutline.js` tail before relying on it; the MCP's
`reorder_pages` must always send the complete list).

### 4.7 Slugs

```
POST site/normalize-slugs  -> regenerates all slugs from titles per Pathauto
```

### 4.8 Revisions (git-backed; bearer)

```
GET  items/{idOrSlug}/revisions                          -> data = { revisions:[ {revisionNumber, hash, shortHash, author, authorEmail, timestamp, date, message} ] }
GET  items/{idOrSlug}/revisions/{revisionId}             -> data = { nodeId, nodeSlug, nodeTitle, revision, content }
POST items/{idOrSlug}/revisions/{revisionId}/restore     -> restores as a new commit (bearer + site token)
```

### 4.9 Search and tags (public reads; send bearer for unpublished)

```
GET search?q=<required>&filter.*&page.*&sort&fields  -> data = SearchCollection
GET tags                                             -> data = tag frequencies
```

---

## 5. Site API: content

Source: `src/siteRoutes/v1/content.js`, `routes/saveNode.js`, `src/lib/HAXCMS.js`
`pageBreakParser` ~L4334 and `parse_attributes` ~L4318, `src/lib/sanitizeContent.js`.

### 5.1 Read

```
GET content/{idOrSlug}?format=json|md|html  (bearer)
200 -> data = { id, slug, title, format, mode, body:"<html>", links }
GET content?mode=concat&format=md            -> whole site as one markdown string
GET content?mode=list                        -> ContentRecord per item
```

`body` is the stored page file. It does **not** contain a `<page-break>`; HAXcms strips it on save.

### 5.2 Write (the Page Break rule)

```
PATCH content/{idOrSlug}  (bearer + site token)
{ "site":{"name":s}, "body":"<page-break ...></page-break><p>...</p>...", "schema":[...optional...], "details":{...optional...} }
200 -> data = updated item
400 -> "Content body is required"
500 -> "failed to write"
```

`updateContent` forwards to the legacy `saveNode`, which runs `pageBreakParser(body)`. The parser
only yields pages for `<page-break ...>...</page-break><content>` segments. **A body with no
`<page-break>` produces zero segments, nothing is written, and the call still returns 200.** The MCP
must therefore always send:

```html
<page-break item-id="<id>" title="<title>" slug="<slug>" path="<slug>" parent="<parentId or omit>"
            published="published" locked="locked" hide-in-menu="hide-in-menu" page-type="<type>"
            tags="a,b" related-items="id1,id2" image="<url>" icon="<icon>" accent-color="<color>"
            description="<text>" developer-theme="<themeKey>" depth="<indent>" order="<order>"
            override-pathauto="true"></page-break>
<p>first block</p>
...
```

Attribute rules from `saveNode.js` L83-330:

- Every attribute must be `name="value"`; boolean flags must be written with a value
  (`published="published"`). `parse_attributes` returns `null` for value-less attributes and the
  parser's `published ` → `published="published"` rewrite only works when followed by a space.
- **Absence means false** for `published`, `hide-in-menu`, `override-pathauto`; absence **deletes**
  `page-type`, `related-items`, `image`, `tags`, `icon`, `accent-color`, `link-url`, `link-target`,
  `developer-theme`, and `description` (verify description). The MCP must build the page break from
  the current item record so a content save never clears details by accident.
- `title` is entity-decoded and tag-stripped. `slug` `x` becomes `x-x`; `x/...` becomes `x-x/...`.
- When Pathauto is on and `override-pathauto` is not set, the slug is regenerated from the title.
- `item-id` must equal the item being saved; other ids in extra page breaks create new pages
  (multi-page splitting), which the MCP must not use.
- The content after `</page-break>` is sanitised with DOMPurify: `script, svg, frame, frameset,
  applet, meta, link, base, style` tags are removed; `on*` and `style` attributes are removed; URL
  attributes must be `http`, `https`, `mailto`, `tel`, or `#`; iframes keep only `src, title, width,
  height, loading, allow, allowfullscreen, referrerpolicy, sandbox`. Custom element tags and
  hyphenated attributes survive. `code-sample`, `runkit-embed`, `web-container` `<template>`
  contents are escaped.
- `schema` (optional array of `{tag, properties}`) is used only to fill `metadata.images` and
  `metadata.videos` for `img`, `a11y-gif-player`, `media-image` (`source`), `video-player`
  (`source`). The MCP should send it for those tags.
- `metadata.files` is rebuilt from a content path scan on every save.
- Each save is a git commit `Page details updated: <title> (<id>)`.

### 5.3 Site-wide text replace

```
PATCH content  (bearer + site token)  { "site":{"name":s}, ...search/replace fields }   (verify body in content.js replaceContent)
```

---

## 6. Site API: files

Source: `src/siteRoutes/v1/files.js`, `src/lib/HAXCMSFile.js`, `src/lib/fileOpsRateLimiter.js`.

```
GET  files?filter.type=image|video|audio|document&filter.extension=&filter.startsWith=&filter.nameContains=&filename=&page.limit=&page.offset=&sort=&fields=  (bearer + site token)
     -> data = { count, total, page, files:[FileRecord], orphans:[...] }
POST files  multipart/form-data  field "file-upload" (also accepts "upload" or "file"), optional "nodeId"   (bearer + site token)
     -> data = { file: { path, fullUrl, url, type, name, size, uuid, width?, height? } }
GET  files/{uuid}                       -> data = FileRecord
PATCH files/{uuid} { "operation": "rename"|"convert-jpg"|"scale"|"sepia"|"black-and-white"|"rotate-90"|"compress"|"duplicate", "newName"?, "size"?, "level": "light"|"medium"|"heavy"|"maximum" }
DELETE files/{uuid}
```

`FileRecord`: `{ path, fullUrl, url, mimetype, name, size, dateCreated, width?, height?, uuid }`.
Use `url` (site-relative, e.g. `files/Songline_1.png`) or `fullUrl` as the `source` of a
`media-image`. Upload limit defaults to `50mb` (`HAXCMS_UPLOAD_LIMIT`). Allowed extensions are gated
server-side by `HAXCMSFile.ALLOWED_MIME_BY_EXTENSION`; expect 400 on mismatch. Mutations are limited
to 500 per 5 minutes per user:site, then 429 with `Retry-After`.

---

## 7. Site API: settings

Source: `src/siteRoutes/v1/site.js` (dispatch) and `routes/saveManifest.js`,
`saveAppearanceSettings.js`, `saveSeoSettings.js`, `saveEditorSettings.js`, `saveAllowedBlocks.js`,
`savePlatformSettings.js`.

```
GET   site                       -> data = site summary (title, description, license, metadata, counts, links)
PATCH site                       -> saveManifest: { "site":{"name":s}, "manifest": { "site":{...}, "theme":{...}, "author":{...}, "seo":{...} } }
PATCH site/appearance            -> { "site":{"name":s}, "manifest": { "theme": { <allowed theme keys> } } }   (only keys site,manifest allowed; manifest only key theme)
PATCH site/seo                   -> { "site":{"name":s}, "seo": { description, domain, lang, gaID, canonical, private, pathauto, publishPagesOn, logo } }  (verify wrapper key name)
PATCH site/editor                -> { "site":{"name":s}, "platform": { "audience": "novice"|"expert" } }
PATCH site/blocks                -> { "site":{"name":s}, "platform": { "allowedBlocks": ["p","media-image",...] | null } }   (tags must be plain HTML or in wc-registry)
PATCH site/platform              -> { "site":{"name":s}, "platform": { "features": { <featureKey>: bool } } }  (verify nesting)
POST  site/updateAlternativeFormats { "format"? }  -> regenerates md/json alternates
```

Manifest field keys (flat, dash-separated, grouped by tab as in `src/coreConfig/siteFields.json`):

| tab | keys |
|---|---|
| site | `manifest-title`, `manifest-description`, `manifest-metadata-site-domain`, `manifest-metadata-site-tags`, `manifest-metadata-site-logo`, `manifest-metadata-site-homePageId` |
| theme | `manifest-metadata-theme-element`, `manifest-metadata-theme-variables-image`, `-imageLink`, `-imageAlt`, `-cssVariable`, `-palette`, `-icon`, `manifest-metadata-theme-regions-header|sidebarFirst|sidebarSecond|contentTop|contentBottom|footerPrimary|footerSecondary` (arrays of item ids) |
| author | `manifest-license`, `manifest-metadata-author-image|name|email|phone|location|website|website2|socialLink|socialLink2` |
| seo | `manifest-metadata-site-settings-private|canonical|lang|pathauto|publishPagesOn|sw|forceUpgrade|gaID` |

`cssVariable` accepts either `--simple-colors-default-theme-<color>-7` or the bare `<color>` name.
Platform feature keys: `addPage, saveAndEdit, deletePage, outlineDesigner, styleGuide, insights,
siteManifest, themeManifest, authorManifest, seoManifest, pageBreak, addBlock, popularGizmos,
recentGizmos, contentMap, viewSource, uploadMedia, onlineMedia, community, pageTemplates,
blockTemplates`. A feature set to `false` makes the corresponding routes reply 403.

**Git settings**: `metadata.site.git` (`vendor, branch, autoPush, url`) drives automatic push after
every commit (`HAXCMS.js` gitCommit ~L900). No v1 route writes these keys; `saveManifest` has no
`git` handling. See PLAN Phase 6 for how `configure_site_git` must handle this (verify first; if no
route accepts it, the tool returns a clear "unsupported by this HAXcms version" error).

---

## 8. Site API: read-only catalogs, exports, views

```
GET blocks                          -> block records + usage counts (bearer optional)
GET blocks/{tag}                    -> one block; ?include=haxProperties,haxSchema,haxElementSchema
GET blocks/{tag}/usage              -> pages using the block
GET schemas?filter.kind=haxProperties&filter.webcomponentName={tag}  -> haxProperties JSON when the server can find <pkg>/lib/<tag>.haxProperties.json
GET custom-elements[/{tag}]         -> wc-registry entries (tag, import, package); schema fragments are stubs unless included
GET themes | themes/active | themes/{name}
GET regions[/{name}] , reports[/{name}], analytics, views[/{id}[/results]], displays
GET site/export/{format}            format in zip|markdown|pdf|docx|epub|html|skeleton ; binary for pdf/docx/epub/html, descriptor JSON otherwise (verify zip/markdown/skeleton behaviour)
GET items/{idOrSlug}/export/{format} format in pdf|docx|html|md|json|yaml|xml|epub ; binary download with Content-Disposition
POST site/export/{format}           -> descriptor metadata only (bearer + site token)
```

haxProperties availability: 188 `*.haxProperties.json` files exist in the instance's public build
(`src/public/build/es6/node_modules/@haxtheweb/<pkg>/lib/<tag>.haxProperties.json`), for example
`self-check`, `a11y-collapse`, `stop-note`, `multiple-choice`, `fill-in-the-blanks`, `flash-card`,
`vocab-term`, `image-compare-slider`, `wikipedia-query`, `image-gallery`, `page-break`,
`page-section`, `block-quote`. **Not** available as JSON (defined inline in the element's JS):
`media-image`, `video-player`, `grid-plate`, `accent-card`, `place-holder`, `simple-cta`,
`code-sample`, `audio-player`, `citation-element`, `license-element`, `lrndesign-timeline`,
`md-block`, `learning-component`. For those the bundled catalog is the only source.

---

## 9. Themes (from `src/coreConfig/themes.json`)

Visible (not hidden) machine names: `bootstrap-theme`, `clean-one` (Course, default),
`clean-portfolio-theme`, `clean-two`, `glossy-portfolio-theme`, `haxma-theme`, `journey-theme`,
`learn-two-theme`, `link-card-theme`, `polaris-flex-sidebar`, `polaris-flex-theme`,
`polaris-invent-theme`, `polaris-theme`, `resume-theme`, `spacebook-theme`, `terrible-*` (5),
`twenty-six-theme`. Hidden but valid: `app-hax-theme`, `chamfer-theme`, `collections-theme`,
`ddd-brochure-theme`, `haxcms-blank-theme`, `haxcms-json-theme`, `haxcms-print-theme`,
`haxor-slevin`, `journey-sidebar-theme`, `journey-topbar-theme`, `outline-player`, `simple-blog`,
`training-theme`. Always fetch the live list; never hard-code beyond defaults.

Bundled skeletons (`src/coreConfig/skeletons/`): `default-starter`, `online-course-clean-one`,
`Clean-One-Blog-Skeleton`, `Art-Portfolio-Skeleton`, `portfolio-skeleton`,
`resume-journey-skeleton`, `Student-Club-Skeleton`, `iscgraduateportfolio`,
`docs-haxma-hax-create`. Skeleton file shape: `{ meta:{name, machineName?, description, useCaseTitle,
category[], tags[]}, site:{name, description, theme, license?}, build:{type:"skeleton",
structure:"from-skeleton", items:[...]}, theme:{hexCode, cssVariable, icon, image} }`.

---

## 10. System API: imports and converters

Source: `src/systemRoutes/v1/routes/import*.js`, `convert*.js`, `siteImport.js`, `imports/*.js`.
All `POST /system/api/v1/actions/<name>` or `/system/api/v1/site/import/{platform}`, bearer + user
token.

### 10.1 Document import (returns items; does not create pages)

```
POST actions/import-docx | import-pptx | import-html | import-xlsx | import-pdf
multipart/form-data: file=<binary>, method="site"|"branch"|"page", type="course"|"portfolio"|"", parentId="<item id>"?
200 -> data = ImportData { items:[ {id, title, slug, parent, indent, order, content|contents, metadata} ], filename, files?:{}, siteFiles?:{}, site?:{license} }
```

`method`: `site` builds a whole outline; `branch` nests everything under `parentId`; `page` yields a
single page. To apply to an existing site: `POST _sites/{s}/x/api/v1/items` with `{items}` (§4.3
bulk). To create a new site: `POST /system/api/v1/sites` with `build:{type:"<kind> import",
structure:"import", items, files}`.

### 10.2 Platform import

```
POST site/import/{platform}   platform in haxcms|html|pressbooks|gitbook|notion|wordpress|elmsln|drupal-book|plone|openstax|vitepress
application/json { "repoUrl": "<url>", "method": "site", "type": "", "parentId": null }  (html also accepts multipart file)
200 -> ImportData ; 400 unsupported platform ; 422 unprocessable source
```

Remote fetches go through an SSRF guard (`safeFetch`); private addresses are refused.

### 10.3 Converters (stateless)

| operationId | path | input | output |
|---|---|---|---|
| docxToHtml | actions/docx-to-html | multipart `file` | `{ data: { html } }` (verify key) |
| htmlToDocx | actions/html-to-docx | json `{ html }` | base64 DOCX |
| mdToHtml | actions/md-to-html | json `{ md }` (verify key) | html |
| htmlToMd | actions/html-to-md | json `{ html }` | markdown |
| prettyHtml | actions/pretty-html | json `{ html }` | html |
| jsonToYaml | actions/json-to-yaml | json | yaml |
| yamlToJson | actions/yaml-to-json | json `{ yaml }` | json |
| htmlToPdf | actions/html-to-pdf | json `{ html }` | base64 PDF (needs Chrome on the instance) |
| xlsxToCsv | actions/xlsx-to-csv | multipart `file` | csv |
| pdfToHtml | actions/pdf-to-html | multipart `file` | html |
| pptxToHtml | actions/pptx-to-html | multipart `file` | html |
| docxToPdf | actions/docx-to-pdf | multipart `file` | base64 PDF |

The exact request and response keys are in `specs/system-spec.yaml`; the generator reads them from
there, so the table above is orientation only.

---

## 11. Running an instance for tests

Source: `test/e2e/helpers/harness.cjs`, `src/lib/HAXCMS.js` ~L3500-3600, `src/app.js` L139.

Minimal recipe for an isolated instance (what the MCP test harness reproduces in Python):

1. `mkdir <runtime>/_sites`, `mkdir <runtime>/_config`, write empty `<runtime>/_config/.isHAXcmsConfig`.
2. Copy from the package's `boilerplate/systemsetup/`: `config.json`, `my-custom-elements.js`,
   `userData.json`, `config.php`, `.htaccess`, `.user-files-htaccess` into `_config/`. Create
   `_config/tmp`, `cache`, `user/files`, `user/skeletons`, `skeletons`, `settings`, `node_modules`.
3. Write `_config/.user` as `{"name":"<user>","password":"<pass>"}` (plaintext is accepted and
   upgraded to a scrypt hash on first login). Do **not** use `admin`/`admin`; the server refuses to
   start with default credentials unless `HAXCMS_ALLOW_DEFAULT_CREDS=1`.
4. Environment: `HAXCMS_ROOT=<runtime>/` (**trailing slash required**), `PORT=<free port>`,
   `HOME=<temp>`, `GIT_AUTHOR_NAME/EMAIL`, `GIT_COMMITTER_NAME/EMAIL` set, `NODE_ENV` unset,
   `HAXCMS_DISABLE_JWT_CHECKS` **unset**.
5. Start `node <pkg>/dist/app.js` (not `dist/local.js`, which forces `HAXCMS_DISABLE_JWT_CHECKS`).
   Ready when `GET {base}/system/api/v1/status` answers (any status) or the stdout banner shows the
   URL.
6. Login per §2.1.

Package facts: `@haxtheweb/haxcms-nodejs@26.8.1`, `engines.node >= 18.20.3`, `main: dist/index.js`,
`files: [dist]`, `dist/app.js` present. Heavy optional runtime deps (`sharp`, `puppeteer-core`)
install with the package; PDF export needs a Chrome binary (`PUPPETEER_EXECUTABLE_PATH`) and is
allowed to be skipped in tests when absent.

Upstream test locations useful as behavioural references: `test/api-conformance/site-spec.conformance.test.cjs`,
`test/e2e/*.e2e.test.cjs`, `test/unit/sanitize-content.test.cjs`, `test/unit/node-detail-operations.test.cjs`.

---

## 12. Environment variables the instance reads

`HAXCMS_ROOT`, `PORT`, `HAXCMS_DISABLE_JWT_CHECKS`, `HAXCMS_ALLOW_DEFAULT_CREDS`,
`HAXCMS_UPLOAD_LIMIT` (default 50mb), `HAXCMS_ENABLE_SSL`, `HAXCMS_SSL_KEY/CERT/CA`, `NODE_ENV`,
`PUPPETEER_EXECUTABLE_PATH`, `YOUTUBE_API_KEY`, `IAM_PRIVATE_ADDRESS_SPACE`, `HAXCMS_CLI_QUIET`.
