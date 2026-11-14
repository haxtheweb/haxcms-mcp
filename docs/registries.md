# Listing haxcms-mcp in MCP registries

Agents and their users find MCP servers through registries. This page says what a listing needs
and what is still missing. Nothing here is automated yet.

## What is in the repository

- [`server.json`](../server.json): the server's registry entry (name, description, package,
  transport, the environment variables a person must set). `tests/unit/test_registry_metadata.py`
  keeps its version equal to `pyproject.toml` and checks the README carries the ownership line.
- The README contains `<!-- mcp-name: io.github.haxtheweb/haxcms-mcp -->`. The official registry
  reads the package's README from PyPI and looks for that line to prove the package and the
  registry name belong together.

## The official MCP Registry

<https://registry.modelcontextprotocol.io> stores metadata only; the installable package has to
be somewhere it can check. For a Python server that is PyPI.

1. **Publish the package to PyPI as `haxcms-mcp`.** It is not there yet (the name was free on
   2026-11-14). `uv build && uv publish`, ideally from a release workflow with PyPI trusted
   publishing so no token is stored. The published README must contain the `mcp-name` line.
2. **Set the version** in `server.json` (both places) to the version just published.
3. **Publish the entry** with the registry's CLI:

   ```bash
   mcp-publisher login github      # the io.github.haxtheweb/ namespace needs a member of the org
   mcp-publisher publish
   ```

   In GitHub Actions, `mcp-publisher login github-oidc` does the same with no secret, from a job
   with `id-token: write`.

Until step 1 is done the install commands in the README (from git) are the way in.

## Other directories

Most other directories either read the official registry or take a link to the repository.
Submit the repository URL and reuse the description from `server.json`. Check each one's terms
before submitting; none has been submitted to yet.

## When the HTTP transport is hosted

`server.json` lists the stdio package only. If a public haxcms-mcp endpoint is ever hosted, add a
`remotes` entry (`streamable-http` and its URL) next to `packages`.
