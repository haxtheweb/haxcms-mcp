# Contributing

> **New to the HAX ecosystem?** Start with the [ecosystem-wide developer onboarding](https://github.com/haxtheweb/issues/blob/master/CONTRIBUTING.md). It covers prerequisites, cloning the core repos, and getting HAXcms running locally. This guide is specific to haxcms-mcp.

- [Communication](#communication)
- [Finding something to work on](#finding-something-to-work-on)
- [Development setup](#development-setup)
- [Checks to run before a pull request](#checks-to-run-before-a-pull-request)
- [Opening a pull request](#opening-a-pull-request)
- [Code review](#code-review)
- [Security](#security)

HAX is open source, but many of the people working on it do so as their day job. To avoid forcing anyone to be "at work" 24/7, we keep a few semi-formal protocols around development.

As a contributor, your changes and ideas are welcome at any hour of the day or night, weekdays, weekends, and holidays. Please never hesitate to ask a question or send a pull request.

## Communication

- **Issues:** every bug, feature request and question goes to the [unified issue queue](https://github.com/haxtheweb/issues/issues), even when it only concerns this repo. Pick **haxcms-mcp** in the Project dropdown. Inside any HAX space you can also open Merlin and type "Issue" to start a report.
- **Chat:** join the [HAXTheWeb Discord](https://discord.gg/aCGxmRHEJP) to ask questions, find reviewers, or introduce yourself.
- **Updates:** [YouTube](https://www.youtube.com/@haxtheweb), [LinkedIn](http://linkedin.com/company/haxtheweb) and [X](https://x.com/haxtheweb).

## Finding something to work on

1. Browse the [unified issue queue](https://github.com/haxtheweb/issues/issues) for haxcms-mcp work. Issues labeled `Plan Created` already have an implementation plan on them.
2. Comment on the issue to say you are picking it up.
3. Read [`CONTEXT.md`](CONTEXT.md) for the domain model and the [ADRs](docs/adr/) for the decisions the server is built on.

## Development setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node + npm for the live test suites.

```bash
git clone https://github.com/haxtheweb/haxcms-mcp && cd haxcms-mcp
uv sync
```

The live suites boot a real HAXcms and target current [haxcms-nodejs](https://github.com/haxtheweb/haxcms-nodejs) `main`, not the npm release. See [Which HAXcms the tests run against](README.md#which-haxcms-the-tests-run-against).

## Checks to run before a pull request

These are the same checks CI runs (`.github/workflows/ci.yml`):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run python scripts/gen_tools.py --check         # converter drift (ADR-0002)
uv run python scripts/gen_routes.py --check        # client route drift (ADR-0005)
uv run python scripts/gen_tool_docs.py --check     # docs/tools.md drift
uv run pytest -m unit
uv run pytest -m "integration or functional"       # needs Node + npm
```

If a change needs a HAXcms backend change, it must land in both [haxcms-nodejs](https://github.com/haxtheweb/haxcms-nodejs) and [haxcms-php](https://github.com/haxtheweb/haxcms-php) with the same behavior, and both OpenAPI specs kept identical.

## Opening a pull request

We work with forks and pull requests. Fork this repo, create a branch, and open a pull request that points to the issue in the unified queue.

- Use [Conventional Commits](https://www.conventionalcommits.org/) and add a line under `## [Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) for user-visible changes.
- Put `Closes https://github.com/haxtheweb/issues/issues/<number>` in the PR body, not in commit messages.
- Fill in the pull request template, including which checks you ran.
- Break large changes into a series of smaller PRs that each make sense on their own.
- First-time contributors are asked to sign the [Contributor License Agreement](https://github.com/haxtheweb/cla/blob/main/CLA.md); the CLA Assistant bot will comment on your PR with instructions.

## Code review

Reviewers look at, in order: is the idea sound, is it architected correctly, is it polished ([The Gentle Art of Patch Review](http://sage.thesharps.us/2014/09/01/the-gentle-art-of-patch-review/)).

If your pull request isn't getting attention, ask in [Discord](https://discord.gg/aCGxmRHEJP) for help finding reviewers.

## Security

Do not open public issues for unpatched vulnerabilities. See [`SECURITY.md`](SECURITY.md) to report one privately.

All participation is covered by our [Code of Conduct](CODE_OF_CONDUCT.md).
