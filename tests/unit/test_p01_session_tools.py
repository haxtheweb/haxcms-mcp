"""Unit tests for the four session tools through the MCP interface (PLAN Phase 1 T1.7).

The AuthManager is covered in test_p01_auth.py; these tests pin what an Agent actually
sees from login/logout/whoami/get_server_info over an in-memory Client with respx: the
login wire body, AUTH_FAILED / RATE_LIMITED surfacing (without echoing the password and
without retrying a rate-limited login), logout suppressing env-credential auto-login,
the NO_AUTH whoami shape (no HTTP at all), the per-caller HTTP mode refusing
login/logout, and get_server_info degrading per probe instead of failing.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.middleware import ErrorTranslationMiddleware
from haxcms_mcp.server import build_server
from haxcms_mcp.tools.auth import register_auth_tools

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
LOGOUT_URL = f"{BASE}/system/api/v1/session/logout"
SESSION_URL = f"{BASE}/system/api/v1/session"
REFRESH_URL = f"{BASE}/system/api/v1/session/refresh"
VERSION_URL = f"{BASE}/system/api/v1/system/version"
STATUS_URL = f"{BASE}/system/api/v1/status"
DISCOVERY_URL = f"{BASE}/system/api/v1"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)


def secret() -> str:
    """A throwaway credential made at runtime (nothing credential-shaped is committed)."""
    return secrets.token_urlsafe(16)


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, **kwargs)  # type: ignore[arg-type]


def login_ok(jwt: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"status": 200, "jwt": jwt},
        headers={"set-cookie": "haxcms_refresh_token=r1; Path=/; HttpOnly"},
    )


def mock_session_probe() -> respx.Route:
    return respx.get(SESSION_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"user": "probe"}})
    )


async def call(server: FastMCP, tool: str, **arguments: Any) -> Any:
    async with Client(server) as client:
        return (await client.call_tool(tool, arguments)).data


async def call_error(server: FastMCP, tool: str, **arguments: Any) -> str:
    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(tool, arguments)
    return str(excinfo.value)


# --- login ------------------------------------------------------------------------------------


@respx.mock
async def test_login_posts_credentials_and_whoami_reports_the_user() -> None:
    password = secret()
    jwt = secret()
    login_route = respx.post(LOGIN_URL).mock(return_value=login_ok(jwt))
    session_route = mock_session_probe()
    server = build_server(make_settings(default_site="demo"))
    async with Client(server) as client:
        result = await client.call_tool("login", {"username": "author", "password": password})
        assert result.data == {"user": "author", "expires_in_s": 900}
        who = (await client.call_tool("whoami", {})).data

    assert json.loads(login_route.calls.last.request.content) == {
        "username": "author",
        "password": password,
    }
    # whoami reuses the login token: no second login
    assert login_route.call_count == 1
    assert session_route.calls.last.request.headers["Authorization"] == f"Bearer {jwt}"
    assert who["user"] == "author"
    assert who["authenticated"] is True
    assert who["default_site"] == "demo"
    assert who["read_only"] is False
    assert who["per_caller_auth"] is False
    assert isinstance(who["token_age_s"], float)
    assert set(who["budget"]) == {"tokens", "waits", "denials"}
    # the result never carries the token itself
    assert jwt not in json.dumps(who)


@respx.mock
async def test_login_with_bad_credentials_is_auth_failed_without_the_password() -> None:
    password = secret()
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            401, json={"status": 401, "data": {"message": "Invalid credentials"}}
        )
    )
    message = await call_error(
        build_server(make_settings()), "login", username="author", password=password
    )
    assert message.startswith("[AUTH_FAILED]")
    assert "call login with valid credentials" in message
    assert password not in message


@respx.mock
async def test_rate_limited_login_surfaces_retry_after_and_is_not_retried() -> None:
    route = respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            429,
            json={"status": 429, "data": {"message": "Too many login attempts"}},
            headers={"Retry-After": "600"},
        )
    )
    message = await call_error(
        build_server(make_settings()), "login", username="author", password=secret()
    )
    assert message.startswith("[RATE_LIMITED]")
    assert "retry after 600s" in message
    assert route.call_count == 1


# --- logout -------------------------------------------------------------------------------------


@respx.mock
async def test_logout_ends_the_session_and_blocks_env_auto_login() -> None:
    jwt = secret()
    login_route = respx.post(LOGIN_URL).mock(return_value=login_ok(jwt))
    logout_route = respx.post(LOGOUT_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": "loggedout"})
    )
    respx.get(REFRESH_URL).mock(
        return_value=httpx.Response(401, json={"status": 401, "data": {"message": "no"}})
    )
    mock_session_probe()
    server = build_server(make_settings(username="env-user", password=secret()))
    async with Client(server) as client:
        await client.call_tool("whoami", {})  # env credentials log in automatically
        assert login_route.call_count == 1
        result = await client.call_tool("logout", {})
        assert result.data == {"status": "loggedout"}
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("whoami", {})

    # the server-side session is ended with the bearer that names it
    assert logout_route.calls.last.request.headers["Authorization"] == f"Bearer {jwt}"
    assert str(excinfo.value).startswith("[AUTH_REQUIRED] session was logged out")
    # env credentials are NOT used again after an explicit logout
    assert login_route.call_count == 1


@respx.mock
async def test_whoami_without_credentials_is_auth_required() -> None:
    message = await call_error(build_server(make_settings()), "whoami")
    assert message.startswith("[AUTH_REQUIRED]")
    assert "HAXCMS_MCP_USERNAME" in message


@respx.mock
async def test_whoami_in_no_auth_mode_makes_no_requests() -> None:
    data = await call(
        build_server(make_settings(no_auth=True, username="anon", default_site="demo")),
        "whoami",
    )
    assert data["no_auth"] is True
    assert data["authenticated"] is None
    assert data["token_age_s"] is None
    assert data["user"] == "anon"
    assert not [call for call in respx.calls if "/session" in call.request.url.path]


# --- per-caller HTTP mode -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [("login", {"username": "author", "password": secret()}), ("logout", {})],
)
@respx.mock
async def test_per_caller_mode_refuses_login_and_logout(
    tool: str, arguments: dict[str, Any]
) -> None:
    # the connection's own token IS the session there; the tools must not swap it
    settings = make_settings(transport="http", http_auth="haxcms")
    server = FastMCP("session-tools")
    server.add_middleware(ErrorTranslationMiddleware())
    register_auth_tools(server, settings, HaxcmsClient(settings))
    message = await call_error(server, tool, **arguments)
    assert message.startswith(f"[UNSUPPORTED] {tool} is not available on this server")
    assert "connector authorization" in message
    assert not respx.calls


# --- get_server_info ------------------------------------------------------------------------


@respx.mock
async def test_server_info_reports_version_and_degrades_status_per_probe() -> None:
    respx.post(LOGIN_URL).mock(return_value=login_ok(secret()))
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))
    respx.get(VERSION_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"version": "26.9.0"}})
    )
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(500, json={"status": 500, "data": {"message": "boom"}})
    )
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(
            200, json={"status": 200, "data": {"mcp": {"enabled": True, "readOnly": False}}}
        )
    )
    data = await call(
        build_server(make_settings(username="env-user", password=secret())), "get_server_info"
    )
    assert data["base_url"] == BASE
    assert data["haxcms"]["version"] == {"version": "26.9.0"}
    assert "version_error" not in data["haxcms"]
    assert data["haxcms"]["status_error"].startswith("[")
    assert "status" not in data["haxcms"]
    assert data["instance_mcp_policy"]["enabled"] is True
    assert data["instance_mcp_policy"]["read_only"] is False
    # no spec served by the fake: the compatibility probe degrades instead of failing
    assert data["spec_compatibility"]["status"] == "unavailable"
