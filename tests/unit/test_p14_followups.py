"""Security follow-ups: capped streamed downloads, published-link confinement, per-user
outbound budgets with a total cap."""

from __future__ import annotations

import gzip

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient, system_api
from haxcms_mcp.client.principal import Principal, current_principal
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.files import ssrf

pytestmark = pytest.mark.unit

BASE = "http://haxcms.invalid"


def settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, no_auth=True, **kwargs)  # type: ignore[arg-type]


async def test_downloads_over_the_cap_are_refused_without_buffering() -> None:
    async with HaxcmsClient(settings(download_max_mb=1)) as client:
        with respx.mock(base_url=BASE) as router:
            router.get("/_published/big.zip").mock(
                return_value=httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
            )
            with pytest.raises(HaxcmsMcpError) as excinfo:
                await system_api.fetch_published(client, "/_published/big.zip")
    assert excinfo.value.code is ErrorCode.UNSUPPORTED
    assert "download cap" in excinfo.value.message


async def test_compressed_bodies_are_capped_after_decoding() -> None:
    bomb = gzip.compress(b"\0" * (3 * 1024 * 1024))  # tiny on the wire, 3 MB decoded
    async with HaxcmsClient(settings(download_max_mb=1)) as client:
        with respx.mock(base_url=BASE) as router:
            router.get("/_published/bomb.zip").mock(
                return_value=httpx.Response(200, content=bomb, headers={"content-encoding": "gzip"})
            )
            with pytest.raises(HaxcmsMcpError, match="download cap"):
                await system_api.fetch_published(client, "/_published/bomb.zip")


async def test_downloads_under_the_cap_arrive_decoded() -> None:
    payload = b"PK\x03\x04" + b"z" * 1000
    async with HaxcmsClient(settings()) as client:
        with respx.mock(base_url=BASE) as router:
            router.get("/_published/ok.zip").mock(
                return_value=httpx.Response(
                    200, content=gzip.compress(payload), headers={"content-encoding": "gzip"}
                )
            )
            assert await system_api.fetch_published(client, "/_published/ok.zip") == payload


@pytest.mark.parametrize(
    "link",
    [
        "http://169.254.169.254/latest/meta-data/",
        "//evil.example/_published/x.zip",
        "/system/api/v1/sites",
        "https://haxcms.invalid/_published/x.zip",
    ],
)
async def test_published_links_never_leave_the_published_mount(link: str) -> None:
    async with HaxcmsClient(settings()) as client:
        with (
            respx.mock(base_url=BASE, assert_all_called=False),
            pytest.raises(HaxcmsMcpError) as excinfo,
        ):
            await system_api.fetch_published(client, link)
    assert "unexpected download link" in excinfo.value.message


# --- per-user budgets -------------------------------------------------------------------------


def per_caller(**kwargs: object) -> Settings:
    return Settings(
        base_url=BASE,
        transport="http",
        http_auth="haxcms",
        **kwargs,  # type: ignore[arg-type]
    )


def as_user(name: str) -> object:
    return current_principal.set(Principal(f"token-{name}", name))


async def test_each_user_has_their_own_budget_and_all_share_a_total() -> None:
    async with HaxcmsClient(per_caller()) as client:
        reset = as_user("ann")
        try:
            ann = client.budget
            assert client._buckets() == [ann, client._total_budget]
        finally:
            current_principal.reset(reset)  # type: ignore[arg-type]
        reset = as_user("bob")
        try:
            bob = client.budget
        finally:
            current_principal.reset(reset)  # type: ignore[arg-type]
        assert ann is not bob
        # the same user with a rotated token keeps the same bucket
        reset = current_principal.set(Principal("a-new-token", "ann"))
        try:
            assert client.budget is ann
        finally:
            current_principal.reset(reset)


async def test_one_busy_user_does_not_drain_another() -> None:
    async with HaxcmsClient(
        per_caller(rate_limit_rps=0.001, rate_limit_burst=2, rate_limit_max_wait_s=0)
    ) as client:
        reset = as_user("busy")
        try:
            assert client.budget.try_acquire() and client.budget.try_acquire()
            assert client.budget.try_acquire() is False  # busy's own bucket is empty
        finally:
            current_principal.reset(reset)  # type: ignore[arg-type]
        reset = as_user("quiet")
        try:
            assert client.budget.try_acquire() is True  # quiet still has its own
        finally:
            current_principal.reset(reset)  # type: ignore[arg-type]


async def test_stdio_keeps_one_process_budget() -> None:
    async with HaxcmsClient(settings()) as client:
        reset = as_user("ignored")
        try:
            assert client._buckets() == [client._shared_budget]
        finally:
            current_principal.reset(reset)  # type: ignore[arg-type]


# --- explicit egress proxy for URL sources ---------------------------------------------------


async def test_via_proxy_hands_host_names_to_the_proxy_unresolved() -> None:
    async def never(host: str, port: int) -> list[str]:
        raise AssertionError("no local DNS in proxy mode")

    target = await ssrf.validate_url(
        "https://files.example/a.png?x=1", resolve=never, via_proxy=True
    )
    assert target.url == "https://files.example/a.png?x=1"  # not pinned


@pytest.mark.parametrize(
    "url", ["http://169.254.169.254/latest/", "http://10.0.0.1/", "ftp://files.example/x"]
)
async def test_via_proxy_still_refuses_internal_ip_literals_and_odd_schemes(url: str) -> None:
    with pytest.raises(HaxcmsMcpError):
        await ssrf.validate_url(url, via_proxy=True)
