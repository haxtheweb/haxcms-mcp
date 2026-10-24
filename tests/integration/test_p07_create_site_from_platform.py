"""Live integration tests for the platform import path (PLAN T7.6).

DEVIATION from the PLAN's "html platform from a local server" sketch (recorded in
PROGRESS.md): the server's safeFetch SSRF guard refuses loopback/private/link-local
addresses with 400 `data.error` and has no env override, so a local http server can
NEVER feed the repoUrl mode. The html platform's reachable local path is the multipart
file upload (exercised here at the system_api level), and the guard itself is asserted
live through the tool. The remote platforms (gitbook, pressbooks, ...) need public
sample exports; the docs name none, so those tests are `network`-marked and take their
URLs from the environment (skipped when unset).
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import os
import secrets
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from haxcms_mcp.client import HaxcmsClient, system_api
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "import"
PAGE_HTML = FIXTURES / "page.html"


@contextlib.contextmanager
def _local_http_server(directory: Path) -> Iterator[int]:
    """Serve `directory` on a free loopback port for the SSRF-refusal probe."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


async def test_html_platform_multipart_upload_produces_items(client: HaxcmsClient) -> None:
    """The html platform's local mode: a multipart .html upload (no site is created)."""
    data = await system_api.import_platform(
        client,
        "html",
        filename="page.html",
        content=PAGE_HTML.read_bytes(),
        mimetype="text/html",
    )
    items = data["items"]
    assert [item["title"] for item in items] == ["Field Trip", "Logistics", "Packing List"]
    assert items[1]["slug"] == "field-trip/logistics"
    assert items[1]["parent"] == items[0]["id"]
    assert "north parking lot" in items[1]["contents"]
    assert data["filename"] == "page.html"


async def test_local_url_is_refused_by_the_ssrf_guard(mcp: McpTestClient) -> None:
    """A loopback repoUrl is rejected upstream; the tool surfaces the guarded message
    with the hint pointing at create_site_from_document for local HTML."""
    with _local_http_server(FIXTURES) as port:
        error = await mcp.call_error(
            "create_site_from_platform",
            name=f"mcp-p7p-{secrets.token_hex(4)}",
            platform="html",
            url=f"http://127.0.0.1:{port}/page.html",
        )
    assert "[INVALID_ARGUMENT]" in error
    assert "private, reserved, loopback" in error
    assert "create_site_from_document" in error


async def test_unknown_platform_is_refused(mcp: McpTestClient) -> None:
    error = await mcp.call_error(
        "create_site_from_platform",
        name=f"mcp-p7u-{secrets.token_hex(4)}",
        platform="myspace",
        url="https://example.invalid/export",
    )
    assert "[INVALID_ARGUMENT]" in error
    assert "platform" in error.lower()


@pytest.mark.network
async def test_gitbook_import_from_env_url(mcp: McpTestClient) -> None:
    """GitBook import against a PUBLIC sample (GitHub repo URL or SUMMARY.md link).

    No stable public sample is documented, so the URL comes from the environment:
    HAXCMS_MCP_TEST_GITBOOK_URL (with HAXCMS_MCP_TEST_NETWORK=1).
    """
    url = os.environ.get("HAXCMS_MCP_TEST_GITBOOK_URL", "")
    if not url:
        pytest.skip("set HAXCMS_MCP_TEST_GITBOOK_URL to a public GitBook export URL")
    name = f"mcp-p7g-{secrets.token_hex(4)}"
    created = name
    try:
        detail = await mcp.call("create_site_from_platform", name=name, platform="gitbook", url=url)
        created = detail["name"]
        assert detail["page_count"] >= 1
        outline = await mcp.call("get_outline", site=created)
        assert outline["count"] >= 1
    finally:
        with contextlib.suppress(Exception):
            await mcp.call("archive_site", site=created)


@pytest.mark.network
async def test_pressbooks_import_from_env_url(mcp: McpTestClient) -> None:
    """Pressbooks import against a PUBLIC sample (site root; wp-json is discovered).

    HAXCMS_MCP_TEST_PRESSBOOKS_URL (with HAXCMS_MCP_TEST_NETWORK=1).
    """
    url = os.environ.get("HAXCMS_MCP_TEST_PRESSBOOKS_URL", "")
    if not url:
        pytest.skip("set HAXCMS_MCP_TEST_PRESSBOOKS_URL to a public Pressbooks site URL")
    name = f"mcp-p7b-{secrets.token_hex(4)}"
    created = name
    try:
        detail = await mcp.call(
            "create_site_from_platform", name=name, platform="pressbooks", url=url
        )
        created = detail["name"]
        assert detail["page_count"] >= 1
        outline = await mcp.call("get_outline", site=created)
        assert outline["count"] >= 1
    finally:
        with contextlib.suppress(Exception):
            await mcp.call("archive_site", site=created)
