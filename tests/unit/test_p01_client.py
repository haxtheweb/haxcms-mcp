"""Unit tests for the HaxcmsClient request pipeline (PLAN Phase 1 T1.5)."""

from __future__ import annotations

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.client.budget import OutboundBudget
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ECHO_URL = f"{BASE}/system/api/v1/echo"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


class CountingBudget(OutboundBudget):
    def __init__(self) -> None:
        super().__init__(rate=1000.0, capacity=1000, max_wait=1.0)
        self.acquired = 0

    async def acquire(self) -> None:
        self.acquired += 1
        await super().acquire()


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"status": 200, "jwt": "jwt-1"},
            headers={"set-cookie": "haxcms_refresh_token=r1; Path=/; HttpOnly"},
        )
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def test_path_helpers() -> None:
    client = HaxcmsClient(make_settings())
    assert client.sys("session/login") == "/system/api/v1/session/login"
    assert client.sys("/status") == "/system/api/v1/status"
    assert client.sys() == "/system/api/v1"
    assert client.site_path("demo", "items") == "/_sites/demo/x/api/v1/items"
    assert client.site_path("demo", "/items/123") == "/_sites/demo/x/api/v1/items/123"
    assert client.site_path("demo") == "/_sites/demo/x/api/v1"


@respx.mock
async def test_header_matrix_none() -> None:
    route = respx.get(ECHO_URL).mock(return_value=httpx.Response(200, json={"status": 200}))
    async with HaxcmsClient(make_settings()) as client:
        await client.request("GET", "/system/api/v1/echo", auth="none")
    headers = route.calls.last.request.headers
    assert "authorization" not in headers
    assert "x-haxcms-user-token" not in headers
    assert "x-haxcms-site-token" not in headers


@respx.mock
async def test_header_matrix_bearer() -> None:
    mock_auth()
    route = respx.get(ECHO_URL).mock(return_value=httpx.Response(200, json={"status": 200}))
    async with HaxcmsClient(make_settings()) as client:
        await client.request("GET", "/system/api/v1/echo", auth="bearer")
    headers = route.calls.last.request.headers
    assert headers["authorization"] == "Bearer jwt-1"
    assert "x-haxcms-user-token" not in headers
    assert "x-haxcms-site-token" not in headers


@respx.mock
async def test_header_matrix_bearer_plus_user() -> None:
    mock_auth()
    route = respx.get(ECHO_URL).mock(return_value=httpx.Response(200, json={"status": 200}))
    async with HaxcmsClient(make_settings()) as client:
        await client.request("GET", "/system/api/v1/echo", auth="bearer+user")
    headers = route.calls.last.request.headers
    assert headers["authorization"] == "Bearer jwt-1"
    assert headers["x-haxcms-user-token"] == "user-tok"
    assert "x-haxcms-site-token" not in headers


@respx.mock
async def test_header_matrix_bearer_plus_site() -> None:
    mock_auth()
    route = respx.get(ECHO_URL).mock(return_value=httpx.Response(200, json={"status": 200}))
    async with HaxcmsClient(make_settings()) as client:
        await client.request("GET", "/system/api/v1/echo", auth="bearer+site", site="demo")
    headers = route.calls.last.request.headers
    assert headers["authorization"] == "Bearer jwt-1"
    assert headers["x-haxcms-site-token"] == "site-tok"
    assert "x-haxcms-user-token" not in headers


@respx.mock
async def test_bearer_plus_site_requires_site() -> None:
    mock_auth()
    respx.get(ECHO_URL).mock(return_value=httpx.Response(200, json={"status": 200}))
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await client.request("GET", "/system/api/v1/echo", auth="bearer+site")
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


@respx.mock
async def test_budget_consumed_per_request_including_auth_calls() -> None:
    mock_auth()
    respx.get(ECHO_URL).mock(return_value=httpx.Response(200, json={"status": 200}))
    budget = CountingBudget()
    async with HaxcmsClient(make_settings(), budget=budget) as client:
        await client.request("GET", "/system/api/v1/echo", auth="bearer")
        first = budget.acquired
        assert first >= 2  # login + echo at minimum
        await client.request("GET", "/system/api/v1/echo", auth="bearer")
        assert budget.acquired == first + 1  # token cached: just the echo


@respx.mock
async def test_cookie_jar_persists_across_requests() -> None:
    mock_auth()
    refresh_route = respx.get(f"{BASE}/system/api/v1/session/refresh").mock(
        return_value=httpx.Response(
            200,
            json={"status": 200, "jwt": "jwt-2"},
            headers={"set-cookie": "haxcms_refresh_token=r2; Path=/; HttpOnly"},
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        await client.auth.ensure_access()  # logs in, stores r1 cookie
        assert client.http.cookies.get("haxcms_refresh_token") == "r1"
        assert await client.auth.refresh() is True
        assert "haxcms_refresh_token=r1" in refresh_route.calls.last.request.headers["cookie"]
        assert client.http.cookies.get("haxcms_refresh_token") == "r2"


@respx.mock
async def test_get_json_unwraps_and_download_returns_bytes() -> None:
    mock_auth()
    respx.get(ECHO_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"hello": "world"}})
    )
    respx.get(f"{BASE}/_published/x.zip").mock(
        return_value=httpx.Response(200, content=b"PK\x03\x04zipdata")
    )
    async with HaxcmsClient(make_settings()) as client:
        data = await client.get_json("/system/api/v1/echo", auth="bearer")
        assert data == {"hello": "world"}
        raw = await client.download("/_published/x.zip", auth="none")
        assert raw == b"PK\x03\x04zipdata"


@respx.mock
async def test_error_response_raises_through_json_helpers() -> None:
    mock_auth()
    respx.get(ECHO_URL).mock(
        return_value=httpx.Response(
            404, json={"status": 404, "data": {"message": "Site not found"}}
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await client.get_json("/system/api/v1/echo", auth="bearer")
        assert excinfo.value.code is ErrorCode.NOT_FOUND
