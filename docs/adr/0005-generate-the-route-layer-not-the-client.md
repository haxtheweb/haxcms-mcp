# Generate the route layer from the spec; keep request bodies and responses hand-written

Status: accepted for the route layer ([haxtheweb/issues#3137](https://github.com/haxtheweb/issues/issues/3137), stretch goal).

`client/system_api.py` and `client/site_api.py` used to spell out every method, path and auth mode by hand (`client.request("PATCH", client.site_path(site, "site/seo"), auth="bearer+site")`). When HAXcms renamed a route, nothing noticed until a user hit a 404. ADR-0002 already generates the twelve converter *tools* from the spec. This extends generation to every operation's *route*. Bodies and responses stay hand-written.

`scripts/gen_routes.py` writes `generated/system_routes.py` and `generated/site_routes.py`:
- One builder per operation, named after its `operationId` in snake_case (`update_site_seo(site)`, `get_item_revision_by_id(site, id_or_slug, revision_id)`).
- Each builder returns a `Route`: method, full path, and the auth the spec's `security` block requires.
- Path parameters are percent-encoded with `safe=""`, so nested slugs stay one segment.
- Site routes get the `/_sites/{site}` mount.
- Each module also carries an `OPERATIONS` table for lookups by id (the import and converter dispatchers).

The hand-written client calls `client.call(routes.update_site_seo(site), json=body, site=site)`. Auth comes from the spec. An explicit `auth=` at a call site means we deliberately send more than the spec requires: item, search and tag reads are open routes that show unpublished pages to an authenticated user.

We did not generate the whole client. The specs' request schemas are loose (many bodies are `type: object` with a description). Several behaviors only exist in the HAXcms source:
- the multipart field names
- `PATCH items/{id}` taking one `operation` per request
- the page-break envelope on content saves
- converters that take a file despite a JSON schema in the spec

Those live in the hand-written functions, their docstrings and their tests. Generating them would either lose them or move them into a large override table that is harder to read than the code.

## Consequences

- When a route moves, regenerate (`scripts/gen_routes.py`). When an operation disappears or its parameters change, the hand-written caller fails `mypy` and imports instead of failing at runtime.
- The nightly drift workflow regenerates the routes from `haxcms-nodejs` `main` and type-checks the client. When the specs drift, the run shows whether a plain regenerate is enough.
- CI runs `gen_routes.py --check`, like the converters.
- `client/auth.py` (login, refresh, logout, connection-settings) and `compat.py` still build their few session paths by hand for now, because open PRs touch those lines. Moving them is a mechanical follow-up.
- Next candidate: generate response *models* for the operations whose response schemas are precise (files, revisions), one model at a time, each checked against the live suite.
