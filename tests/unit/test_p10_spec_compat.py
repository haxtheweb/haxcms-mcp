"""Startup spec-compatibility check (#3137): vendored spec identity vs the live instance."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
import respx

from haxcms_mcp.client import HaxcmsClient, retry
from haxcms_mcp.compat import CompatChecker, check_spec_compatibility
from haxcms_mcp.config import Settings
from haxcms_mcp.generated import spec_info
from haxcms_mcp.spec_hash import spec_sha256

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"
OPENAPI_URL = f"{BASE}/system/api/v1/openapi"
SPECS = Path(__file__).resolve().parents[2] / "specs"


@pytest.fixture(autouse=True)
def no_transient_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """GETs retry connection errors on a 0.5/1/2 s schedule; keep the tests instant."""
    monkeypatch.setattr(retry, "BACKOFF_SCHEDULE_S", ())


def make_client() -> HaxcmsClient:
    return HaxcmsClient(Settings(base_url=BASE, no_auth=True))  # type: ignore[call-arg]


def test_generated_spec_info_matches_the_vendored_specs() -> None:
    """Drift guard: regenerate with scripts/sync_specs.py after touching specs/."""
    assert spec_sha256((SPECS / "system-spec.yaml").read_bytes()) == spec_info.SYSTEM_SPEC_SHA256
    assert spec_sha256((SPECS / "site-spec.yaml").read_bytes()) == spec_info.SITE_SPEC_SHA256
    assert (SPECS / "VERSION").read_text().strip() == (
        f"{spec_info.HAXCMS_VERSION} {spec_info.HAXCMS_COMMIT}"
    )


def test_hash_ignores_line_endings() -> None:
    assert spec_sha256(b"a: 1\r\nb: 2\r\n") == spec_sha256(b"a: 1\nb: 2\n")


@respx.mock
async def test_matching_spec_is_reported_as_match() -> None:
    respx.get(OPENAPI_URL).mock(
        return_value=httpx.Response(200, content=(SPECS / "system-spec.yaml").read_bytes())
    )
    result = await check_spec_compatibility(make_client())
    assert result.status == "match"
    assert result.actual_sha256 == spec_info.SYSTEM_SPEC_SHA256
    assert result.detail is None


@respx.mock
async def test_different_spec_is_reported_as_mismatch_with_both_hashes() -> None:
    respx.get(OPENAPI_URL).mock(return_value=httpx.Response(200, text="openapi: 3.0.3\n"))
    result = await check_spec_compatibility(make_client())
    assert result.status == "mismatch"
    assert result.expected_sha256 == spec_info.SYSTEM_SPEC_SHA256
    assert result.actual_sha256 == spec_sha256(b"openapi: 3.0.3\n")
    assert result.vendored_ref == f"HAXcms NodeJS {spec_info.HAXCMS_VERSION} @ " + (
        spec_info.HAXCMS_COMMIT
    )
    assert "different system OpenAPI spec" in (result.detail or "")


@respx.mock
@pytest.mark.parametrize("failure", ["http_404", "connection_refused"])
async def test_unreachable_or_erroring_instance_is_unavailable_not_an_error(failure: str) -> None:
    if failure == "http_404":
        respx.get(OPENAPI_URL).mock(return_value=httpx.Response(404, text="nope"))
    else:
        respx.get(OPENAPI_URL).mock(side_effect=httpx.ConnectError("refused"))
    result = await check_spec_compatibility(make_client())
    assert result.status == "unavailable"
    assert result.actual_sha256 is None
    assert result.detail


@respx.mock
async def test_checker_runs_once_and_warns_on_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    route = respx.get(OPENAPI_URL).mock(return_value=httpx.Response(200, text="openapi: 3.0.3\n"))
    checker = CompatChecker(make_client())
    with caplog.at_level(logging.WARNING, logger="haxcms_mcp"):
        first = await checker.result()
        second = await checker.result()
    assert first == second
    assert route.call_count == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "spec mismatch" in warnings[0].getMessage()


@respx.mock
async def test_checker_retries_while_the_instance_is_unavailable() -> None:
    route = respx.get(OPENAPI_URL).mock(side_effect=httpx.ConnectError("refused"))
    checker = CompatChecker(make_client())
    assert (await checker.result()).status == "unavailable"
    route.mock(return_value=httpx.Response(200, content=(SPECS / "system-spec.yaml").read_bytes()))
    assert (await checker.result()).status == "match"
    assert route.call_count == 2


async def test_a_closed_client_is_unavailable_not_a_crash() -> None:
    """Regression: get_server_info after the lifespan closed the httpx client must not raise."""
    client = make_client()
    await client.aclose()
    result = await check_spec_compatibility(client)
    assert result.status == "unavailable"
    assert "closed" in (result.detail or "")


def test_hash_is_the_same_for_the_php_json_rendering_of_the_vendored_spec() -> None:
    """#3139: HAXcms PHP serves the system spec as JSON, with the instance's version and
    servers filled in and empty objects encoded as `[]`; it must hash like the YAML."""
    import json

    import yaml

    document = yaml.safe_load((SPECS / "system-spec.yaml").read_text(encoding="utf-8"))
    document["info"]["version"] = "99.0.0"
    document["servers"] = [{"url": "http://127.0.0.1:9/", "description": "instance"}]
    php_style = json.dumps(document, indent=4).replace("{}", "[]").encode("utf-8")
    assert spec_sha256(php_style) == spec_info.SYSTEM_SPEC_SHA256


def test_hash_still_detects_a_real_contract_change() -> None:
    import yaml

    document = yaml.safe_load((SPECS / "system-spec.yaml").read_text(encoding="utf-8"))
    document["paths"].pop(next(iter(document["paths"])))
    changed = yaml.safe_dump(document).encode("utf-8")
    assert spec_sha256(changed) != spec_info.SYSTEM_SPEC_SHA256


def test_prose_differences_do_not_count_but_a_property_named_description_does() -> None:
    """Descriptions/summaries are documentation: two backends whose prose differs serve the
    same contract. A schema property literally called `description` IS contract."""
    import yaml

    document = yaml.safe_load((SPECS / "system-spec.yaml").read_text(encoding="utf-8"))
    document["info"]["description"] = "reworded"
    first_path = next(iter(document["paths"].values()))
    next(iter(first_path.values()))["summary"] = "also reworded"
    assert spec_sha256(yaml.safe_dump(document).encode()) == spec_info.SYSTEM_SPEC_SHA256

    schemas = document["components"]["schemas"]
    schemas["ProbeOnly"] = {"type": "object", "properties": {"description": {"type": "string"}}}
    with_prop = spec_sha256(yaml.safe_dump(document).encode())
    del schemas["ProbeOnly"]["properties"]["description"]
    assert spec_sha256(yaml.safe_dump(document).encode()) != with_prop
