"""Security audit: local-path and URL sources in local (stdio) mode."""

from __future__ import annotations

import ipaddress
from pathlib import Path

import httpx
import pytest

from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.files import ssrf
from haxcms_mcp.services.files.sources import resolve_source

pytestmark = pytest.mark.unit

BASE = "http://haxcms.invalid"


async def test_local_paths_are_off_until_a_root_is_configured(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await resolve_source(str(tmp_path / "a.txt"), Settings(base_url=BASE))
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR
    assert "not enabled" in excinfo.value.message
    assert "HAXCMS_MCP_INPUT_ROOTS" in (excinfo.value.hint or "")


@pytest.mark.parametrize(
    "relative",
    [
        ".env",
        "project/.env",
        ".git/config",
        ".ssh/id_ed25519",
        "keys/id_rsa",
        "keys/server.pem",
        "keys/tls.key",
        "certs/bundle.p12",
        "prod.env",
        "credentials.json",
        "secrets.yaml",
        ".npmrc",
    ],
)
async def test_hidden_and_key_files_are_refused_inside_a_root(
    tmp_path: Path, relative: str
) -> None:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("HAXCMS_MCP_PASSWORD=hunter2")
    settings = Settings(base_url=BASE, input_roots=[tmp_path])
    for source in (str(target), relative):
        with pytest.raises(HaxcmsMcpError) as excinfo:
            await resolve_source(source, settings)
        assert "refusing to read" in excinfo.value.message


async def test_ordinary_files_still_work(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    resolved = await resolve_source(
        "images/photo.png", Settings(base_url=BASE, input_roots=[tmp_path])
    )
    assert resolved.filename == "photo.png"


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.8", "192.168.1.20", "172.16.4.4", "100.64.1.1", "::1", "fd12::1"],
)
def test_allow_private_permits_lan_and_loopback(address: str) -> None:
    assert ssrf.is_allowed_private_address(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",  # cloud metadata (link-local)
        "169.254.10.10",
        "fe80::1",
        "fd00:ec2::254",  # AWS IMDS IPv6
        "100.100.100.200",  # Alibaba metadata
        "168.63.129.16",  # Azure wire server
        "::ffff:169.254.169.254",
        "64:ff9b::a9fe:a9fe",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
    ],
)
def test_allow_private_still_refuses_metadata_and_link_local(address: str) -> None:
    assert ssrf.is_allowed_private_address(ipaddress.ip_address(address)) is False


async def test_stdio_url_sources_reach_the_lan_but_never_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = {"nas.lan": ["192.168.1.20"], "metadata.lan": ["169.254.169.254"]}

    async def resolve(host: str, port: int) -> list[str]:
        return answers[host]

    monkeypatch.setattr(ssrf, "_system_resolve", resolve)
    settings = Settings(base_url=BASE)  # stdio: private addresses allowed

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_with_mock(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ssrf.httpx, "AsyncClient", client_with_mock)
    resolved = await resolve_source("http://nas.lan/doc.pdf", settings)
    assert resolved.data == b"%PDF-1.4"
    with pytest.raises(HaxcmsMcpError, match="non-public"):
        await resolve_source("http://metadata.lan/latest/meta-data/", settings)
