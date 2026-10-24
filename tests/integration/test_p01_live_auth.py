"""Live auth integration tests against the real HAXcms (PLAN Phase 1).

Covers: login -> whoami -> forced refresh -> logout -> AUTH_REQUIRED; wrong password ->
AUTH_FAILED; repeated wrong passwords -> RATE_LIMITED with Retry-After surfaced; per-site tokens
(verified fact: siteToken differs per site; a token for the wrong site is refused with 403).
Sites are created with raw client calls per API-REF §3.3 (Phase 2 tools do not exist yet).
"""

from __future__ import annotations

import secrets

import pytest

from haxcms_mcp.client import HaxcmsClient, system_api
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration


async def create_site(client: HaxcmsClient, name: str) -> None:
    """Raw create-site call per API-REF §3.3 (blank site, one inline home item)."""
    payload = {
        "site": {
            "name": name,
            "description": "",
            "theme": "clean-one",
            "license": "by-sa",
            "domain": None,
        },
        "build": {
            "type": "skeleton",
            "structure": "from-skeleton",
            "items": [
                {
                    "id": f"item-home-{secrets.token_hex(8)}",
                    "title": "Home",
                    "slug": "home",
                    "order": 0,
                    "parent": None,
                    "indent": 0,
                    "content": "<p>Edit this page to get started on your HAX site!</p>",
                    "metadata": {"published": True, "hideInMenu": False, "tags": []},
                }
            ],
        },
    }
    response = await client.request("POST", client.sys("sites"), json=payload, auth="bearer+user")
    assert response.status_code == 200, response.text


async def archive_site(client: HaxcmsClient, name: str) -> None:
    response = await client.request(
        "POST",
        client.sys(f"sites/{name}/archive"),
        json={"site": {"name": name}},
        auth="bearer+user",
    )
    assert response.status_code == 200, response.text


async def test_live_auth_lifecycle(client: HaxcmsClient) -> None:
    # the fixture logged in with the env credentials
    assert client.auth.access_token is not None
    await system_api.session(client)  # bearer session check succeeds

    # forced proactive refresh: backdate the token past the 12-minute threshold
    assert client.auth.access_issued_at is not None
    client.auth.access_issued_at -= 13 * 60
    token = await client.auth.ensure_access()
    assert token is not None
    await system_api.session(client)  # still a valid session after the refresh

    # logout kills the session; auto-login is suppressed even with env credentials
    await client.auth.logout()
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await client.auth.ensure_access()
    assert excinfo.value.code is ErrorCode.AUTH_REQUIRED


async def test_live_session_and_status_endpoints(client: HaxcmsClient) -> None:
    profile = await system_api.session_user(client)
    assert profile is not None
    diagnostics = await system_api.status(client)
    assert isinstance(diagnostics, dict)
    version_data = await system_api.version(client)
    assert version_data is not None
    sites = await system_api.list_sites(client)
    assert isinstance(sites.items, list)


async def test_whoami_tool_over_live_session(mcp: McpTestClient, haxcms: HaxcmsRuntime) -> None:
    me = await mcp.call("whoami")
    assert me["authenticated"] is True
    assert me["user"] == haxcms.username
    assert me["read_only"] is False
    assert isinstance(me["budget"], dict)


async def test_get_server_info_reports_live_version(mcp: McpTestClient) -> None:
    info = await mcp.call("get_server_info")
    assert info["name"] == "haxcms-mcp"
    haxcms_info = info["haxcms"]
    assert "version_error" not in haxcms_info, haxcms_info
    assert "status_error" not in haxcms_info, haxcms_info
    assert haxcms_info["version"] is not None


async def test_wrong_password_is_auth_failed(mcp: McpTestClient, haxcms: HaxcmsRuntime) -> None:
    error = await mcp.call_error("login", username=haxcms.username, password="definitely-wrong")
    assert error.startswith("[AUTH_FAILED]"), error
    assert "Invalid username or password" in error


async def test_repeated_wrong_passwords_are_rate_limited(mcp: McpTestClient) -> None:
    # Use a throwaway username: the limiter is per IP+user and must not lock out the test user.
    fake_user = f"probe-{secrets.token_hex(4)}"
    last_error = ""
    for _ in range(7):
        last_error = await mcp.call_error("login", username=fake_user, password="wrong")
        if last_error.startswith("[RATE_LIMITED]"):
            break
    assert last_error.startswith("[RATE_LIMITED]"), last_error
    assert "retry after" in last_error


async def test_site_tokens_are_per_site_and_enforced(client: HaxcmsClient) -> None:
    suffix = secrets.token_hex(4)
    site_a, site_b = f"mcp-a-{suffix}", f"mcp-b-{suffix}"
    try:
        await create_site(client, site_a)
        await create_site(client, site_b)

        token_a = await client.auth.site_token(site_a)
        token_b = await client.auth.site_token(site_b)
        assert token_a and token_b
        assert token_a != token_b, "verified fact: siteToken must differ per site"

        # a harmless write (create a page) with the right token succeeds
        node_payload = {
            "site": {"name": site_a},
            "node": {
                "id": None,
                "title": "probe",
                "location": None,
                "duplicate": None,
                "contents": "<p></p>",
            },
            "parent": None,
            "order": None,
            "indent": None,
            "description": "",
            "metadata": None,
        }
        response = await client.request(
            "POST",
            client.site_path(site_a, "items"),
            json=node_payload,
            auth="bearer+site",
            site=site_a,
        )
        assert response.status_code == 200, response.text

        # the same write against site B with site A's token is refused
        wrong_payload = {**node_payload, "site": {"name": site_b}}
        response = await client.request(
            "POST",
            client.site_path(site_b, "items"),
            json=wrong_payload,
            auth="none",
            headers={
                "Authorization": f"Bearer {client.auth.access_token}",
                "X-HAXCMS-Site-Token": str(token_a),
            },
        )
        assert response.status_code == 403, response.text
    finally:
        await archive_site(client, site_a)
        await archive_site(client, site_b)
