"""Unit tests for envelope unwrapping and every error-mapping row (PLAN Phase 1 T1.3)."""

from __future__ import annotations

import httpx
import pytest

from haxcms_mcp.client.envelope import (
    error_from_response,
    is_invalid_bearer,
    unwrap,
    unwrap_full,
)
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

pytestmark = pytest.mark.unit

URL = "http://x.invalid/system/api/v1/sites"


def make(
    status: int,
    json_body: object | None = None,
    text: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    kwargs: dict = {
        "status_code": status,
        "headers": headers or {},
        "request": httpx.Request("GET", URL),
    }
    if json_body is not None:
        kwargs["json"] = json_body
    elif text is not None:
        kwargs["text"] = text
    return httpx.Response(**kwargs)


def err(message: str) -> dict:
    return {"status": 0, "data": {"message": message}}


def test_unwrap_returns_data() -> None:
    response = make(200, {"status": 200, "data": {"items": []}})
    assert unwrap(response) == {"items": []}


def test_unwrap_full_preserves_top_level_extras() -> None:
    response = make(200, {"status": 200, "jwt": "a.b.c"})
    body = unwrap_full(response)
    assert body["jwt"] == "a.b.c"


def test_unwrap_body_without_data_key() -> None:
    response = make(200, {"status": 200, "link": "/_published/x.zip"})
    assert unwrap(response) == {"status": 200, "link": "/_published/x.zip"}


def test_401_invalid_credentials_maps_to_auth_failed() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        unwrap(make(401, err("Invalid username or password")))
    assert excinfo.value.code is ErrorCode.AUTH_FAILED
    assert "Invalid username or password" in excinfo.value.message


def test_401_other_maps_to_auth_required() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        unwrap(make(401, err("Authentication required")))
    assert excinfo.value.code is ErrorCode.AUTH_REQUIRED


def test_403_invalid_bearer_maps_to_auth_failed_and_flags_refresh() -> None:
    response = make(403, err("Invalid bearer token"))
    assert is_invalid_bearer(response) is True
    error = error_from_response(response)
    assert error.code is ErrorCode.AUTH_FAILED


def test_403_missing_site_token_is_auth_failed_but_not_refreshable() -> None:
    response = make(403, err("X-HAXCMS-Site-Token header is required for this endpoint"))
    assert is_invalid_bearer(response) is False
    assert error_from_response(response).code is ErrorCode.AUTH_FAILED


def test_403_disabled_for_site_maps_to_feature_disabled() -> None:
    error = error_from_response(make(403, err("git is disabled for this site")))
    assert error.code is ErrorCode.FEATURE_DISABLED
    assert "is disabled for this site" in error.message


@pytest.mark.parametrize(
    "message",
    [
        # the settings/outline/files gates use the ARE form (Phase 6 source read):
        "Platform settings are disabled for this site",
        "Theme settings are disabled for this site",
        "SEO settings are disabled for this site",
        "Editor settings are disabled for this site",
        "Allowed blocks settings are disabled for this site",
        "Outline operations are disabled for this site",
        "File operations are disabled for this site",
        "Uploading media is disabled for this site",
        "Manifest editing is disabled for this site",
        "This operation is disabled for this site",  # featureDisabledResponse default
    ],
)
def test_403_are_disabled_variant_maps_to_feature_disabled(message: str) -> None:
    error = error_from_response(make(403, err(message)))
    assert error.code is ErrorCode.FEATURE_DISABLED
    assert error.message == message


def test_404_maps_to_not_found_with_exact_message() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        unwrap(make(404, err("Site not found")))
    assert excinfo.value.code is ErrorCode.NOT_FOUND
    assert excinfo.value.message == "Site not found"


def test_400_maps_to_invalid_argument_including_message() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        unwrap(make(400, err("Invalid theme supplied for site creation")))
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "Invalid theme supplied" in excinfo.value.message


def test_405_maps_to_unsupported() -> None:
    assert error_from_response(make(405, text="Method Not Allowed")).code is ErrorCode.UNSUPPORTED


def test_429_maps_to_rate_limited_with_retry_after() -> None:
    response = make(429, err("Too many failed login attempts"), headers={"Retry-After": "300"})
    error = error_from_response(response)
    assert error.code is ErrorCode.RATE_LIMITED
    assert error.details is not None
    assert error.details["retry_after_s"] == "300"
    assert "wait out the Retry-After" in (error.hint or "")


def test_500_failed_to_write_maps_to_upstream_error() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        unwrap(make(500, err("failed to write")))
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR
    assert "failed to write" in excinfo.value.message


def test_non_json_error_body_falls_back_to_text() -> None:
    error = error_from_response(make(502, text="<html>bad gateway</html>"))
    assert error.code is ErrorCode.UPSTREAM_ERROR
    assert "bad gateway" in error.message


def test_non_json_success_body_is_upstream_error() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        unwrap(make(200, text="not json"))
    assert excinfo.value.code is ErrorCode.UPSTREAM_ERROR


def test_details_include_status_and_path() -> None:
    error = error_from_response(make(404, err("Site not found")))
    assert error.details == {"status_code": 404, "path": "/system/api/v1/sites"}
