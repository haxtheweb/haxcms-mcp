"""Golden unit tests for the Phase 6 settings payload builders (PLAN Phase 6 test list).

Pure assertions over the builder output: the scoped-manifest dash keys (the only reachable
PATCH-site path), the SHORT seo/author wrapper keys, the 14-key appearance theme block,
accent-color/palette normalization, region and feature validation, and the platform
merge-over-replace helper. The wire bodies these builders feed are asserted in
test_p06_settings_service.py (respx).
"""

from __future__ import annotations

import pytest

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services.settings import (
    VALID_FEATURE_KEYS,
    VALID_REGIONS,
    build_appearance_theme,
    build_author_fields,
    build_scoped_manifest_payload,
    build_seo_fields,
    merge_platform_features,
    normalize_accent_color,
    normalize_palette,
    validate_features,
    validate_region,
)

pytestmark = pytest.mark.unit


# --- scoped manifest payload ---------------------------------------------------------------


def test_scoped_manifest_title_only() -> None:
    assert build_scoped_manifest_payload("demo", title="New Title") == {
        "site": {"name": "demo"},
        "manifest": {"site": {"manifest-title": "New Title"}},
    }


def test_scoped_manifest_home_page_only_including_clear() -> None:
    assert build_scoped_manifest_payload("demo", home_page_id="item-9") == {
        "site": {"name": "demo"},
        "manifest": {"site": {"manifest-metadata-site-homePageId": "item-9"}},
    }
    # "" is the clear signal (the server deletes the key on an invalid/empty id)
    cleared = build_scoped_manifest_payload("demo", home_page_id="")
    assert cleared["manifest"]["site"]["manifest-metadata-site-homePageId"] == ""


def test_scoped_manifest_both_keys_and_empty() -> None:
    both = build_scoped_manifest_payload("demo", title="T", home_page_id="item-1")
    assert both["manifest"]["site"] == {
        "manifest-title": "T",
        "manifest-metadata-site-homePageId": "item-1",
    }
    # no fields: the manifest object must still exist (scoped detection requires it)
    empty = build_scoped_manifest_payload("demo")
    assert empty == {"site": {"name": "demo"}, "manifest": {"site": {}}}


# --- seo / author wrappers -----------------------------------------------------------------


def test_seo_fields_golden() -> None:
    fields = build_seo_fields(
        description="D",
        domain="demo.example.com",
        logo="files/logo.png",
        lang="es",
        ga_id="UA-9",
        private=True,
        canonical=False,
        pathauto=True,
        publish_pages_on=False,
    )
    assert fields == {
        "description": "D",
        "domain": "demo.example.com",
        "logo": "files/logo.png",
        "lang": "es",
        "gaID": "UA-9",
        "private": True,
        "canonical": False,
        "pathauto": True,
        "publishPagesOn": False,
    }


def test_seo_fields_only_present_keys() -> None:
    assert build_seo_fields(lang="fr") == {"lang": "fr"}
    assert build_seo_fields() == {}


def test_author_fields_golden() -> None:
    fields = build_author_fields(
        license="by-nc",
        name="A",
        email="a@example.invalid",
        image="files/a.png",
        phone="555-0100",
        location="here",
        website="https://w.invalid",
        social_link="https://s.invalid",
    )
    assert fields == {
        "license": "by-nc",
        "name": "A",
        "email": "a@example.invalid",
        "image": "files/a.png",
        "phone": "555-0100",
        "location": "here",
        "website": "https://w.invalid",
        "socialLink": "https://s.invalid",
    }
    assert build_author_fields(name="A") == {"name": "A"}


# --- appearance theme block -----------------------------------------------------------------


def test_appearance_theme_golden() -> None:
    theme = build_appearance_theme(
        element="learn-two-theme",
        palette="learn",
        accent_color="deep-purple",
        icon="account",
        banner_image="files/b.png",
        banner_alt="Banner",
        banner_link="https://l.invalid",
    )
    assert theme == {
        "manifest-metadata-theme-element": "learn-two-theme",
        "manifest-metadata-theme-variables-palette": "learn",
        "manifest-metadata-theme-variables-cssVariable": "deep-purple",
        "manifest-metadata-theme-variables-icon": "account",
        "manifest-metadata-theme-variables-image": "files/b.png",
        "manifest-metadata-theme-variables-imageAlt": "Banner",
        "manifest-metadata-theme-variables-imageLink": "https://l.invalid",
    }


def test_appearance_theme_region_key() -> None:
    theme = build_appearance_theme(region="sidebarFirst", region_page_ids=["item-9", "item-1"])
    assert theme == {"manifest-metadata-theme-regions-sidebarFirst": ["item-9", "item-1"]}
    # an empty list clears the region
    assert build_appearance_theme(region="header", region_page_ids=[]) == {
        "manifest-metadata-theme-regions-header": []
    }


def test_appearance_theme_only_present_keys() -> None:
    assert build_appearance_theme(icon="apps") == {"manifest-metadata-theme-variables-icon": "apps"}
    assert build_appearance_theme() == {}


# --- normalizers / validators ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("deep-purple", "deep-purple"),
        (" Deep-Purple ", "deep-purple"),
        ("--simple-colors-default-theme-deep-purple-7", "deep-purple"),
        ("--simple-colors-default-theme-DEEP-PURPLE-7", "deep-purple"),
        ("--simple-colors-default-theme-blue-8", "blue-8"),  # only the -7 suffix strips
    ],
)
def test_normalize_accent_color(value: str, expected: str) -> None:
    assert normalize_accent_color(value) == expected


@pytest.mark.parametrize("value", ["", "  ", "bad color", "--simple-colors-default-theme--7", "a!"])
def test_normalize_accent_color_rejects(value: str) -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        normalize_accent_color(value)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "accent color" in excinfo.value.message


def test_normalize_palette() -> None:
    assert normalize_palette(" Learn ") == "learn"
    assert normalize_palette("") == ""  # empty deletes the key server-side
    with pytest.raises(HaxcmsMcpError) as excinfo:
        normalize_palette("bad palette!")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


def test_validate_region() -> None:
    for region in VALID_REGIONS:
        assert validate_region(region) == region
    for bad in ("sidebar-first", "SidebarFirst", "footer", ""):
        with pytest.raises(HaxcmsMcpError) as excinfo:
            validate_region(bad)
        assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
        assert "sidebarFirst" in (excinfo.value.hint or "")


def test_validate_features_accepts_canonical_keys() -> None:
    features = {"deletePage": False, "addPage": True}
    assert validate_features(features) == features
    assert len(VALID_FEATURE_KEYS) == 21


def test_validate_features_rejections() -> None:
    with pytest.raises(HaxcmsMcpError) as excinfo:
        validate_features({})
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    with pytest.raises(HaxcmsMcpError) as excinfo:
        validate_features({"manifest": True})  # legacy alias, not a canonical key
    assert "unknown platform feature" in excinfo.value.message
    with pytest.raises(HaxcmsMcpError) as excinfo:
        validate_features({"addPage": "yes"})  # type: ignore[dict-item]
    assert "booleans" in excinfo.value.message


# --- platform merge --------------------------------------------------------------------------


def test_merge_platform_features() -> None:
    current = {"addPage": True, "deletePage": True, "legacy": "yes", "broken": None}
    merged = merge_platform_features(current, {"deletePage": False})
    # requested wins; current booleans pass through; non-booleans drop (strict route)
    assert merged == {"addPage": True, "deletePage": False}


def test_merge_platform_features_empty_current() -> None:
    assert merge_platform_features({}, {"insights": True}) == {"insights": True}
