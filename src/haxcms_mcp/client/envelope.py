"""Response envelope handling and error mapping (PLAN §2.3, API-REF §1).

Every HAXcms JSON response is `{status, data}`; errors carry `data.message` — except the
Phase 7 import/converter routes, which live-probe as `data.error`. `unwrap` returns
`data`, `unwrap_full` keeps top-level extras (`jwt`, `link`, `id`, `slug`). Non-2xx responses map
to `HaxcmsMcpError` with the exact upstream message preserved.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

# Exact upstream messages (API-REF §1/§2; verified live in Phase 0/1).
MSG_INVALID_CREDENTIALS = "Invalid username or password"
MSG_INVALID_BEARER = "Invalid bearer token"
MSG_AUTH_REQUIRED = "Authentication required"
MSG_SITE_TOKEN_REQUIRED = "X-HAXCMS-Site-Token header is required for this endpoint"
MSG_USER_TOKEN_REQUIRED = "X-HAXCMS-User-Token header is required for this endpoint"
MSG_TOO_MANY_LOGINS = "Too many failed login attempts"
# The feature-gate 403 tail. Upstream varies the verb — "Manifest editing IS disabled for
# this site", "Platform settings ARE disabled for this site", "Outline operations ARE ...",
# "Uploading media IS ...", "File operations ARE ..." — so match the shared tail (PLAN L220).
MSG_DISABLED_FOR_SITE = "disabled for this site"
MSG_FAILED_TO_WRITE = "failed to write"
MSG_SITE_NOT_FOUND = "Site not found"

_TOKEN_MESSAGE_FRAGMENTS = (
    MSG_INVALID_BEARER,
    "X-HAXCMS-Site-Token",
    "X-HAXCMS-User-Token",
    "Site Token",
    "User Token",
)


def response_message(response: httpx.Response) -> str:
    """Best-effort extraction of the upstream `data.message`/`data.error` (or raw text)."""
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return response.text.strip()[:500]
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            return str(data["message"])
        # Phase 7 live probe: every import/converter 400 carries its message here
        # (e.g. 'Unsupported import platform "foo"', "No file uploaded", SSRF refusals).
        if isinstance(data, dict) and isinstance(data.get("error"), str):
            return str(data["error"])
        if isinstance(data, str):
            return data
        if isinstance(body.get("message"), str):
            return str(body["message"])
    return response.text.strip()[:500] or f"HTTP {response.status_code}"


def is_invalid_bearer(response: httpx.Response) -> bool:
    """True for the 403 that should trigger one reactive refresh (API-REF §2.2)."""
    return response.status_code == 403 and MSG_INVALID_BEARER in response_message(response)


def _details(response: httpx.Response) -> dict[str, Any]:
    details: dict[str, Any] = {
        "status_code": response.status_code,
        "path": response.request.url.path if response.request else None,
    }
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        details["retry_after_s"] = retry_after
    return details


def error_from_response(response: httpx.Response) -> HaxcmsMcpError:
    """Map a non-2xx response to the HaxcmsMcpError the Agent should see."""
    status = response.status_code
    message = response_message(response)
    details = _details(response)

    if status == 401:
        if MSG_INVALID_CREDENTIALS in message:
            return HaxcmsMcpError(
                ErrorCode.AUTH_FAILED,
                message,
                hint=(
                    "check HAXCMS_MCP_USERNAME/HAXCMS_MCP_PASSWORD "
                    "or call login with valid credentials"
                ),
                details=details,
            )
        return HaxcmsMcpError(
            ErrorCode.AUTH_REQUIRED,
            message or MSG_AUTH_REQUIRED,
            hint="call the login tool (or set HAXCMS_MCP_USERNAME/HAXCMS_MCP_PASSWORD)",
            details=details,
        )

    if status == 403:
        if MSG_DISABLED_FOR_SITE in message:
            return HaxcmsMcpError(
                ErrorCode.FEATURE_DISABLED,
                message,
                hint="the feature is disabled for this site; see the site's platform settings",
                details=details,
            )
        return HaxcmsMcpError(
            ErrorCode.AUTH_FAILED,
            message,
            hint="the access or request token was refused; re-login may be required",
            details=details,
        )

    if status == 404:
        return HaxcmsMcpError(
            ErrorCode.NOT_FOUND,
            message or MSG_SITE_NOT_FOUND,
            hint="check the site name or item id (list_sites / list_pages)",
            details=details,
        )

    if status == 400:
        return HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            message or "invalid request",
            details=details,
        )

    if status == 422:
        # PLAN T7.3: some remote platform converters (openstax, plone) answer 422;
        # it is always an input problem the Agent can act on.
        return HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            message or "unprocessable request",
            details=details,
        )

    if status == 405:
        return HaxcmsMcpError(
            ErrorCode.UNSUPPORTED,
            message or f"method not allowed for {details['path']}",
            details=details,
        )

    if status == 429:
        hint = "retry after the indicated delay"
        if MSG_TOO_MANY_LOGINS in message:
            hint = "too many failed logins; wait out the Retry-After window before trying again"
        text = message or "too many requests"
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            # Surface the server's back-off window in the message itself (ToolError text).
            text = f"{text} (retry after {retry_after}s)"
        return HaxcmsMcpError(
            ErrorCode.RATE_LIMITED,
            text,
            hint=hint,
            details=details,
        )

    if status >= 500:
        return HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            message or f"HAXcms returned HTTP {status}",
            hint="the HAXcms instance failed to handle the request; check its logs",
            details=details,
        )

    return HaxcmsMcpError(
        ErrorCode.UPSTREAM_ERROR,
        message or f"unexpected HTTP {status}",
        details=details,
    )


def unwrap_full(response: httpx.Response) -> dict[str, Any]:
    """Return the whole JSON body, preserving top-level extras (jwt, link, id, slug)."""
    if response.status_code >= 400:
        raise error_from_response(response)
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            f"expected JSON from {response.request.url.path}, got: {response.text[:200]!r}",
        ) from exc
    if not isinstance(body, dict):
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            f"expected a JSON object from {response.request.url.path}",
        )
    return body


def unwrap(response: httpx.Response) -> Any:
    """Return `data` from the `{status, data}` envelope; raise the mapped error on non-2xx."""
    body = unwrap_full(response)
    if "data" in body:
        return body["data"]
    return body


def unwrap_dict(response: httpx.Response) -> dict[str, Any]:
    """Like `unwrap`, but guarantees a dict (UPSTREAM_ERROR when `data` is not an object)."""
    data = unwrap(response)
    if not isinstance(data, dict):
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            f"expected a JSON object in data from {response.request.url.path}",
        )
    return data


def unwrap_list(response: httpx.Response) -> list[Any]:
    """Like `unwrap`, but guarantees a list (UPSTREAM_ERROR when `data` is not an array)."""
    data = unwrap(response)
    if not isinstance(data, list):
        raise HaxcmsMcpError(
            ErrorCode.UPSTREAM_ERROR,
            f"expected a JSON array in data from {response.request.url.path}",
        )
    return data
