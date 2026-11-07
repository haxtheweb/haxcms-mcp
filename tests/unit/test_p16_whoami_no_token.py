"""`whoami` never returns the access token (security follow-up).

HAXcms's `GET /system/api/v1/session` echoes the bearer token back as `jwt`. The tool used to
forward that body verbatim under `session`, putting a live credential into the model context.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server
from haxcms_mcp.tools.auth import _session_summary

pytestmark = pytest.mark.unit

BASE = "http://haxcms.invalid"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.secret-access-token"


def _walk(value: Any) -> list[tuple[str, Any]]:
    """Every (key, value) pair anywhere in a nested JSON structure."""
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            out.append((key, nested))
            out.extend(_walk(nested))
    elif isinstance(value, list):
        for nested in value:
            out.extend(_walk(nested))
    return out


async def test_whoami_result_contains_no_jwt_anywhere() -> None:
    settings = Settings(base_url=BASE, username="admin", password="pw")
    mcp = build_server(settings)
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.get("/system/api/v1").mock(
            return_value=httpx.Response(200, json={"status": 200, "data": {}})
        )
        router.post("/system/api/v1/session/login").mock(
            return_value=httpx.Response(
                200,
                json={"status": 200, "jwt": TOKEN},
                headers={"set-cookie": "haxcms_refresh_token=r1; Path=/; HttpOnly"},
            )
        )
        # what haxcms-nodejs session.js really answers: the token comes straight back
        router.get("/system/api/v1/session").mock(
            return_value=httpx.Response(
                200,
                json={"status": 200, "authenticated": True, "jwt": TOKEN, "user": "admin"},
            )
        )
        async with Client(mcp) as client:
            result = await client.call_tool("whoami", {})

    data = result.data
    assert data["authenticated"] is True
    assert data["user"] == "admin"
    assert data["session"] == {"authenticated": True, "user": "admin"}

    keys = {key for key, _ in _walk(data)}
    assert "jwt" not in keys
    assert "status" not in data["session"]
    # belt and braces: the token string appears nowhere in the serialised result
    serialised = json.dumps(data) + "".join(getattr(c, "text", "") for c in result.content)
    assert TOKEN not in serialised


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            {"status": 200, "authenticated": True, "jwt": "x", "user": "admin"},
            {"authenticated": True, "user": "admin"},
        ),
        ({"authenticated": False, "reason": "missing_jwt"}, {"authenticated": False, "user": None}),
        ("not a dict", {"authenticated": None, "user": None}),
        (None, {"authenticated": None, "user": None}),
    ],
)
def test_session_summary_keeps_only_descriptive_fields(body: Any, expected: dict[str, Any]) -> None:
    summary = _session_summary(body)
    assert summary == expected
    assert "jwt" not in summary
