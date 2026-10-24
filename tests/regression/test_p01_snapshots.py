"""Phase 1 regression goldens: the auth header matrix (PLAN §6.4).

Pins which headers HaxcmsClient sends for each auth mode, with fully deterministic mocked
credentials. Update deliberately with `pytest --snapshot-update`.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from tests.harness.snapshots import assert_or_update_snapshot

pytestmark = pytest.mark.regression

BASE = "http://golden.invalid"
TRACKED_HEADERS = ("authorization", "x-haxcms-user-token", "x-haxcms-site-token", "cookie")
APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"golden-token","siteToken":"golden-site",'
    '"userToken":"golden-user","siteApiBasePath":"/_sites/golden/x/api"};\n'
)


@respx.mock
async def test_auth_header_matrix(request: pytest.FixtureRequest) -> None:
    respx.post(f"{BASE}/system/api/v1/session/login").mock(
        return_value=httpx.Response(
            200,
            json={"status": 200, "jwt": "golden-jwt"},
            headers={"set-cookie": "haxcms_refresh_token=golden-refresh; Path=/"},
        )
    )
    respx.get(f"{BASE}/system/api/v1/session/connection-settings").mock(
        return_value=httpx.Response(200, text=APP_SETTINGS_JS)
    )
    echo = respx.get(f"{BASE}/system/api/v1/echo").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {}})
    )

    matrix: dict[str, dict[str, str | None]] = {}
    settings = Settings(base_url=BASE, username="golden-user", password="golden-pass")
    async with HaxcmsClient(settings) as client:
        calls: list[tuple[str, dict[str, object]]] = [
            ("none", {}),
            ("bearer", {}),
            ("bearer+user", {}),
            ("bearer+site", {"site": "golden"}),
        ]
        for mode, kwargs in calls:
            echo.reset()
            await client.request("GET", "/system/api/v1/echo", auth=mode, **kwargs)  # type: ignore[arg-type]
            sent = echo.calls.last.request.headers
            matrix[mode] = {name: sent.get(name) for name in TRACKED_HEADERS}

    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("auth_header_matrix", matrix, update=update)
