# The MCP server is an HTTP client of a running HAXcms NodeJS, not a reimplementation

We needed an MCP server that gives an agent every capability a human has in HAXcms. We decided to
build it as a typed HTTP client of a running `@haxtheweb/haxcms-nodejs` instance (pinned 26.8.1),
using its system API (`/system/api/v1`) and site API (`/_sites/{site}/x/api/v1`) as the contract.
We rejected reimplementing the CMS in Python (reading and writing `site.json` and page HTML on disk)
because that would mean porting DOMPurify sanitisation, Twig rendering, sharp image operations,
Puppeteer PDF export, git revisions, and eleven site importers, and it would drift from upstream on
every release. Upstream already ships an `mcp.enabled` / `mcp.readOnly` policy in its config,
signalling that an MCP layer is expected to sit in front of the HTTP API.

## Consequences

- The MCP server needs network access and credentials for one HAXcms instance; it has no value
  offline.
- Every behaviour we depend on (Page Break rule, token acquisition via connection-settings,
  sanitisation) is upstream's; we document it in `docs/haxcms-api-reference.md` and pin the version.
- Integration and functional tests must spawn a real HAXcms (Node required in CI).
