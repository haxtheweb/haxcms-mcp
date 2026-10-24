"""Prove the test harness: boot HAXcms, raw-httpx login, list sites, disk layout, teardown.

PLAN.md Phase 0 T0.7; login per API-REF §2.1; instance recipe per API-REF §11.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from tests.harness.haxcms_runtime import HaxcmsRuntime

pytestmark = pytest.mark.integration


def fetch_app_settings(client: httpx.Client, referer: str | None = None) -> dict[str, Any]:
    """GET connection-settings and parse the window.appSettings object (API-REF §2.5)."""
    headers = {"Accept": "application/javascript"}
    if referer is not None:
        headers["Referer"] = referer
    response = client.get("/system/api/v1/session/connection-settings", headers=headers)
    assert response.status_code == 200, response.text
    text = response.text
    marker = text.index("window.appSettings")
    start = text.index("{", marker)
    settings, _ = json.JSONDecoder().raw_decode(text[start:])
    assert isinstance(settings, dict)
    return settings


async def test_boot_and_disk_layout(haxcms: HaxcmsRuntime) -> None:
    root = haxcms.runtime_root
    assert root is not None and root.is_dir()
    # §11 steps 1-2 layout
    assert (root / "_sites").is_dir()
    config = root / "_config"
    assert (config / ".isHAXcmsConfig").is_file()
    assert (config / "config.json").is_file()
    assert (config / "userData.json").is_file()
    assert (config / "my-custom-elements.js").is_file()
    for sub in ("tmp", "cache", "user/files", "user/skeletons", "skeletons", "settings"):
        assert (config / sub).is_dir(), f"_config/{sub} missing"
    # §11 step 3: login user file (plaintext accepted, upgraded on first login)
    user = json.loads((config / ".user").read_text(encoding="utf-8"))
    assert user["name"] == haxcms.username
    assert user["name"] != "admin"


async def test_status_answers(haxcms: HaxcmsRuntime) -> None:
    response = httpx.get(f"{haxcms.base_url}/system/api/v1/status", timeout=15)
    assert response.status_code < 500


async def test_login_and_list_sites(haxcms: HaxcmsRuntime) -> None:
    with httpx.Client(base_url=haxcms.base_url, timeout=30) as client:
        # §2.1 login
        response = client.post(
            "/system/api/v1/session/login",
            json={"username": haxcms.username, "password": haxcms.password},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == 200
        jwt = body["jwt"]
        assert isinstance(jwt, str) and jwt.count(".") == 2
        # refresh cookie set by the server
        assert "haxcms_refresh_token" in client.cookies

        # §2.5 connection-settings: userToken works on a fresh instance with no Referer
        app_settings = fetch_app_settings(client)
        user_token = app_settings["userToken"]
        assert isinstance(user_token, str) and user_token

        auth = {"Authorization": f"Bearer {jwt}"}
        # Verified fact: GET /system/api/v1/sites requires bearer + X-HAXCMS-User-Token
        # (spec security bearerAuth+userTokenHeader; API-REF §2.6 matrix is outdated here).
        response = client.get("/system/api/v1/sites", headers=auth)
        assert response.status_code == 403, response.text
        assert "X-HAXCMS-User-Token" in response.text

        # §3.1 list sites (bearer + user token) - fresh instance has none
        response = client.get(
            "/system/api/v1/sites", headers={**auth, "X-HAXCMS-User-Token": user_token}
        )
        assert response.status_code == 200, response.text
        envelope = response.json()
        assert envelope["status"] == 200
        assert envelope["data"]["items"] == []

        # wrong password is refused
        response = client.post(
            "/system/api/v1/session/login",
            json={"username": haxcms.username, "password": "wrong-password"},
        )
        assert response.status_code == 401


async def test_teardown_removes_runtime_dir() -> None:
    runtime = HaxcmsRuntime()
    async with runtime:
        root = runtime.runtime_root
        assert root is not None and root.is_dir()
    assert root is not None
    assert not root.exists(), f"runtime dir {root} survived teardown"
