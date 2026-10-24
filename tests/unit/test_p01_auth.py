"""Unit tests for AuthManager with respx (PLAN Phase 1 T1.4).

The connection-settings parsing test uses a response captured from a real HAXcms 26.8.1 instance
(tests/fixtures/connection_settings.js).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.client.auth import parse_app_settings
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
REFRESH_URL = f"{BASE}/system/api/v1/session/refresh"
LOGOUT_URL = f"{BASE}/system/api/v1/session/logout"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "connection_settings.js"


class FakeClock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def make_client(settings: Settings, clock: FakeClock | None = None) -> HaxcmsClient:
    return HaxcmsClient(settings, clock=clock or FakeClock())


def login_response(jwt: str = "jwt-1", cookie: str = "refresh-1") -> httpx.Response:
    return httpx.Response(
        200,
        json={"status": 200, "jwt": jwt},
        headers={"set-cookie": f"haxcms_refresh_token={cookie}; Path=/; HttpOnly"},
    )


def refresh_response(jwt: str = "jwt-2", cookie: str = "refresh-2") -> httpx.Response:
    return httpx.Response(
        200,
        json={"status": 200, "jwt": jwt},
        headers={"set-cookie": f"haxcms_refresh_token={cookie}; Path=/; HttpOnly"},
    )


@respx.mock
async def test_login_success_stores_token_and_cookie() -> None:
    route = respx.post(LOGIN_URL).mock(return_value=login_response())
    async with make_client(make_settings()) as client:
        jwt = await client.auth.login("u", "p")
        assert jwt == "jwt-1"
        assert client.auth.access_token == "jwt-1"
        assert client.auth.access_issued_at is not None
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"username": "u", "password": "p"}


@respx.mock
async def test_login_failure_maps_to_auth_failed() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            401, json={"status": 401, "data": {"message": "Invalid username or password"}}
        )
    )
    async with make_client(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await client.auth.login("u", "wrong")
    assert excinfo.value.code is ErrorCode.AUTH_FAILED


@respx.mock
async def test_cookie_jar_holds_refresh_token_after_login() -> None:
    respx.post(LOGIN_URL).mock(return_value=login_response(cookie="rotating-1"))
    async with make_client(make_settings()) as client:
        await client.auth.login("u", "p")
        assert client.http.cookies.get("haxcms_refresh_token") == "rotating-1"
        assert client.auth.has_refresh_cookie


@respx.mock
async def test_proactive_refresh_at_12_minutes() -> None:
    clock = FakeClock()
    respx.post(LOGIN_URL).mock(return_value=login_response(jwt="jwt-1"))
    refresh_route = respx.get(REFRESH_URL).mock(return_value=refresh_response(jwt="jwt-2"))
    async with make_client(make_settings(), clock) as client:
        await client.auth.ensure_access()
        assert client.auth.access_token == "jwt-1"

        clock.advance(11 * 60)  # still fresh at 11 min
        assert await client.auth.ensure_access() == "jwt-1"
        assert not refresh_route.called

        clock.advance(2 * 60)  # 13 min total -> proactive refresh
        assert await client.auth.ensure_access() == "jwt-2"
        assert refresh_route.call_count == 1


@respx.mock
async def test_refresh_sends_cookie_and_rotates_it() -> None:
    respx.post(LOGIN_URL).mock(return_value=login_response(cookie="r1"))
    refresh_route = respx.get(REFRESH_URL).mock(return_value=refresh_response(cookie="r2"))
    async with make_client(make_settings()) as client:
        await client.auth.login("u", "p")
        assert await client.auth.refresh() is True
        request = refresh_route.calls.last.request
        assert "haxcms_refresh_token=r1" in request.headers.get("cookie", "")
        assert "origin" not in request.headers
        assert "referer" not in request.headers
        assert client.http.cookies.get("haxcms_refresh_token") == "r2"


@respx.mock
async def test_refresh_failure_falls_back_to_login() -> None:
    clock = FakeClock()
    login_route = respx.post(LOGIN_URL).mock(
        side_effect=[login_response(jwt="jwt-1"), login_response(jwt="jwt-3")]
    )
    respx.get(REFRESH_URL).mock(
        return_value=httpx.Response(401, json={"status": 401, "data": {"message": "expired"}})
    )
    async with make_client(make_settings(), clock) as client:
        await client.auth.ensure_access()
        clock.advance(13 * 60)  # stale -> refresh attempt -> 401 -> re-login
        assert await client.auth.ensure_access() == "jwt-3"
        assert login_route.call_count == 2


@respx.mock
async def test_reactive_refresh_on_403_invalid_bearer() -> None:
    session_url = f"{BASE}/system/api/v1/session"
    respx.post(LOGIN_URL).mock(return_value=login_response(jwt="jwt-1"))
    respx.get(REFRESH_URL).mock(return_value=refresh_response(jwt="jwt-2"))
    session_route = respx.get(session_url).mock(
        side_effect=[
            httpx.Response(403, json={"status": 403, "data": {"message": "Invalid bearer token"}}),
            httpx.Response(200, json={"status": 200, "data": {"user": "envuser"}}),
        ]
    )
    async with make_client(make_settings()) as client:
        response = await client.request("GET", client.sys("session"), auth="bearer")
        assert response.status_code == 200
        assert session_route.call_count == 2
        assert client.auth.access_token == "jwt-2"
        retry_auth = session_route.calls.last.request.headers["authorization"]
        assert retry_auth == "Bearer jwt-2"


@respx.mock
async def test_ensure_access_without_credentials_raises_auth_required() -> None:
    settings = Settings(base_url=BASE)
    async with make_client(settings) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await client.auth.ensure_access()
        assert excinfo.value.code is ErrorCode.AUTH_REQUIRED


@respx.mock
async def test_logout_clears_state_and_blocks_auto_login() -> None:
    respx.post(LOGIN_URL).mock(return_value=login_response())
    logout_route = respx.post(LOGOUT_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": "loggedout"})
    )
    async with make_client(make_settings()) as client:
        await client.auth.ensure_access()
        await client.auth.logout()
        assert logout_route.called
        assert client.auth.access_token is None
        assert not client.auth.has_refresh_cookie
        # env credentials exist, but the explicit logout suppresses auto-login
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await client.auth.ensure_access()
        assert excinfo.value.code is ErrorCode.AUTH_REQUIRED
        # an explicit login clears the logged-out flag
        assert await client.auth.login("u", "p") == "jwt-1"
        assert await client.auth.ensure_access() == "jwt-1"


@respx.mock
async def test_connection_settings_parsing_of_captured_response() -> None:
    captured = FIXTURE.read_text(encoding="utf-8")
    respx.get(CONN_URL).mock(
        return_value=httpx.Response(
            200, text=captured, headers={"content-type": "application/javascript"}
        )
    )
    start = captured.index("{", captured.index("window.appSettings"))
    expected, _ = json.JSONDecoder().raw_decode(captured[start:])
    parsed = parse_app_settings(captured)
    assert parsed == expected
    for key in ("token", "siteToken", "userToken", "siteApiBasePath"):
        assert key in parsed, f"captured fixture lacks {key}"
    assert parsed["userToken"]

    async with make_client(make_settings()) as client:
        assert await client.auth.user_token() == expected["userToken"]
        # second call is served from the cache (route called once)
        assert await client.auth.user_token() == expected["userToken"]


@respx.mock
async def test_site_tokens_cached_per_site_with_referer() -> None:
    captured = FIXTURE.read_text(encoding="utf-8")
    expected = parse_app_settings(captured)
    conn_route = respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=captured))
    async with make_client(make_settings()) as client:
        token_a = await client.auth.site_token("alpha")
        token_b = await client.auth.site_token("beta")
        token_a2 = await client.auth.site_token("alpha")
    assert token_a == expected["siteToken"] == token_a2
    assert token_b == expected["siteToken"]  # fixture is single-site; cache key still per site
    assert conn_route.call_count == 2  # one fetch per distinct site
    referers = [call.request.headers.get("referer") for call in conn_route.calls]
    assert referers == [f"{BASE}/_sites/alpha/", f"{BASE}/_sites/beta/"]


def test_parse_app_settings_rejects_garbage() -> None:
    with pytest.raises(HaxcmsMcpError):
        parse_app_settings("<html>no script here</html>")
    with pytest.raises(HaxcmsMcpError):
        parse_app_settings("window.appSettings = not-json")


@respx.mock
async def test_no_auth_mode_sends_no_headers() -> None:
    settings = make_settings(no_auth=True)
    route = respx.get(f"{BASE}/system/api/v1/session").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {}})
    )
    async with make_client(settings) as client:
        assert await client.auth.ensure_access() is None
        response = await client.request("GET", client.sys("session"), auth="bearer")
        assert response.status_code == 200
        headers = route.calls.last.request.headers
        assert "authorization" not in headers
        assert "x-haxcms-user-token" not in headers
        assert "x-haxcms-site-token" not in headers
        assert await client.auth.user_token() is None
        assert await client.auth.site_token("whatever") is None
