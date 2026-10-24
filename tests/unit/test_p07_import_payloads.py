"""Unit tests for the Phase 7 import/converter endpoint helpers (PLAN T7.2).

respx goldens over the live-probed wire shapes: the multipart document-import body
(`file-upload` part + method/type/parentId form fields), the platform-import JSON and
multipart modes with the dispatcher's lowercase/trim, the converter `action()` envelope
handling (`data.contents` text results, xlsxToCsv's `sheet` QUERY param, docxToPdf's RAW
application/pdf bytes under raw=True), and the `data.error` -> INVALID_ARGUMENT mapping
every import/converter 400 uses. Response goldens mirror the Phase 7 live probe.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient, system_api
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.imports import ConversionResult, ImportData

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
LOGIN_URL = f"{BASE}/system/api/v1/session/login"
CONN_URL = f"{BASE}/system/api/v1/session/connection-settings"
IMPORT_DOCX_URL = f"{BASE}/system/api/v1/actions/import-docx"
IMPORT_HTML_URL = f"{BASE}/system/api/v1/site/import/html"
IMPORT_WP_URL = f"{BASE}/system/api/v1/site/import/wordpress"
MD_TO_HTML_URL = f"{BASE}/system/api/v1/actions/md-to-html"
HTML_TO_DOCX_URL = f"{BASE}/system/api/v1/actions/html-to-docx"
XLSX_TO_CSV_URL = f"{BASE}/system/api/v1/actions/xlsx-to-csv"
DOCX_TO_PDF_URL = f"{BASE}/system/api/v1/actions/docx-to-pdf"

APP_SETTINGS_JS = (
    "window.MicroFrontendRegistryConfig = window.MicroFrontendRegistryConfig || {};\n"
    'window.appSettings ={"token":"t","siteToken":"site-tok","userToken":"user-tok",'
    '"siteApiBasePath":"/_sites/demo/x/api"};\n'
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 16  # zip magic (importDocx checks it)

# Live-probe golden: importDocx built these from a two-heading document — server-fresh
# ids, `contents` (NOT `content`), and the nested child slug `parentSlug/childSlug`.
IMPORTED_ITEMS = [
    {
        "id": "item-uuid-1",
        "title": "Unit One",
        "slug": "unit-one",
        "parent": None,
        "indent": 0,
        "order": 0,
        "contents": "<p>Overview</p>",
        "metadata": {},
    },
    {
        "id": "item-uuid-2",
        "title": "Lesson One",
        "slug": "unit-one/lesson-one",
        "parent": "item-uuid-1",
        "indent": 1,
        "order": 1,
        "contents": '<p>Content with <img src="data:image/png;base64,AAAA"/></p>',
        "metadata": {},
    },
]


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, username="envuser", password="envpass", **kwargs)  # type: ignore[arg-type]


def mock_auth() -> None:
    respx.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, json={"status": 200, "jwt": "jwt-1"})
    )
    respx.get(CONN_URL).mock(return_value=httpx.Response(200, text=APP_SETTINGS_JS))


def envelope(data: object) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "data": data})


def error_envelope(message: str, status: int = 400) -> httpx.Response:
    """The import/converter error shape (live-probed): data.error, NOT data.message."""
    return httpx.Response(
        status,
        json={"status": status, "data": {"error": message, "items": [], "filename": None}},
    )


def assert_user_auth(request: httpx.Request) -> None:
    assert request.headers["Authorization"] == "Bearer jwt-1"  # the login jwt
    assert request.headers["X-HAXCMS-User-Token"] == "user-tok"  # from appSettings


# --- import_document ---------------------------------------------------------------------------


@respx.mock
async def test_import_document_multipart_shape() -> None:
    mock_auth()
    route = respx.post(IMPORT_DOCX_URL).mock(
        return_value=envelope({"items": IMPORTED_ITEMS, "filename": "lesson.docx"})
    )
    async with HaxcmsClient(make_settings()) as client:
        data = await system_api.import_document(
            client,
            "docx",
            filename="lesson.docx",
            content=DOCX_BYTES,
            mimetype=DOCX_MIME,
            method="branch",
            content_type="course",
            parent_id="item-9",
        )
    request = route.calls.last.request
    assert_user_auth(request)
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="file-upload"' in body
    assert b'filename="lesson.docx"' in body
    assert b'name="method"' in body and b"branch" in body
    assert b'name="type"' in body and b"course" in body
    assert b'name="parentId"' in body and b"item-9" in body
    assert data["filename"] == "lesson.docx"
    parsed = ImportData.from_api(data)
    assert len(parsed.items) == 2
    assert parsed.items[1].slug == "unit-one/lesson-one"
    assert parsed.items[1].parent == "item-uuid-1"
    assert parsed.items[1].indent == 1
    assert "data:image/png;base64" in (parsed.items[1].contents or "")


@respx.mock
async def test_import_document_omits_unset_form_fields() -> None:
    mock_auth()
    route = respx.post(IMPORT_DOCX_URL).mock(
        return_value=envelope({"items": [], "filename": "x.docx"})
    )
    async with HaxcmsClient(make_settings()) as client:
        await system_api.import_document(
            client, "docx", filename="x.docx", content=DOCX_BYTES, mimetype=DOCX_MIME
        )
    body = route.calls.last.request.content
    assert b'name="method"' not in body
    assert b'name="type"' not in body
    assert b'name="parentId"' not in body


@respx.mock
async def test_import_document_unknown_kind_is_local() -> None:
    mock_auth()
    route = respx.post(IMPORT_DOCX_URL).mock(return_value=envelope({}))
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await system_api.import_document(
                client, "odt", filename="x.odt", content=b"x", mimetype="application/x-odt"
            )
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "odt" in error.message
    assert "docx" in (error.hint or "")
    assert route.call_count == 0


@respx.mock
async def test_import_document_error_maps_data_error() -> None:
    mock_auth()
    respx.post(IMPORT_DOCX_URL).mock(
        return_value=error_envelope("File type not supported. Please upload a .docx file.")
    )
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await system_api.import_document(
                client, "docx", filename="x.docx", content=DOCX_BYTES, mimetype=DOCX_MIME
            )
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert excinfo.value.message == "File type not supported. Please upload a .docx file."


# --- import_platform ---------------------------------------------------------------------------


@respx.mock
async def test_import_platform_json_body_and_dispatcher_normalization() -> None:
    mock_auth()
    route = respx.post(IMPORT_WP_URL).mock(
        return_value=envelope(
            {
                "items": IMPORTED_ITEMS,
                "filename": "wordpress-export",
                "files": {"files/img.png": "https://blog.example.invalid/img.png"},
                "siteFiles": {"files/logo.png": "https://blog.example.invalid/logo.png"},
                "site": {"license": "by-sa"},
            }
        )
    )
    async with HaxcmsClient(make_settings()) as client:
        data = await system_api.import_platform(
            client, " WordPress ", repo_url="https://blog.example.invalid", method="site"
        )
    request = route.calls.last.request  # dispatcher lowercases/trims -> wordpress path
    assert_user_auth(request)
    assert request.headers["content-type"].startswith("application/json")
    assert json.loads(request.content) == {
        "repoUrl": "https://blog.example.invalid",
        "method": "site",
    }
    parsed = ImportData.from_api(data)
    assert parsed.files == {"files/img.png": "https://blog.example.invalid/img.png"}
    assert parsed.site_files == {"files/logo.png": "https://blog.example.invalid/logo.png"}
    assert parsed.license == "by-sa"
    assert len(parsed.items) == 2


@respx.mock
async def test_import_platform_multipart_file() -> None:
    mock_auth()
    route = respx.post(IMPORT_HTML_URL).mock(
        return_value=envelope({"items": [], "filename": "index.html"})
    )
    async with HaxcmsClient(make_settings()) as client:
        await system_api.import_platform(
            client,
            "html",
            filename="index.html",
            content=b"<html><body><h1>Home</h1></body></html>",
            mimetype="text/html",
        )
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data")
    # siteImport.js allow-lists the field name: upload | file | file-upload
    assert b'name="file-upload"' in request.content
    assert b'filename="index.html"' in request.content


@respx.mock
async def test_import_platform_requires_a_source() -> None:
    mock_auth()
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await system_api.import_platform(client, "gitbook")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


@respx.mock
async def test_import_platform_multipart_requires_filename() -> None:
    mock_auth()
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await system_api.import_platform(client, "html", content=b"<h1>x</h1>")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "filename" in excinfo.value.message


@respx.mock
async def test_import_platform_unsupported_platform_message() -> None:
    mock_auth()
    respx.post(f"{BASE}/system/api/v1/site/import/foo").mock(
        return_value=error_envelope('Unsupported import platform "foo"')
    )
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await system_api.import_platform(client, "foo", repo_url="https://x.example.invalid")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert excinfo.value.message == 'Unsupported import platform "foo"'


# --- action (converters) ------------------------------------------------------------------------


@respx.mock
async def test_action_json_converter_returns_contents() -> None:
    mock_auth()
    route = respx.post(MD_TO_HTML_URL).mock(
        return_value=envelope({"contents": "<h1>Hello</h1>\n<p>World</p>\n"})
    )
    async with HaxcmsClient(make_settings()) as client:
        data = await system_api.action(client, "mdToHtml", json={"md": "# Hello\n\nWorld"})
    request = route.calls.last.request
    assert_user_auth(request)
    assert json.loads(request.content) == {"md": "# Hello\n\nWorld"}
    assert data == {"contents": "<h1>Hello</h1>\n<p>World</p>\n"}  # live-probe golden


@respx.mock
async def test_action_xlsx_sheet_is_a_query_param() -> None:
    mock_auth()
    route = respx.post(XLSX_TO_CSV_URL).mock(
        return_value=envelope(
            {
                "contents": "a,b\n1,2\n",
                "sheetNames": ["Sheet1", "Sheet2"],
                "selectedSheet": "Sheet2",
            }
        )
    )
    files = {
        "file-upload": (
            "book.xlsx",
            b"PK\x03\x04",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    async with HaxcmsClient(make_settings()) as client:
        data = await system_api.action(client, "xlsxToCsv", files=files, params={"sheet": "Sheet2"})
    assert route.calls.last.request.url.params["sheet"] == "Sheet2"
    assert data["selectedSheet"] == "Sheet2"
    assert data["sheetNames"] == ["Sheet1", "Sheet2"]


@respx.mock
async def test_action_raw_pdf_bytes_bypass_envelope() -> None:
    mock_auth()
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    route = respx.post(DOCX_TO_PDF_URL).mock(
        return_value=httpx.Response(
            200,
            content=pdf,
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="converted.pdf"',
            },
        )
    )
    files = {"file-upload": ("lesson.docx", DOCX_BYTES, DOCX_MIME)}
    async with HaxcmsClient(make_settings()) as client:
        content = await system_api.action(client, "docxToPdf", files=files, raw=True)
    assert content == pdf
    assert route.call_count == 1


@respx.mock
async def test_action_raw_error_still_maps_data_error() -> None:
    mock_auth()
    respx.post(DOCX_TO_PDF_URL).mock(return_value=error_envelope("No file uploaded"))
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await system_api.action(client, "docxToPdf", files={}, raw=True)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert excinfo.value.message == "No file uploaded"


@respx.mock
async def test_action_html_to_docx_missing_file_golden() -> None:
    """Live probe: html-to-docx with a JSON body instead of a file -> 400 data.error."""
    mock_auth()
    respx.post(HTML_TO_DOCX_URL).mock(return_value=error_envelope("No file uploaded"))
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await system_api.action(client, "htmlToDocx", json={"html": "<h1>x</h1>"})
    assert excinfo.value.message == "No file uploaded"


@respx.mock
async def test_action_unknown_operation_is_local() -> None:
    mock_auth()
    route = respx.post(MD_TO_HTML_URL).mock(return_value=envelope({}))
    with pytest.raises(HaxcmsMcpError) as excinfo:
        async with HaxcmsClient(make_settings()) as client:
            await system_api.action(client, "txtToMd", json={"txt": "x"})
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert "txtToMd" in error.message
    assert "mdToHtml" in (error.hint or "")
    assert route.call_count == 0


# --- response models -----------------------------------------------------------------------------


def test_import_data_extras_and_defaults() -> None:
    parsed = ImportData.from_api(
        {
            "items": [{"id": "a", "title": "A"}],
            "filename": "book.xlsx",
            "selectedSheet": "Sheet1",  # importXlsx adds this; rides along as an extra
        }
    )
    assert parsed.items[0].id == "a"
    assert parsed.items[0].contents is None
    assert parsed.model_extra == {"selectedSheet": "Sheet1"}
    assert parsed.files is None and parsed.site_files is None and parsed.license is None


def test_import_data_tolerates_junk() -> None:
    parsed = ImportData.from_api({"items": None, "filename": 3, "site": "nope"})
    assert parsed.items == []
    assert parsed.filename is None
    assert parsed.license is None
    assert parsed.model_extra == {}


def test_conversion_result_text_and_binary_shapes() -> None:
    dumped = dump_model(ConversionResult(text="<h1>Hi</h1>", mimetype="text/html"))
    assert dumped == {"text": "<h1>Hi</h1>", "mimetype": "text/html"}  # exclude_none
    dumped = dump_model(
        ConversionResult(
            path="haxcms-mcp-output/converted.docx",
            bytes=20651,
            mimetype=DOCX_MIME,
            filename="converted.docx",
        )
    )
    assert dumped["path"] == "haxcms-mcp-output/converted.docx"
    assert dumped["bytes"] == 20651
    assert "text" not in dumped
