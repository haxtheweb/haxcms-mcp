"""Unit tests for the files service with respx (PLAN Phase 5 T5.4 test list).

Covers the multipart upload shape (field `file-upload`, filename override, the `nodeId`
data field resolved from `page`), the query keys list_files emits, the PATCH operation
payloads (rename / scale with size / compress with level / duplicate), the bodyless
DELETE, argument validation, the upload-response `type` MIME key, and the file-ops
limiter 429 -> RATE_LIMITED mapping with its Retry-After.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.files import service

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
FILES_URL = f"{BASE}/_sites/demo/x/api/v1/files"
FILE_URL = f"{FILES_URL}/abc-123"
ITEM_URL = f"{BASE}/_sites/demo/x/api/v1/items/home"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")
DATA_URL = f"data:image/png;base64,{PNG_B64}"

FILE_RECORD = {
    "path": "sites/demo/files/upload.png",
    "fullUrl": "http://hax.invalid/_sites/demo/files/upload.png",
    "url": "files/upload.png",
    "mimetype": "image/png",
    "name": "upload.png",
    "uuid": "abc-123",
    "size": 24,
    "dateCreated": 1750000000,
    "width": 4,
    "height": 3,
}


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


# --- list_files --------------------------------------------------------------------------------


@respx.mock
async def test_list_files_emits_filter_and_page_params() -> None:
    mock_auth()
    route = respx.get(FILES_URL).mock(
        return_value=envelope(
            {"count": 1, "total": 1, "page": {"limit": 10}, "files": [FILE_RECORD], "orphans": []}
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        collection = await service.list_files(
            client,
            "demo",
            type="image",
            extension=".PNG",
            name_contains="song",
            limit=10,
            offset=5,
        )
    params = route.calls.last.request.url.params
    assert params["filter.type"] == "image"
    assert params["filter.extension"] == "png"  # dot stripped, lowercased
    assert params["filter.nameContains"] == "song"
    assert params["page.limit"] == "10"
    assert params["page.offset"] == "5"
    assert collection.count == 1 and collection.total == 1
    assert collection.files[0].uuid == "abc-123"
    assert collection.files[0].width == 4 and collection.files[0].height == 3


@respx.mock
async def test_list_files_defaults_to_page_only() -> None:
    mock_auth()
    route = respx.get(FILES_URL).mock(
        return_value=envelope({"count": 0, "total": 0, "page": {}, "files": [], "orphans": []})
    )
    async with HaxcmsClient(make_settings()) as client:
        await service.list_files(client, "demo")
    params = route.calls.last.request.url.params
    assert params["page.limit"] == "25"
    assert params["page.offset"] == "0"
    assert "filter.type" not in params
    assert "filter.extension" not in params
    assert "filter.nameContains" not in params


# --- upload_file --------------------------------------------------------------------------------


@respx.mock
async def test_upload_file_multipart_shape() -> None:
    mock_auth()
    route = respx.post(FILES_URL).mock(
        return_value=envelope(
            # the upload response names the MIME key `type`, not `mimetype`
            {"file": {**FILE_RECORD, "mimetype": None, "type": "image/png"}}
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        result = await service.upload_file(client, make_settings(), "demo", DATA_URL)
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="file-upload"' in body
    assert b'filename="upload.png"' in body
    assert b"image/png" in body
    assert PNG_BYTES in body
    assert b'name="nodeId"' not in body
    # UploadResult mapped the `type` key onto the record's mimetype
    assert result.file is not None
    assert result.file.mimetype == "image/png"
    assert result.file.uuid == "abc-123"
    assert result.file.url == "files/upload.png"


@respx.mock
async def test_upload_file_filename_override_and_page_node_id() -> None:
    mock_auth()
    item_route = respx.get(ITEM_URL).mock(
        return_value=envelope({"id": "node-9", "title": "Home", "slug": "home"})
    )
    upload_route = respx.post(FILES_URL).mock(return_value=envelope({"file": FILE_RECORD}))
    async with HaxcmsClient(make_settings()) as client:
        await service.upload_file(
            client, make_settings(), "demo", DATA_URL, filename="Songline_1.png", page="home"
        )
    assert item_route.call_count == 1
    body = upload_route.calls.last.request.content
    assert b'filename="Songline_1.png"' in body
    assert b'name="nodeId"' in body
    assert b"node-9" in body


@respx.mock
async def test_upload_file_rejects_path_like_filename_override() -> None:
    mock_auth()
    route = respx.post(FILES_URL).mock(return_value=envelope({"file": FILE_RECORD}))
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await service.upload_file(client, make_settings(), "demo", DATA_URL, filename="a/b.png")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert route.call_count == 0


# --- get / rename / transform / duplicate / delete ------------------------------------------------


@respx.mock
async def test_get_file_maps_record() -> None:
    mock_auth()
    respx.get(FILE_URL).mock(return_value=envelope(FILE_RECORD))
    async with HaxcmsClient(make_settings()) as client:
        record = await service.get_file(client, "demo", "abc-123")
    assert record.name == "upload.png"
    assert record.date_created == 1750000000


@respx.mock
async def test_rename_file_payload() -> None:
    mock_auth()
    route = respx.patch(FILE_URL).mock(return_value=envelope({"file": FILE_RECORD}))
    async with HaxcmsClient(make_settings()) as client:
        await service.rename_file(client, "demo", "abc-123", "renamed.png")
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"operation": "rename", "newName": "renamed.png"}


async def test_rename_file_rejects_empty_name() -> None:
    # validation fires before any client use, so no mocks are needed
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await service.rename_file(None, "demo", "abc-123", "   ")  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "filename" in excinfo.value.message


@respx.mock
async def test_transform_scale_sends_size_as_string() -> None:
    mock_auth()
    route = respx.patch(FILE_URL).mock(return_value=envelope({"operation": "scale"}))
    async with HaxcmsClient(make_settings()) as client:
        await service.transform_file(client, "demo", "abc-123", "scale", size=800)
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"operation": "scale", "size": "800"}


@respx.mock
async def test_transform_compress_normalises_level() -> None:
    mock_auth()
    route = respx.patch(FILE_URL).mock(return_value=envelope({"operation": "compress"}))
    async with HaxcmsClient(make_settings()) as client:
        await service.transform_file(client, "demo", "abc-123", "compress", level="HEAVY")
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"operation": "compress", "level": "heavy"}


@respx.mock
async def test_transform_rejects_unknown_operation_and_level() -> None:
    mock_auth()
    route = respx.patch(FILE_URL).mock(return_value=envelope({}))
    async with HaxcmsClient(make_settings()) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await service.transform_file(client, "demo", "abc-123", "delete")
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
        assert "rotate-90" in (excinfo.value.hint or "")
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await service.transform_file(client, "demo", "abc-123", "compress", level="extreme")
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
        assert "maximum" in (excinfo.value.hint or "")
    assert route.call_count == 0


@respx.mock
async def test_duplicate_file_payload() -> None:
    mock_auth()
    route = respx.patch(FILE_URL).mock(return_value=envelope({"file": FILE_RECORD}))
    async with HaxcmsClient(make_settings()) as client:
        await service.duplicate_file(client, "demo", "abc-123")
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"operation": "duplicate"}


@respx.mock
async def test_delete_file_sends_bodyless_delete() -> None:
    mock_auth()
    route = respx.delete(FILE_URL).mock(return_value=envelope({"deleted": "abc-123"}))
    async with HaxcmsClient(make_settings()) as client:
        result = await service.delete_file(client, "demo", "abc-123")
    request = route.calls.last.request
    assert request.method == "DELETE"
    assert request.content == b""
    assert result == {"deleted": "abc-123"}


async def test_empty_uuid_rejected() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await service.get_file(None, "demo", "  ")  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "uuid" in excinfo.value.message


# --- rate limiting --------------------------------------------------------------------------------


@respx.mock
async def test_file_ops_429_maps_to_rate_limited() -> None:
    # retry_max=0 so the retry policy surfaces the 429 immediately instead of sleeping
    # out the real Retry-After (42s x retry_max) — this test asserts the mapping only.
    mock_auth()
    respx.patch(FILE_URL).mock(
        return_value=httpx.Response(
            429,
            json={"status": 429, "message": "too many file operations"},
            headers={"Retry-After": "42"},
        )
    )
    async with HaxcmsClient(make_settings(retry_max=0)) as client:
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await service.rename_file(client, "demo", "abc-123", "x.png")
    error = excinfo.value
    assert error.code is ErrorCode.RATE_LIMITED
    assert "42" in error.message
    assert error.details is not None and error.details["retry_after_s"] == "42"
