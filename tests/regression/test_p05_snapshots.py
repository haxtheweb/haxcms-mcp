"""Phase 5 regression snapshots (PLAN §6.4: multipart golden).

`multipart_upload` freezes the wire contract of `site_api.upload_file`: the multipart
field name (`file-upload`, per API-REF §6 — the server also accepts `upload`/`file` but
we send this one), the `filename` and part `Content-Type`, the raw payload bytes, the
optional `nodeId` data field, and the part order (data fields before the file part, as
httpx encodes them). The random multipart boundary is parsed away so the golden is
deterministic; auth headers are never snapshotted.

Update deliberately with `pytest --snapshot-update`.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient, site_api
from haxcms_mcp.config import Settings
from tests.harness.snapshots import assert_or_update_snapshot

pytestmark = pytest.mark.regression

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
FILES_URL = f"{BASE}/_sites/demo/x/api/v1/files"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

PAYLOAD = b"<svg>placeholder</svg>"


def make_settings() -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass")


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def parse_multipart(request: httpx.Request) -> dict[str, Any]:
    """Decode the request body into a deterministic structure (boundary removed)."""
    content_type = request.headers["content-type"]
    boundary = re.search(r"boundary=(\S+)", content_type).group(1).strip('"')
    parts: list[dict[str, Any]] = []
    for chunk in request.content.split(f"--{boundary}".encode()):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        raw_headers, _, body = chunk.partition(b"\r\n\r\n")
        headers = raw_headers.decode("utf-8")
        part: dict[str, Any] = {
            "name": re.search(r'name="([^"]+)"', headers).group(1),
        }
        filename = re.search(r'filename="([^"]+)"', headers)
        if filename:
            part["filename"] = filename.group(1)
        part_type = re.search(r"(?im)^content-type:\s*(.+)$", headers)
        if part_type:
            part["content_type"] = part_type.group(1).strip()
        part["body"] = body.decode("utf-8")
        parts.append(part)
    return {
        "method": request.method,
        "content_type": content_type.split(";")[0],
        "part_order": [part["name"] for part in parts],
        "parts": parts,
    }


@respx.mock
async def test_multipart_upload_golden(request: pytest.FixtureRequest) -> None:
    update = bool(request.config.getoption("--snapshot-update", default=False))
    mock_auth()
    with_node = respx.post(FILES_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"file": {}}})
    )
    async with HaxcmsClient(make_settings()) as client:
        await site_api.upload_file(
            client,
            "demo",
            filename="photo.png",
            content=PAYLOAD,
            mimetype="image/png",
            node_id="node-9",
        )
        await site_api.upload_file(
            client, "demo", filename="photo.png", content=PAYLOAD, mimetype="image/png"
        )
    golden = {
        "with_node_id": parse_multipart(with_node.calls[0].request),
        "without_node_id": parse_multipart(with_node.calls[1].request),
    }
    assert_or_update_snapshot("multipart_upload", golden, update=update)
