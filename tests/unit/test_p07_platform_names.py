"""Platform ids for `create_site_from_platform` track the HAXcms siteImport dispatcher."""

from __future__ import annotations

import pytest

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.imports import PLATFORMS, _validate_platform

pytestmark = pytest.mark.unit


def test_platform_list_matches_the_current_dispatcher() -> None:
    # haxcms-nodejs siteImport.js: drupal (was drupal-book) and quarto are current
    assert "drupal" in PLATFORMS
    assert "quarto" in PLATFORMS
    assert "drupal-book" not in PLATFORMS


@pytest.mark.parametrize("platform", ["drupal", "Drupal ", "quarto", "vitepress"])
def test_current_platforms_validate(platform: str) -> None:
    assert _validate_platform(platform) == platform.strip().lower()


def test_old_drupal_book_name_maps_to_drupal() -> None:
    assert _validate_platform("drupal-book") == "drupal"
    assert _validate_platform(" Drupal-Book ") == "drupal"


def test_unknown_platform_lists_supported_ones() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        _validate_platform("myspace")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert excinfo.value.hint is not None
    assert "drupal" in excinfo.value.hint
    assert "quarto" in excinfo.value.hint
