# HAXcms MCP

A Python MCP server that lets an AI agent operate a self-hosted HAXcms NodeJS instance the way a human author does through the HAX dashboard and editor. The server is a client of HAXcms, not a replacement for it: HAXcms remains the system of record for sites, pages, files, and settings.

This file is the glossary. It defines the words used in `PLAN.md`, in tool names, and in code. It contains no implementation detail; the HTTP contract lives in `docs/haxcms-api-reference.md` and the build plan lives in `PLAN.md`.

## Language

### The two systems

**HAXcms**:
The open-source CMS (Headless Authoring eXperience) from Penn State that stores each website as a folder of JSON and HTML. This project targets the NodeJS backend, package `@haxtheweb/haxcms-nodejs`, pinned at version 26.8.1.
_Avoid_: HAX (that is the editor), haxcms-php, "the backend" without qualification

**HAX**:
The in-browser block editor that ships with HAXcms and lets a human add and configure Blocks on a Page. Where this project says "a human does X in HAX", it means the editor UI.
_Avoid_: using HAX to mean the CMS

**HAXcms MCP**:
This project. An MCP server exposing Tools, Resources, and Prompts that map onto HAXcms operations.
_Avoid_: "the wrapper", "the proxy", "the bridge"

**Instance**:
One running HAXcms NodeJS server, addressed by a base URL, holding many Sites. The MCP server talks to exactly one Instance per process.
_Avoid_: host, deployment, backend

**Agent**:
The LLM-driven client that calls the MCP server's Tools. The Agent plays the role of the human author.
_Avoid_: user (ambiguous with the HAXcms login user), model, assistant

**Operator**:
The person who configures and runs the MCP server (base URL, credentials, limits).
_Avoid_: admin (that is the HAXcms login user name)

### Authentication

**Login User**:
The single HAXcms account the MCP server authenticates as. HAXcms NodeJS has exactly one configured user per Instance.
_Avoid_: account, principal

**Access Token**:
The short-lived (15 minute) JWT that HAXcms issues on login and that every authenticated request carries as a bearer token.
_Avoid_: JWT alone, session token

**Refresh Token**:
The 24-hour cookie HAXcms sets on login. Presenting it to the refresh endpoint yields a new Access Token and rotates the cookie.
_Avoid_: refresh cookie, long-lived token

**Site Token**:
A per-Site HMAC string HAXcms derives from the Login User and the Site Name. Every write to a Site must carry it in the `X-HAXCMS-Site-Token` header. It is obtained from the connection-settings endpoint and never computed locally.
_Avoid_: site key, CSRF token

**User Token**:
The HMAC string HAXcms derives from the Login User alone. Some system-level writes (site creation, document import) carry it in the `X-HAXCMS-User-Token` header.
_Avoid_: user key

**Read-Only Mode**:
An Operator setting under which the MCP server refuses every Tool that would change state on the Instance and says so in the error.
_Avoid_: safe mode, dry run

### Sites

**Site**:
One website managed by HAXcms: a folder containing a Manifest, Pages, and Files. Also called a "journey" in the dashboard.
_Avoid_: journey, project, course (a course is one kind of Site)

**Site Name**:
The machine name of a Site: lowercase, no spaces, used as its folder name and in URLs. It is the identifier every Site-scoped Tool takes.
_Avoid_: slug (that is a Page property), site id

**Default Site**:
The Site Name the MCP server uses when a Tool is called without one. Set by the Operator; optional.

**Manifest**:
The Site's `site.json`, following the JSON Outline Schema. It holds the Site's title, description, license, metadata, theme, settings, and the ordered list of Items that forms the Outline.
_Avoid_: site.json in prose, config

**Theme**:
The visual design applied to a whole Site, identified by a machine name such as `clean-one` or `learn-two-theme`. A Site has exactly one active Theme, plus optional palette, accent icon, banner image, and Regions.
_Avoid_: template, skin, layout

**Region**:
A named slot in a Theme (header, sidebarFirst, sidebarSecond, contentTop, contentBottom, footerPrimary, footerSecondary) that shows the content of chosen Pages on every Page.

**Skeleton**:
A reusable Site starting structure: a Theme plus a set of pre-titled Pages with placeholder content. Creating a Site from a Skeleton copies that structure.
_Avoid_: template (HAXcms also uses "save as template", which produces a Skeleton)

**Archive**:
Moving a Site out of the active list into an archived folder. Reversible on disk, but the API exposes no restore.
_Avoid_: delete (there is no site delete)

**Clone**:
Copying a Site to a new, automatically generated Site Name.

**Export**:
A downloadable artifact produced from a Site or a Page: a zip of the whole Site, or a PDF, DOCX, EPUB, Markdown, or HTML rendering.
_Avoid_: publish, download (as a noun)

**Publishing**:
Making a Site available outside the Instance. In HAXcms NodeJS this is either an Export, or automatic git push to a configured branch after every save. There is no dedicated publish action.

### Outline and pages

**Outline**:
The ordered tree of Items in a Manifest: parents, children, and sibling order. This is the Site's navigation.
_Avoid_: menu, tree, hierarchy

**Item**:
One entry in the Outline, as stored in the Manifest: id, title, slug, parent, order, indent, location, description, and metadata. An Item points at a Page.
_Avoid_: node (upstream legacy name), entry

**Page**:
The authored HTML document an Item points at, stored at the Item's location. In everyday use "page" covers both the Item and its content; the glossary keeps them apart only where the distinction matters.
_Avoid_: post, article, document

**Page Content**:
The HTML body of a Page, made of Blocks. This is what the agent reads and edits.
_Avoid_: body, HTML, source

**Page Details**:
The Item-level metadata a human edits in the editor's "page details" panel: title, slug, published, locked, hidden in menu, page type, tags, related items, image, icon, description, per-page theme.

**Page Break**:
The invisible element at the top of a Page's HTML that carries Page Details into a content save. HAXcms reads Page Details from it when saving content and stores none of it in the Page file. Every content save must include one.
_Avoid_: header element, meta block

**Slug**:
The URL path segment of an Item. Nested Items have nested slugs. When Pathauto is on, HAXcms regenerates slugs from titles.

**Pathauto**:
A Site setting under which HAXcms derives every Item's Slug from its title automatically unless the Item has an explicit override.

**Published**:
An Item flag. Unpublished Items are hidden from anonymous readers and from navigation. New Pages default to published when saved through HAX.

**Revision**:
A git commit of a Page in the Site's history. Revisions can be listed, read, and restored.
_Avoid_: version, history entry

### Content

**Block**:
One top-level element of Page Content: a native HTML element such as a paragraph or heading, or a HAX web component such as `media-image` or `video-player`. Blocks are the unit a human adds, selects, moves, and configures in HAX.
_Avoid_: element, component, gizmo (upstream editor name), widget

**Core Block**:
One of the roughly thirty Blocks this project gives a dedicated typed Tool. Listed in `PLAN.md`.

**Block Catalog**:
The set of Blocks that are legal in Page Content, with each Block's attributes, slots, and an example. Merged from a bundled catalog in this repository and from the Instance's live block and schema endpoints.
_Avoid_: registry (upstream uses wc-registry for the loader map), schema list

**haxProperties**:
The upstream schema format that describes a Block's configurable attributes and slots. It is the source of truth for the Block Catalog.

**Anchor**:
The way the Agent points at an existing Block inside Page Content: a text snippet the Block contains, or a tag selector, plus an optional occurrence when several Blocks match.
_Avoid_: index, position (position is where a new Block goes relative to an Anchor)

**Placement**:
Where a new Block goes relative to an Anchor: before, after, or replacing it; or append or prepend when there is no Anchor.

**Sanitisation**:
HAXcms's server-side cleaning of saved Page Content: it strips scripts, styles, event handlers, and unsafe URLs. The MCP never sanitises; it relies on HAXcms.

### Files and imports

**File**:
An asset uploaded to a Site (image, PDF, audio, video), identified by a stable UUID and served from the Site's files folder.
_Avoid_: asset, upload (as a noun), media (media is a Block family)

**File Operation**:
A transformation HAXcms applies to a stored image File: rename, convert to JPG, scale, sepia, black and white, rotate, compress, duplicate.

**Source**:
How a binary input reaches a Tool: a local path on the MCP host, an http(s) URL the MCP fetches, or inline base64.

**Document Import**:
Turning an uploaded DOCX, PPTX, HTML, XLSX, or PDF into Items and Page Content, either inside an existing Site or as a brand-new Site.
_Avoid_: upload (that is a File)

**Platform Import**:
Turning a remote site from another system (HAXcms, HTML, Pressbooks, GitBook, Notion, WordPress, ELMSLN, Drupal Book, Plone, OpenStax, VitePress) into a new Site.
_Avoid_: migration

**Converter**:
A stateless format conversion offered by HAXcms with no Site involved: DOCX to HTML, Markdown to HTML, HTML to PDF, and so on.

### MCP surface

**Tool**:
An MCP action the Agent can call. Named `verb_noun` in snake_case, for example `create_site`, `add_image`.

**Resource**:
Read-only data the Agent can load by URI, for example the Block Catalog or a Site's Outline.

**Prompt**:
A reusable instruction template the Agent can invoke, describing a whole journey such as building a Page from a brief.

**Typed Block Tool**:
A Tool dedicated to one Core Block with named parameters, for example `add_video(source, title)`. Contrast with the generic `add_block(tag, attributes, inner_html)`.

**Composite Tool**:
A Tool that performs several HAXcms calls as one action, for example importing a document and creating its Pages.

**Generated Tool**:
A Tool whose Python source is emitted by the repository's generator from the vendored OpenAPI spec rather than written by hand. Only Converters are Generated Tools.

**Destructive Tool**:
A Tool that removes or archives data: delete page, delete file, archive site. Marked with the MCP destructive hint and refused in Read-Only Mode.

### Rate limiting

**Outbound Budget**:
The token-bucket limit on HTTP requests the MCP server sends to the Instance. One Tool call may spend several tokens.
_Avoid_: rate limit alone (ambiguous with HAXcms's own limiters), throttle

**Back-off**:
The bounded wait-and-retry the MCP performs when the Instance answers 429 or the Outbound Budget is empty.

### Delivery process

**Phase**:
One self-contained slice of the build in `PLAN.md`, ending with its own test suites, a tag, and a `PROGRESS.md` entry.

**Session**:
One uninterrupted context window of the implementing agent. Independent Phases get fresh Sessions; overlapping Phases share one.

**Handoff**:
The `PROGRESS.md` entry a Phase writes so the next Session can start with no memory of the previous one.
