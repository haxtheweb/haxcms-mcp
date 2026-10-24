"""Phase 5 integration tests: the files lifecycle against the live instance.

PLAN Phase 5 integration list: `test_p05_files.py` — upload a fixture png (path source) ->
appears in list with width/height -> get -> rename -> duplicate -> scale -> delete; upload by
URL served from a tiny local http server; upload by base64; oversize inline rejected; disk
assertions (the file lands under `<site>/files/`, its uuid in `<site>/files/files.json`).
Plus the T5.7 verify-and-record items, live-probed: the multipart field the server accepts,
the site-relative `url` form, extension-rejection behaviour, the rename extension lock, and
the `nodeId` effect.

Live-contract facts pinned from `../haxcms-nodejs` source (read-only) and recorded in
PROGRESS.md:

* `fullUrl` is ROOT-RELATIVE (`buildFilePublicUrl`): `/_sites/<site>/files/<name>` in this
  multisite test runtime (absolute only if the instance is configured with an absolute
  basePath). `list`/`get` serve the `files.json` datastore records, which carry
  `width`/`height` and append a `?t=<dateCreated>` cache-buster to fullUrl; the *upload*
  response's fullUrl is bare (no `?t=`).
* `rename` `fs.moveSync`s the disk file and PRESERVES the uuid (files.json owns identity); the
  new basename is sanitized to `[a-z0-9-]` (lowercased, `_`->`-`), so "Renamed_1"->"renamed-1";
  `duplicate` mints `<base>-copy.<ext>` with a NEW uuid; `scale`/`compress`/`sepia`/
  `black-and-white`/`rotate-90` are in-place (uuid preserved). `scale` uses `fit: inside,
  withoutEnlargement`, so a 120x80 png scaled to the `sm` preset (480x480) stays 120x80.
* `delete` removes the disk file AND the files.json record (FileStorage.delete ->
  removeRecord), so a later `get` is NOT_FOUND.
* a disallowed extension is HTTP 500 'File type not allowed' (-> UPSTREAM_ERROR); a rename
  that changes the extension is HTTP 400 (-> INVALID_ARGUMENT).
* `nodeId` loads the page but upload no longer appends to `page.metadata.files` (#3043) —
  that set is rebuilt from a content path-scan on page SAVE (see the functional suite).
"""

from __future__ import annotations

import base64
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.item import Item
from haxcms_mcp.services.files import service as files_service
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "images"
SONGLINE_1 = FIXTURES / "Songline_1.png"  # 120 x 80
SONGLINE_2 = FIXTURES / "Songline_2.png"  # 100 x 60


def _read_store(haxcms: HaxcmsRuntime, site: str) -> dict[str, Any]:
    """The site's `files/files.json` datastore envelope (HAXCMS-FILE-SCHEMA-V1)."""
    path = haxcms.site_dir(site) / "files" / "files.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _store_uuids(haxcms: HaxcmsRuntime, site: str) -> set[str]:
    store = _read_store(haxcms, site)
    return {str(record["uuid"]) for record in store["data"]["files"]}


# --- the PLAN lifecycle ----------------------------------------------------------------


async def test_file_lifecycle(mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime) -> None:
    """upload -> list (with width/height) -> get -> rename -> duplicate -> scale -> delete."""
    site_dir = haxcms.site_dir(site)

    # 1. upload the 120x80 fixture by local path
    result = await mcp.call("upload_file", source=str(SONGLINE_1), site=site)
    uploaded = result["file"]
    uuid = uploaded["uuid"]
    assert uuid
    assert uploaded["name"] == "Songline_1.png"
    assert uploaded["url"] == "files/Songline_1.png"  # site-relative
    assert uploaded["path"] == "files/Songline_1.png"
    assert uploaded["mimetype"] == "image/png"
    assert uploaded["width"] == 120
    assert uploaded["height"] == 80
    assert uploaded["size"] > 0
    # fullUrl is root-relative (multisite: /_sites/<site>/files/<name>); the upload response's
    # fullUrl is bare - no ?t=<dateCreated> cache-buster (list/get append that).
    assert uploaded["full_url"].startswith("/")
    assert uploaded["full_url"].endswith("files/Songline_1.png")
    assert site in uploaded["full_url"]
    assert "t=" not in uploaded["full_url"]

    # 2. it appears in list WITH pixel dimensions (list serves datastore records)
    listed = await mcp.call("list_files", site=site)
    rec = next(f for f in listed["files"] if f["uuid"] == uuid)
    assert rec["url"] == "files/Songline_1.png"
    assert rec["width"] == 120
    assert rec["height"] == 80
    assert rec["mimetype"] == "image/png"

    # 3. get by uuid — fullUrl carries the ?t=<dateCreated> cache-buster
    got = await mcp.call("get_file", uuid=uuid, site=site)
    assert got["uuid"] == uuid
    assert got["url"] == "files/Songline_1.png"
    assert got["mimetype"] == "image/png"
    assert got["full_url"].startswith("/")  # root-relative (/_sites/<site>/files/<name>)
    assert got["full_url"].split("?")[0].endswith("files/Songline_1.png")
    assert "t=" in got["full_url"]  # list/get append the ?t=<dateCreated> cache-buster
    assert got["date_created"] is not None

    # 4. disk: the file is under <site>/files/ and its uuid is in files.json
    assert (site_dir / "files" / "Songline_1.png").is_file()
    store = _read_store(haxcms, site)
    assert store["schema"] == "HAXCMS-FILE-SCHEMA-V1"
    assert store["data"]["path"] == "files"
    assert uuid in _store_uuids(haxcms, site)

    # 5. rename (same extension) — uuid preserved, disk file moved
    renamed = await mcp.call("rename_file", uuid=uuid, new_name="Renamed_1.png", site=site)
    assert renamed["operation"] == "rename"
    assert renamed["source"] == "files/Songline_1.png"
    # the server sanitizes the new basename to [a-z0-9-] (lowercase, `_`->`-`), so the
    # requested "Renamed_1.png" is stored as "renamed-1.png" (extension locked to .png).
    assert renamed["path"] == "files/renamed-1.png"
    after_rename = await mcp.call("get_file", uuid=uuid, site=site)  # SAME uuid still resolves
    assert after_rename["uuid"] == uuid
    assert after_rename["url"] == "files/renamed-1.png"
    assert after_rename["name"] == "renamed-1.png"
    assert (site_dir / "files" / "renamed-1.png").is_file()
    assert not (site_dir / "files" / "Songline_1.png").exists()

    # 6. duplicate — new uuid, `<base>-copy.<ext>` name
    dup = await mcp.call("duplicate_file", uuid=uuid, site=site)
    assert dup["operation"] == "duplicate"
    assert dup["path"] == "files/renamed-1-copy.png"  # duplicate of the renamed file
    copy_uuid = dup["file"]["uuid"]
    assert copy_uuid and copy_uuid != uuid
    assert (site_dir / "files" / "renamed-1-copy.png").is_file()

    # 7. scale in place (preset key `sm` = 480x480 fit-inside; 120x80 stays, no enlarge)
    scaled = await mcp.call("transform_file", uuid=uuid, operation="scale", size="sm", site=site)
    assert scaled["operation"] == "scale"
    after_scale = await mcp.call("get_file", uuid=uuid, site=site)
    assert after_scale["uuid"] == uuid  # in-place transform preserves the uuid
    assert after_scale["width"] == 120
    assert after_scale["height"] == 80
    assert after_scale["mimetype"] == "image/png"

    # 8. delete — disk file AND files.json record gone; get -> NOT_FOUND; the copy survives
    deleted = await mcp.call("delete_file", uuid=uuid, site=site)
    assert deleted["operation"] == "delete"
    assert deleted["deleted"] is True
    assert not (site_dir / "files" / "renamed-1.png").exists()
    assert uuid not in _store_uuids(haxcms, site)
    err = await mcp.call_error("get_file", uuid=uuid, site=site)
    assert "NOT_FOUND" in err
    listed_after = await mcp.call("list_files", site=site)
    remaining = {f["uuid"] for f in listed_after["files"]}
    assert uuid not in remaining
    assert copy_uuid in remaining


async def test_list_filters(mcp: McpTestClient, site: str) -> None:
    """type / extension / name_contains filters combine on the live route."""
    await mcp.call("upload_file", source=str(SONGLINE_1), site=site)
    await mcp.call("upload_file", source=str(SONGLINE_2), site=site)

    images = await mcp.call("list_files", type="image", site=site)
    assert {"Songline_1.png", "Songline_2.png"} <= {f["name"] for f in images["files"]}

    # the extension filter strips a leading dot and is case-insensitive
    pngs = await mcp.call("list_files", extension=".PNG", site=site)
    assert {"Songline_1.png", "Songline_2.png"} <= {f["name"] for f in pngs["files"]}

    only_first = await mcp.call("list_files", name_contains="Songline_1", site=site)
    names = {f["name"] for f in only_first["files"]}
    assert "Songline_1.png" in names
    assert "Songline_2.png" not in names


# --- the other source forms --------------------------------------------------------------


async def test_upload_by_url(mcp: McpTestClient, site: str) -> None:
    """An http(s) source is fetched by this MCP server from a tiny local http server."""
    handler = functools.partial(_QuietHandler, directory=str(FIXTURES))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        result = await mcp.call(
            "upload_file", source=f"http://127.0.0.1:{port}/Songline_2.png", site=site
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    uploaded = result["file"]
    assert uploaded["name"] == "Songline_2.png"  # basename from the URL path
    assert uploaded["url"] == "files/Songline_2.png"
    assert uploaded["mimetype"] == "image/png"
    assert uploaded["width"] == 100
    assert uploaded["height"] == 60


async def test_upload_by_base64(mcp: McpTestClient, site: str) -> None:
    """A `base64:<name>:<payload>` source uploads under the given name."""
    payload = base64.b64encode(SONGLINE_2.read_bytes()).decode("ascii")
    result = await mcp.call("upload_file", source=f"base64:FromBase64.png:{payload}", site=site)
    uploaded = result["file"]
    assert uploaded["name"] == "FromBase64.png"
    assert uploaded["url"] == "files/FromBase64.png"
    assert uploaded["mimetype"] == "image/png"  # sniffed from the bytes
    assert uploaded["width"] == 100
    assert uploaded["height"] == 60


async def test_oversize_inline_rejected(
    client: HaxcmsClient, settings: Settings, site: str
) -> None:
    """An inline source over MAX_INLINE_BASE64_MB is rejected before any transfer."""
    payload = base64.b64encode(SONGLINE_2.read_bytes()).decode("ascii")
    tiny = settings.model_copy(update={"max_inline_base64_mb": 0})
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await files_service.upload_file(client, tiny, site, f"base64:TooBig.png:{payload}")
    assert excinfo.value.code == ErrorCode.FILE_SOURCE_ERROR
    assert "inline" in excinfo.value.message.lower()
    # nothing reached the site
    listed = await files_service.list_files(client, site)
    assert all(record.name != "TooBig.png" for record in listed.files)


# --- T5.7 verify-and-record probes -------------------------------------------------------


async def test_server_accepts_alternate_multipart_field(client: HaxcmsClient, site: str) -> None:
    """T5.7: the route accepts the alternate `upload` multipart field (multer `.any()`)."""
    png = SONGLINE_2.read_bytes()
    response = await client.request(
        "POST",
        client.site_path(site, "files"),
        files={"upload": ("AltField.png", png, "image/png")},
        auth="bearer+site",
        site=site,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == 200
    assert body["data"]["file"]["name"] == "AltField.png"
    assert body["data"]["file"]["url"] == "files/AltField.png"


async def test_disallowed_extension_rejected(mcp: McpTestClient, site: str) -> None:
    """T5.7: a disallowed extension is refused upstream (HTTP 500 -> UPSTREAM_ERROR)."""
    payload = base64.b64encode(SONGLINE_1.read_bytes()).decode("ascii")
    err = await mcp.call_error("upload_file", source=f"base64:archive.zip:{payload}", site=site)
    assert "UPSTREAM_ERROR" in err


async def test_rename_cannot_change_extension(mcp: McpTestClient, site: str) -> None:
    """T5.7: rename locks the extension (HTTP 400 -> INVALID_ARGUMENT)."""
    result = await mcp.call("upload_file", source=str(SONGLINE_1), site=site)
    uuid = result["file"]["uuid"]
    err = await mcp.call_error("rename_file", uuid=uuid, new_name="Renamed.jpg", site=site)
    assert "INVALID_ARGUMENT" in err


async def test_upload_with_page_does_not_touch_metadata_files(
    mcp: McpTestClient, site: str, page: Item
) -> None:
    """T5.7: `nodeId` loads the page but upload no longer appends to metadata.files (#3043)."""
    result = await mcp.call("upload_file", source=str(SONGLINE_2), page=page.id, site=site)
    uuid = result["file"]["uuid"]
    record = await mcp.call("get_page", page=page.id, site=site)
    files = record["metadata"].get("files") or []
    # the association only lands when the page is SAVED with the file referenced in its
    # body — that is the add_image_from_file composite path (see the functional suite).
    assert uuid not in files


class _QuietHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler that does not spam stderr during the URL-upload test."""

    def log_message(self, format: str, *args: Any) -> None:
        pass
