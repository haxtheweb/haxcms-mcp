## Related Issue

<!-- Link the issue in the unified queue this PR addresses -->

Closes https://github.com/haxtheweb/issues/issues/XXXX

## Description of Changes

### What changed:

-
-

### Why this change was needed:

<!-- Explain the problem this solves or the feature this adds -->

## Type of Change

- [ ] 🐛 Bug fix (non-breaking change which fixes an issue)
- [ ] ✨ New feature or tool (non-breaking change which adds functionality)
- [ ] 💥 Breaking change (a tool, resource, prompt or setting changes in a way that breaks existing clients)
- [ ] 📚 Documentation update
- [ ] ♻️ Code refactoring
- [ ] 🔧 Configuration or CI changes

## Checks Run

<!-- Say which you ran; CI runs the same set (.github/workflows/ci.yml) -->

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
- [ ] `uv run python scripts/gen_tools.py --check`, `gen_routes.py --check`, `gen_tool_docs.py --check`
- [ ] `uv run pytest -m unit`
- [ ] `uv run pytest -m "integration or functional"` against haxcms-nodejs `main`
- [ ] Tested against haxcms-php `master` (if the change touches the HAXcms API)
- [ ] Added or updated tests for the behavior I changed
- [ ] Added a line under `## [Unreleased]` in `CHANGELOG.md` (user-visible changes)

## HAXcms Backend Impact

- [ ] No HAXcms backend change needed
- [ ] Needs a backend change, mirrored in **both** haxcms-nodejs and haxcms-php (link both PRs):

## HAX Pillar Checks

<!-- For non-trivial changes. A "no" is fine: name it below, say why, and link a follow-up issue in https://github.com/haxtheweb/issues. Full questions: https://github.com/haxtheweb/praw/blob/main/WORLDVIEW.md#pillar-checks -->

- [ ] **Accessible**: content the agent authors meets WCAG 2.0 AA without extra effort from authors
- [ ] **Efficient**: no new heavy dependency without reason; a newcomer gets it in about three seconds
- [ ] **Extensible**: built on web standards and MCP; plugs into existing and future systems
- [ ] **Free and open**: no paywall, lock-in or required proprietary service
- [ ] **Platform agnostic**: works the same against the haxcms-nodejs and haxcms-php backends
- [ ] **Remixable**: content stays portable (HTML, JSON Outline Schema); import and export still work
- [ ] **Sustainable**: someone other than the author could maintain it; sites made before this change still work
- [ ] **Human creativity first**: people keep the creative decisions and the output doesn't depend on one AI service

Any "no", and why:

## Ways to Test This Change

1.
2.
3.

## Additional Notes

<!-- Any additional context, decisions, or follow-up work -->

- [ ] I have read the [contributing guidelines](https://github.com/haxtheweb/haxcms-mcp/blob/main/CONTRIBUTING.md)
