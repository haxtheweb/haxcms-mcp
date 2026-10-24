"""Unit tests for the T9.4 hardening items that need no live instance.

Covers: the `--version` CLI flag, graceful shutdown (the server lifespan closes the
httpx client), the client timeout wiring, and log redaction (no password, JWT or access
token ever reaches a log record, while the DEBUG request line is present).

The remaining T9.4 items live elsewhere: whoami budget stats (functional Phase 1 test),
the read-only matrix and the HTTP transport (integration Phase 9 tests), the coverage
gate (CI workflow).
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx
from fastmcp import Client

import haxcms_mcp.server as server_module
from haxcms_mcp import __version__
from haxcms_mcp.__main__ import main
from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
PASSWORD = "sup3r-secret-PASSWORD"
JWT = "jwt-SUPERSECRET-value"
ACCESS_TOKEN = "tok-SUPERSECRET-value"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
ECHO_URL = f"{BASE}/system/api/v1/echo"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"' + ACCESS_TOKEN + '","siteToken":"site-tok",'
    '"userToken":"user-tok","siteApiBasePath":"/_sites/demo/x/api"};\n'
)


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password=PASSWORD, **kwargs)  # type: ignore[arg-type]


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert f"haxcms-mcp {__version__}" in capsys.readouterr().out


async def test_lifespan_closes_the_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[HaxcmsClient] = []
    real = HaxcmsClient

    def factory(settings: Settings, **kwargs: object) -> HaxcmsClient:
        instance = real(settings, **kwargs)  # type: ignore[arg-type]
        created.append(instance)
        return instance

    monkeypatch.setattr(server_module, "HaxcmsClient", factory)
    server = build_server(make_settings())
    assert len(created) == 1
    owned = created[0]
    assert not owned.http.is_closed

    async with Client(server) as client:
        assert await client.list_prompts()  # connected: the client must stay open
        assert not owned.http.is_closed

    assert owned.http.is_closed  # disconnect ran the lifespan shutdown


def test_client_timeout_wiring() -> None:
    settings = make_settings(timeout_s=12.5, export_timeout_s=99.0)
    client = HaxcmsClient(settings)
    # every request carries the client-level timeout unless a call overrides it
    assert client.http.timeout == httpx.Timeout(12.5)
    assert settings.export_timeout_s == 99.0


@respx.mock
async def test_timeout_none_does_not_disable_the_client_timeout() -> None:
    # request(timeout=None) must fall back to the client-level timeout, never httpx's
    # "no timeout" (the kwargs guard in HaxcmsClient.request)
    route = respx.get(ECHO_URL).mock(return_value=httpx.Response(200, json={"status": 200}))
    async with HaxcmsClient(make_settings(timeout_s=12.5)) as client:
        await client.request("GET", "/system/api/v1/echo", auth="none", timeout=None)
        await client.request("GET", "/system/api/v1/echo", auth="none", timeout=3.0)
    first, second = (call.request.extensions["timeout"] for call in route.calls)
    assert first["connect"] == 12.5 and first["read"] == 12.5
    assert second["connect"] == 3.0 and second["read"] == 3.0


@respx.mock
async def test_logs_never_leak_credentials(caplog: pytest.LogCaptureFixture) -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"status": 200, "jwt": JWT},
            headers={"set-cookie": "haxcms_refresh_token=refresh-SUPERSECRET; Path=/; HttpOnly"},
        )
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))
    respx.get(ECHO_URL).mock(return_value=httpx.Response(200, json={"status": 200}))
    respx.post(f"{BASE}/system/api/v1/session/logout").mock(
        return_value=httpx.Response(200, json={"status": 200})
    )

    caplog.set_level(logging.DEBUG, logger="haxcms_mcp")
    async with HaxcmsClient(make_settings()) as client:
        await client.auth.ensure_access()
        await client.get_json("/system/api/v1/echo")
        await client.auth.logout()

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert logged, "expected log records from the auth + request cycle"
    for secret in (PASSWORD, JWT, ACCESS_TOKEN, "refresh-SUPERSECRET"):
        assert secret not in logged
    # the PLAN §5 DEBUG line is present: METHOD path status ms (no headers, no bodies)
    assert any(
        record.getMessage().startswith("GET /system/api/v1/echo 200 ")
        and record.getMessage().endswith("ms")
        for record in caplog.records
    )
    # the login is logged by username only
    assert "logged in as envuser" in logged
