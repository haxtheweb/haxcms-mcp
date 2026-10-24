"""Unit tests for haxcms_mcp.errors (message format per PLAN Section 5)."""

from __future__ import annotations

import pytest

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

pytestmark = pytest.mark.unit


def test_all_codes_present() -> None:
    expected = {
        "AUTH_REQUIRED",
        "AUTH_FAILED",
        "READ_ONLY",
        "RATE_LIMITED",
        "NOT_FOUND",
        "INVALID_ARGUMENT",
        "ANCHOR_NOT_FOUND",
        "ANCHOR_AMBIGUOUS",
        "FEATURE_DISABLED",
        "UPSTREAM_ERROR",
        "UNSUPPORTED",
        "FILE_SOURCE_ERROR",
        "TIMEOUT",
    }
    assert {c.value for c in ErrorCode} == expected


def test_message_format_without_hint() -> None:
    err = HaxcmsMcpError(ErrorCode.NOT_FOUND, "page 'x' does not exist")
    assert err.formatted == "[NOT_FOUND] page 'x' does not exist"
    assert str(err) == err.formatted


def test_message_format_with_hint() -> None:
    err = HaxcmsMcpError(
        ErrorCode.INVALID_ARGUMENT,
        "bad site name",
        hint="names cannot contain spaces; use - or _",
    )
    assert str(err) == "[INVALID_ARGUMENT] bad site name. names cannot contain spaces; use - or _"


def test_code_coerced_from_string() -> None:
    err = HaxcmsMcpError("RATE_LIMITED", "slow down")
    assert err.code is ErrorCode.RATE_LIMITED


def test_unknown_code_rejected() -> None:
    with pytest.raises(ValueError):
        HaxcmsMcpError("NOPE", "x")


def test_details_preserved() -> None:
    details = {"matches": [1, 2, 3]}
    err = HaxcmsMcpError(ErrorCode.ANCHOR_AMBIGUOUS, "several matches", details=details)
    assert err.details == details


def test_is_exception() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        raise HaxcmsMcpError(ErrorCode.AUTH_REQUIRED, "login needed", hint="call login")
    assert excinfo.value.hint == "call login"
