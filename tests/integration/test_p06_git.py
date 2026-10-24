"""Phase 6 integration probes: the git publishing settings are NOT writable (PLAN T6.3).

PLAN asked to "first verify on the live instance whether any v1 route persists
`metadata.site.git` (try PATCH site with a `manifest-metadata-site-git-*` key, then inspect
site.json)". Outcome recorded here and in PROGRESS.md: NO route persists them.

* A body carrying ONLY git dash keys is not a scoped-details payload (detection looks for
  manifest-title / homePageId / sw / forceUpgrade), so it falls through to the full form
  path, whose `validateRequestToken` needs a `haxcms_form_token` no reachable route mints
  (it passes only under `haxcms_middleware=node-cli`) -> 403 'Authentication required'.
* Smuggling git keys ALONGSIDE a real scoped key takes the scoped path, which writes only
  its four known fields and silently IGNORES the git keys.

Therefore `configure_site_git` raises UNSUPPORTED (hint: edit site.json on the server) and
`get_site_settings` still reports the git block read-only.
"""

from __future__ import annotations

import pytest

from haxcms_mcp.client import HaxcmsClient
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration


async def test_git_only_body_hits_the_form_token_wall(
    client: HaxcmsClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    """Probe 1: git dash keys alone are not 'details' -> form path -> 403."""
    before = haxcms.read_site_json(site)
    response = await client.request(
        "PATCH",
        client.site_path(site, "site"),
        json={
            "site": {"name": site},
            "manifest": {"site": {"manifest-metadata-site-git-branch": "probe-branch"}},
        },
        auth="bearer+site",
        site=site,
    )
    assert response.status_code == 403
    body = response.json()
    assert body["data"]["message"] == "Authentication required"
    # nothing was written — the git block (and the whole manifest) is unchanged
    assert haxcms.read_site_json(site) == before


async def test_git_keys_smuggled_on_scoped_path_are_ignored(
    client: HaxcmsClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    """Probe 2: a valid scoped key carries the body, but only the four fields persist."""
    before_git = haxcms.read_site_json(site)["metadata"]["site"].get("git")
    response = await client.request(
        "PATCH",
        client.site_path(site, "site"),
        json={
            "site": {"name": site},
            "manifest": {
                "site": {
                    "manifest-title": "Scoped Title Probe",
                    "manifest-metadata-site-git-branch": "probe-branch",
                }
            },
        },
        auth="bearer+site",
        site=site,
    )
    assert response.status_code == 200
    after = haxcms.read_site_json(site)
    assert after["title"] == "Scoped Title Probe"  # the scoped key DID write
    assert after["metadata"]["site"].get("git") == before_git  # the git key did NOT


async def test_configure_site_git_tool_unsupported(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    """The tool fails UNSUPPORTED without touching the site; the git view stays readable."""
    before = haxcms.read_site_json(site)
    err = await mcp.call_error(
        "configure_site_git",
        branch="main",
        auto_push=True,
        remote_url="git@example.invalid:org/repo.git",
        vendor="github",
        site=site,
    )
    assert "UNSUPPORTED" in err
    assert "git publishing settings" in err
    assert "metadata.site.git" in err
    assert haxcms.read_site_json(site) == before

    # get_site_settings still reports the git block when the manifest carries one
    view = await mcp.call("get_site_settings", site=site)
    git = before["metadata"]["site"].get("git")
    if isinstance(git, dict) and git:
        assert view["git"]["branch"] == git.get("branch")
        assert view["git"]["vendor"] == git.get("vendor")
