"""#3140: SSRF guard for URL sources and fail-closed HTTP settings."""

from __future__ import annotations

import ipaddress
from pathlib import Path

import httpx
import pytest

from haxcms_mcp.config import Settings, is_loopback_host
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.files import sources
from haxcms_mcp.services.files.ssrf import guarded_fetch, is_public_address, validate_url

pytestmark = pytest.mark.unit

BASE = "http://haxcms.invalid"
PUBLIC = "93.184.215.14"


def resolver(table: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return table[host]

    return resolve


def never_too_large(size: int) -> None:
    if size > 1000:
        raise HaxcmsMcpError(ErrorCode.FILE_SOURCE_ERROR, f"too large: {size}")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
        "2002:7f00:1::",  # 6to4 of 127.0.0.1
    ],
)
def test_non_public_addresses_are_refused(address: str) -> None:
    assert is_public_address(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize("address", [PUBLIC, "2606:4700:4700::1111"])
def test_public_addresses_pass(address: str) -> None:
    assert is_public_address(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://[::1]/x",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://example.com/x",
        "file:///etc/passwd",
        "http://user:pw@example.com/x",
    ],
)
async def test_validate_url_refuses(url: str) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await validate_url(url, resolve=resolver({"example.com": [PUBLIC]}))
    assert excinfo.value.code is ErrorCode.FILE_SOURCE_ERROR


async def test_a_name_with_any_private_answer_is_refused() -> None:
    with pytest.raises(HaxcmsMcpError, match="non-public"):
        await validate_url(
            "https://mixed.example/x", resolve=resolver({"mixed.example": [PUBLIC, "10.0.0.5"]})
        )


async def test_public_name_is_pinned_to_the_validated_address() -> None:
    target = await validate_url(
        "https://files.example:8443/a/b.png?x=1", resolve=resolver({"files.example": [PUBLIC]})
    )
    assert target.url == f"https://{PUBLIC}:8443/a/b.png?x=1"
    assert target.host == "files.example"
    assert target.host_header == "files.example:8443"


async def test_guarded_fetch_connects_to_the_pinned_ip_with_host_and_sni() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"PNGDATA", headers={"content-type": "image/png"})

    result = await guarded_fetch(
        "https://files.example/a.png",
        timeout_s=5,
        check_size=never_too_large,
        resolve=resolver({"files.example": [PUBLIC]}),
        transport=httpx.MockTransport(handler),
    )
    assert result.content == b"PNGDATA"
    assert seen[0].url.host == PUBLIC
    assert seen[0].headers["host"] == "files.example"
    assert seen[0].extensions["sni_hostname"] == "files.example"


async def test_redirect_to_a_private_address_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

    with pytest.raises(HaxcmsMcpError, match="169.254.169.254"):
        await guarded_fetch(
            "https://files.example/a.png",
            timeout_s=5,
            check_size=never_too_large,
            resolve=resolver({"files.example": [PUBLIC]}),
            transport=httpx.MockTransport(handler),
        )


async def test_redirect_to_a_name_that_resolves_private_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "https://internal.example/admin"})

    with pytest.raises(HaxcmsMcpError, match="non-public"):
        await guarded_fetch(
            "https://files.example/a.png",
            timeout_s=5,
            check_size=never_too_large,
            resolve=resolver({"files.example": [PUBLIC], "internal.example": ["192.168.0.2"]}),
            transport=httpx.MockTransport(handler),
        )


async def test_redirect_loops_stop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(HaxcmsMcpError, match="redirects"):
        await guarded_fetch(
            "https://files.example/a",
            timeout_s=5,
            check_size=never_too_large,
            resolve=resolver({"files.example": [PUBLIC]}),
            transport=httpx.MockTransport(handler),
        )


async def test_public_redirect_is_followed_and_revalidated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, content=b"ok")

    result = await guarded_fetch(
        "https://files.example/start",
        timeout_s=5,
        check_size=never_too_large,
        resolve=resolver({"files.example": [PUBLIC]}),
        transport=httpx.MockTransport(handler),
    )
    assert result.content == b"ok"
    assert result.url == "https://files.example/final"


async def test_body_over_the_cap_is_stopped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    with pytest.raises(HaxcmsMcpError, match="too large"):
        await guarded_fetch(
            "https://files.example/big",
            timeout_s=5,
            check_size=never_too_large,
            resolve=resolver({"files.example": [PUBLIC]}),
            transport=httpx.MockTransport(handler),
        )


# --- settings: what turns the guards on, and fail-closed binding -----------------------


def test_stdio_defaults_keep_local_and_private_sources() -> None:
    settings = Settings(base_url=BASE)
    assert settings.ssrf_guard_enabled is False
    assert settings.local_sources_enabled is True
    assert settings.per_caller_auth is False


def test_http_defaults_turn_the_guards_on() -> None:
    settings = Settings(base_url=BASE, transport="http")
    assert settings.ssrf_guard_enabled is True
    assert settings.local_sources_enabled is False


def test_operator_overrides_win() -> None:
    settings = Settings(
        base_url=BASE, transport="http", allow_private_url_sources=True, allow_local_sources=True
    )
    assert settings.ssrf_guard_enabled is False
    assert settings.local_sources_enabled is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "mcp.example.org"])
def test_http_on_a_non_loopback_host_without_auth_fails_closed(host: str) -> None:
    with pytest.raises(ValueError, match="without authentication"):
        Settings(base_url=BASE, transport="http", http_host=host)


def test_http_on_a_non_loopback_host_with_auth_is_allowed() -> None:
    settings = Settings(base_url=BASE, transport="http", http_host="0.0.0.0", http_auth="haxcms")
    assert settings.per_caller_auth is True


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.2"])
def test_loopback_hosts(host: str) -> None:
    assert is_loopback_host(host) is True


async def test_http_mode_refuses_local_paths(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("secret")
    settings = Settings(base_url=BASE, transport="http", input_roots=[tmp_path])
    with pytest.raises(HaxcmsMcpError, match="local file paths"):
        await sources.resolve_source(str(tmp_path / "a.txt"), settings)


async def test_http_mode_refuses_private_urls() -> None:
    settings = Settings(base_url=BASE, transport="http")
    with pytest.raises(HaxcmsMcpError, match="non-public"):
        await sources.resolve_source("http://127.0.0.1:3000/system/api/v1/status", settings)
