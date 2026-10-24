# Converter tools are generated at build time from a vendored OpenAPI spec

HAXcms exposes twelve stateless format converters (`docx-to-html`, `html-to-pdf`, ...). Rather than
hand-write twelve near-identical tools, or construct them at runtime from the live instance's
`/system/api/v1/openapi.json`, we vendor `system-spec.yaml` and `site-spec.yaml` into `specs/`
pinned to the HAXcms version and run `scripts/gen_tools.py` to emit a committed, reviewable
`src/haxcms_mcp/generated/converters.py`. Runtime generation was rejected because it makes the tool
list depend on server availability at startup, cannot be unit-tested offline, and makes the schema
snapshot (regression suite) nondeterministic. Only converters are generated; every other tool is
hand-designed because its value lies in agent-oriented parameters and composition, which a spec
cannot express.

## Consequences

- Upgrading HAXcms means running `scripts/sync_specs.py`, regenerating, and reviewing the diff.
- CI fails if the generated file drifts from the spec (`gen_tools.py --check`).
