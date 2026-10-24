"""Unit tests for the site machine-name validation (PLAN Phase 2 T2.6)."""

from __future__ import annotations

import pytest

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.sites import validate_site_name

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "name",
    [
        "first-underscore-course",
        "site",
        "site-1",
        "site_1",
        "9lives",
        "a-b_c-9",
        "clean-one-blog-skeleton",
    ],
)
def test_valid_names_pass_through(name: str) -> None:
    assert validate_site_name(name) == name


def test_surrounding_whitespace_is_trimmed() -> None:
    assert validate_site_name("  site-1  ") == "site-1"


@pytest.mark.parametrize(
    "name",
    [
        "First",  # uppercase (Appendix D: the tutorial's first attempt fails)
        "my course",  # inner space
        "First Course",
        "site!",
        "site.name",
        "site/name",
        "site\\name",
        "ünïcode",
        "site:name",
        "site name-",
    ],
)
def test_invalid_names_raise_invalid_argument(name: str) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        validate_site_name(name)
    error = excinfo.value
    assert error.code is ErrorCode.INVALID_ARGUMENT
    assert error.message.startswith("invalid site name")
    # the offending name is quoted with repr() (backslashes get escaped there)
    assert repr(name) in error.message


@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_empty_names_raise_invalid_argument(name: str) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        validate_site_name(name)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


def test_hint_mentions_the_spaces_rule() -> None:
    """PLAN Appendix D: the failure must teach the machine-name rule."""
    with pytest.raises(HaxcmsMcpError) as excinfo:
        validate_site_name("First Course")
    hint = excinfo.value.hint or ""
    assert "cannot contain spaces" in hint
    assert "- or _" in hint
