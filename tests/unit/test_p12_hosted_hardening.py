"""Security audit fixes for the HTTP transport: DNS-rebinding guard settings, TLS requirement,
token-verification isolation (own budget, refusal cache) and the failed-auth limiter."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.http_auth import (
    VERIFY_FAILURE_TTL_S,
    AuthFailureLimiter,
    HaxcmsTokenVerifier,
    transport_middleware,
)

pytestmark = pytest.mark.unit

BASE = "http://haxcms.invalid"


def per_caller(**kwargs: Any) -> Settings:
    return Settings(base_url=BASE, transport="http", http_auth="haxcms", **kwargs)


# --- Host/Origin guard ------------------------------------------------------------------


def test_guard_is_always_strict_and_trusts_the_public_url() -> None:
    guard = per_caller(
        http_host="0.0.0.0",
        public_url="https://mcp.example.org",
        http_allowed_hosts="alt.example.org, 10.0.0.5",
        http_allowed_origins="https://app.example.org",
    ).transport_guard
    assert guard["host_origin_protection"] is True
    assert {"alt.example.org", "10.0.0.5", "mcp.example.org"} <= set(guard["allowed_hosts"])
    assert set(guard["allowed_origins"]) == {"https://app.example.org", "https://mcp.example.org"}


def test_loopback_default_trusts_nothing_extra() -> None:
    guard = Settings(base_url=BASE, transport="http").transport_guard
    assert guard == {"host_origin_protection": True, "allowed_hosts": [], "allowed_origins": []}


@pytest.mark.parametrize("public_url", [None, "http://mcp.example.org"])
def test_exposed_per_caller_mode_requires_https(public_url: str | None) -> None:
    with pytest.raises(ValueError, match="PUBLIC_URL=https"):
        per_caller(http_host="0.0.0.0", public_url=public_url)


def test_loopback_per_caller_mode_may_use_plain_http() -> None:
    assert per_caller().per_caller_auth is True


# --- verifier isolation -------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_refused_tokens_are_not_re_asked_about_until_the_failure_ttl() -> None:
    clock = FakeClock()
    async with HaxcmsClient(per_caller()) as client:
        verifier = HaxcmsTokenVerifier(client, clock=clock)
        with respx.mock(base_url=BASE) as router:
            route = router.get("/system/api/v1/session").mock(
                return_value=httpx.Response(401, json={"status": 401, "authenticated": False})
            )
            assert await verifier.verify_token("forged") is None
            assert await verifier.verify_token("forged") is None
            assert route.call_count == 1
            clock.now += VERIFY_FAILURE_TTL_S + 1
            assert await verifier.verify_token("forged") is None
            assert route.call_count == 2


async def test_an_unexpected_answer_is_not_cached_as_a_refusal() -> None:
    """Only a definitive HAXcms verdict (200/401/403) is cached; anything else (a 404 from a
    misrouted proxy, an outage after retries) is asked again next time."""
    async with HaxcmsClient(per_caller()) as client:
        verifier = HaxcmsTokenVerifier(client)
        with respx.mock(base_url=BASE) as router:
            route = router.get("/system/api/v1/session")
            route.side_effect = [
                httpx.Response(404, json={"status": 404}),
                httpx.Response(200, json={"status": 200, "authenticated": True, "user": "ann"}),
            ]
            assert await verifier.verify_token("good") is None
            access = await verifier.verify_token("good")
        assert access is not None and access.client_id == "ann"


async def test_verification_never_draws_from_the_tool_budget() -> None:
    async with HaxcmsClient(per_caller()) as client:
        verifier = HaxcmsTokenVerifier(client)
        before = client.budget.stats
        with respx.mock(base_url=BASE) as router:
            router.get("/system/api/v1/session").mock(
                return_value=httpx.Response(401, json={"status": 401})
            )
            for n in range(15):
                await verifier.verify_token(f"bogus-{n}")
        assert client.budget.stats == before


# --- failed-auth limiter ------------------------------------------------------------------


async def _call(app: Any, client_ip: str = "203.0.113.9") -> tuple[int, dict[bytes, bytes]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/mcp", "client": (client_ip, 5555)}
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], dict(start.get("headers") or [])


def _inner(status: int) -> Any:
    calls = {"n": 0}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        calls["n"] += 1
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app.calls = calls  # type: ignore[attr-defined]
    return app


async def test_limiter_blocks_a_client_after_repeated_401s() -> None:
    clock = FakeClock()
    inner = _inner(401)
    limiter = AuthFailureLimiter(inner, limit=3, window_s=60, clock=clock)
    statuses = [(await _call(limiter))[0] for _ in range(5)]
    assert statuses == [401, 401, 401, 429, 429]
    assert inner.calls["n"] == 3  # the blocked requests never reached auth / HAXcms
    status, headers = await _call(limiter)
    assert status == 429 and int(headers[b"retry-after"]) > 0
    # another address is unaffected, and the block lifts after the window
    assert (await _call(limiter, "198.51.100.7"))[0] == 401
    clock.now += 61
    assert (await _call(limiter))[0] == 401


async def test_limiter_ignores_successful_requests() -> None:
    limiter = AuthFailureLimiter(_inner(200), limit=2, clock=FakeClock())
    assert [(await _call(limiter))[0] for _ in range(5)] == [200] * 5


def test_limiter_only_installed_for_per_caller_mode() -> None:
    assert transport_middleware(Settings(base_url=BASE, transport="http")) == []
    assert len(transport_middleware(per_caller())) == 1
    assert transport_middleware(per_caller(auth_failures_per_minute=0)) == []


# --- per-caller output store -----------------------------------------------------------------


from haxcms_mcp.client.principal import Principal, current_principal  # noqa: E402
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError  # noqa: E402
from haxcms_mcp.services import output_store  # noqa: E402
from haxcms_mcp.services.exports import output as export_output  # noqa: E402
from haxcms_mcp.services.files import ssrf  # noqa: E402


def as_caller(user: str) -> Any:
    return current_principal.set(Principal(f"token-of-{user}", user))


def test_stdio_mode_keeps_absolute_paths_and_no_links(tmp_path: Path) -> None:
    settings = Settings(base_url=BASE, output_dir=tmp_path)
    stored = output_store.store(b"x", settings=settings, filename="a.pdf")
    assert stored.path == tmp_path / "a.pdf"
    assert stored.reported_path == str(tmp_path / "a.pdf")
    assert stored.download_url is None


def test_callers_write_into_separate_folders_and_get_signed_links(tmp_path: Path) -> None:
    settings = per_caller(output_dir=tmp_path, public_url="https://mcp.example.org")
    reset = as_caller("ann")
    try:
        ann = output_store.store(b"ann's", settings=settings, filename="a.pdf", sub="site")
    finally:
        current_principal.reset(reset)
    reset = as_caller("bob")
    try:
        bob = output_store.store(b"bob's", settings=settings, filename="a.pdf", sub="site")
    finally:
        current_principal.reset(reset)
    assert ann.path.parent != bob.path.parent
    assert ann.path.read_bytes() == b"ann's" and bob.path.read_bytes() == b"bob's"
    # results name a path RELATIVE to the output dir: no server layout leaks
    assert not ann.reported_path.startswith("/")
    assert str(tmp_path) not in ann.reported_path
    assert ann.download_url is not None
    assert ann.download_url.startswith("https://mcp.example.org/downloads/")
    token = ann.download_url.rsplit("/", 1)[1]
    assert output_store.resolve_download(settings, token) == ann.path.resolve()


def test_download_tokens_cannot_be_forged_or_reused_after_expiry(tmp_path: Path) -> None:
    settings = per_caller(output_dir=tmp_path)
    reset = as_caller("ann")
    try:
        stored = output_store.store(b"x", settings=settings, filename="a.pdf")
    finally:
        current_principal.reset(reset)
    token = stored.download_url.rsplit("/", 1)[1]  # type: ignore[union-attr]
    assert output_store.resolve_download(settings, token) is not None
    assert output_store.resolve_download(settings, token[:-2] + "AA") is None
    assert output_store.resolve_download(settings, "not-a-token") is None
    later = time.time() + settings.download_ttl_s + 5
    assert output_store.resolve_download(settings, token, now=later) is None
    # a token for a path outside the output dir is refused even if correctly signed
    outside = tmp_path.parent / "elsewhere.txt"
    outside.write_text("secret")
    evil = output_store.sign_download(settings, tmp_path / ".." / "elsewhere.txt", time.time() + 60)
    assert output_store.resolve_download(settings, evil) is None


def test_quota_and_expiry_per_caller(tmp_path: Path) -> None:
    settings = per_caller(output_dir=tmp_path, output_caller_quota_mb=1, output_ttl_s=60)
    reset = as_caller("ann")
    try:
        first = output_store.store(b"x" * 700_000, settings=settings, filename="a.bin")
        with pytest.raises(HaxcmsMcpError) as excinfo:
            output_store.store(b"y" * 700_000, settings=settings, filename="b.bin")
        assert excinfo.value.code is ErrorCode.RATE_LIMITED
        # once the first result expires it is pruned and frees the quota
        old = time.time() - 120
        os.utime(first.path, (old, old))
        output_store.store(b"y" * 700_000, settings=settings, filename="b.bin")
        assert not first.path.exists()
    finally:
        current_principal.reset(reset)


def test_exports_in_per_caller_mode_report_links(tmp_path: Path) -> None:
    settings = per_caller(output_dir=tmp_path)
    reset = as_caller("ann")
    try:
        artifact = export_output.write_export(
            b"PK", settings=settings, site="demo", name="demo.zip", mimetype="z", format="zip"
        )
    finally:
        current_principal.reset(reset)
    assert artifact.download_url is not None and artifact.expires_at is not None
    assert not artifact.path.is_absolute()


def test_writing_results_needs_a_caller_in_per_caller_mode(tmp_path: Path) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        output_store.store(b"x", settings=per_caller(output_dir=tmp_path), filename="a")
    assert excinfo.value.code is ErrorCode.AUTH_REQUIRED


# --- guarded fetch limits / redaction ------------------------------------------------------


async def test_guarded_fetch_has_a_total_deadline() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, content=b"late")

    async def resolve(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    with pytest.raises(HaxcmsMcpError, match="longer than"):
        await ssrf.guarded_fetch(
            "https://slow.example/x",
            timeout_s=60,
            check_size=lambda n: None,
            resolve=resolve,
            transport=httpx.MockTransport(slow),
            deadline_s=0.2,
        )


async def test_refusals_never_reveal_resolved_addresses() -> None:
    async def resolve(host: str, port: int) -> list[str]:
        return ["10.20.30.40"]

    with pytest.raises(HaxcmsMcpError) as excinfo:
        await ssrf.validate_url("https://intranet.example/x", resolve=resolve)
    assert "10.20.30.40" not in excinfo.value.formatted
    assert "non-public" in excinfo.value.message


async def test_connection_errors_do_not_name_the_internal_host() -> None:
    settings = Settings(base_url="http://haxcms.internal.corp:3000", retry_max=0)
    async with HaxcmsClient(settings) as client:
        with respx.mock(base_url="http://haxcms.internal.corp:3000") as router:
            router.post("/system/api/v1/session/login").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(HaxcmsMcpError) as excinfo:
                await client.request("POST", client.sys("session/login"), auth="none")
    assert "internal.corp" not in excinfo.value.formatted
