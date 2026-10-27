"""#3140: per-caller sessions in authenticated HTTP mode (client routing + token verifier)."""

from __future__ import annotations

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.client.principal import Principal, current_principal
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.http_auth import HaxcmsTokenVerifier

pytestmark = pytest.mark.unit

BASE = "http://haxcms.invalid"
SETTINGS_JS = 'window.appSettings = {"userToken": "%s"};'


def per_caller_settings(**kwargs: object) -> Settings:
    return Settings(
        base_url=BASE,
        transport="http",
        http_auth="haxcms",
        username="envuser",  # must never be used in this mode
        password="envpass",
        **kwargs,  # type: ignore[arg-type]
    )


async def test_without_a_caller_nothing_authenticates_and_env_creds_are_unused() -> None:
    async with HaxcmsClient(per_caller_settings()) as client:
        with respx.mock(base_url=BASE, assert_all_called=False) as router:
            login = router.post("/system/api/v1/session/login")
            with pytest.raises(HaxcmsMcpError) as excinfo:
                await client.auth.ensure_access()
        assert excinfo.value.code is ErrorCode.AUTH_REQUIRED
        assert not login.called


async def test_each_caller_gets_its_own_session_and_request_tokens() -> None:
    async with HaxcmsClient(per_caller_settings()) as client:
        with respx.mock(base_url=BASE) as router:

            def connection_settings(request: httpx.Request) -> httpx.Response:
                bearer = request.headers.get("authorization", "")
                return httpx.Response(200, text=SETTINGS_JS % f"ut-for-{bearer[-5:]}")

            router.get("/system/api/v1/session/connection-settings").mock(
                side_effect=connection_settings
            )
            sites = router.get("/system/api/v1/sites").mock(
                return_value=httpx.Response(200, json={"status": 200, "data": []})
            )

            seen: dict[str, tuple[str, str]] = {}
            for token in ("token-AAAAA", "token-BBBBB"):
                reset = current_principal.set(Principal(token, "someone"))
                try:
                    await client.request("GET", client.sys("sites"), auth="bearer+user")
                    seen[token] = (
                        sites.calls.last.request.headers["authorization"],
                        sites.calls.last.request.headers["x-haxcms-user-token"],
                    )
                    assert client.auth.username == "someone"
                finally:
                    current_principal.reset(reset)

        assert seen["token-AAAAA"] == ("Bearer token-AAAAA", "ut-for-AAAAA")
        assert seen["token-BBBBB"] == ("Bearer token-BBBBB", "ut-for-BBBBB")
        # two sessions, two cookie jars, and the process-wide one untouched
        assert len(client._sessions) == 2
        assert client.auth.access_token is None


async def test_a_refused_caller_token_is_auth_failed_not_a_login() -> None:
    async with HaxcmsClient(per_caller_settings()) as client:
        with respx.mock(base_url=BASE, assert_all_called=False) as router:
            router.get("/system/api/v1/sites").mock(
                return_value=httpx.Response(
                    403, json={"status": 403, "data": {"message": "Invalid bearer token"}}
                )
            )
            login = router.post("/system/api/v1/session/login")
            refresh = router.get("/system/api/v1/session/refresh")
            reset = current_principal.set(Principal("expired-token"))
            try:
                with pytest.raises(HaxcmsMcpError) as excinfo:
                    await client.request("GET", client.sys("sites"))
            finally:
                current_principal.reset(reset)
        assert excinfo.value.code is ErrorCode.AUTH_FAILED
        assert not login.called and not refresh.called


async def test_stdio_mode_ignores_any_principal() -> None:
    async with HaxcmsClient(Settings(base_url=BASE, username="u", password="p")) as client:
        reset = current_principal.set(Principal("someone-elses-token"))
        try:
            assert client.auth is client._default_auth
        finally:
            current_principal.reset(reset)


async def test_sessions_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import haxcms_mcp.client as client_module

    monkeypatch.setattr(client_module, "MAX_CALLER_SESSIONS", 3)
    async with HaxcmsClient(per_caller_settings()) as client:
        for n in range(5):
            reset = current_principal.set(Principal(f"t{n}"))
            try:
                _ = client.auth
            finally:
                current_principal.reset(reset)
        assert len(client._sessions) == 3


# --- token verifier ----------------------------------------------------------------------


async def test_verifier_accepts_what_haxcms_accepts_and_caches_it() -> None:
    async with HaxcmsClient(per_caller_settings()) as client:
        verifier = HaxcmsTokenVerifier(client)
        with respx.mock(base_url=BASE) as router:
            route = router.get("/system/api/v1/session").mock(
                return_value=httpx.Response(
                    200, json={"status": 200, "authenticated": True, "user": "alice"}
                )
            )
            first = await verifier.verify_token("good-token")
            second = await verifier.verify_token("good-token")
        assert first is not None and second is not None
        assert first.client_id == "alice"
        assert first.claims["user"] == "alice"
        assert route.call_count == 1
        assert route.calls.last.request.headers["authorization"] == "Bearer good-token"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"status": 401, "authenticated": False}),
        httpx.Response(200, json={"status": 200, "authenticated": False}),
        httpx.Response(200, json={"status": 200, "authenticated": True, "user": ""}),
        httpx.Response(200, text="not json"),
    ],
)
async def test_verifier_rejects_everything_else(response: httpx.Response) -> None:
    async with HaxcmsClient(per_caller_settings()) as client:
        verifier = HaxcmsTokenVerifier(client)
        with respx.mock(base_url=BASE) as router:
            router.get("/system/api/v1/session").mock(return_value=response)
            assert await verifier.verify_token("bad-token") is None


async def test_verifier_treats_an_unreachable_instance_as_unverified() -> None:
    async with HaxcmsClient(per_caller_settings()) as client:
        verifier = HaxcmsTokenVerifier(client)
        with respx.mock(base_url=BASE) as router:
            router.get("/system/api/v1/session").mock(side_effect=httpx.ConnectError("down"))
            assert await verifier.verify_token("any") is None
