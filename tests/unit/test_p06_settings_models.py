"""Unit tests for the Phase 6 settings models (PLAN T6.1).

Pure parsing tests over a hand-built site.json manifest: snake_case mapping (gaID -> ga_id,
homePageId -> home_page_id, socialLink -> social_link, autoPush -> auto_push, the 21 feature
flags), the lenient boolean mirror of parseBooleanFromInput, the regions map, allowedBlocks
null-vs-list, extras preservation, and empty-manifest defaults.
"""

from __future__ import annotations

from typing import Any

import pytest

from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.settings import PlatformFeatures, SiteSettings

pytestmark = pytest.mark.unit

MANIFEST: dict[str, Any] = {
    "id": "site-id-1",
    "title": "Demo Site",
    "description": "A demo",
    "license": "CC-BY-4.0",
    "metadata": {
        "site": {
            "name": "demo",
            "domain": "demo.example.com",
            "tags": ["one", "two"],
            "logo": "files/logo.png",
            "homePageId": "item-1",
            "updated": 1750000000,
            "settings": {
                "lang": "en",
                "gaID": "UA-1",
                "private": False,
                "canonical": True,
                "pathauto": True,
                "publishPagesOn": True,
                "sw": False,
                "forceUpgrade": False,
            },
            "git": {
                "vendor": "github",
                "branch": "main",
                "autoPush": True,
                "url": "git@example.invalid:demo.git",
            },
        },
        "theme": {
            "element": "learn-two-theme",
            "variables": {
                "cssVariable": "--simple-colors-default-theme-deep-purple-7",
                "palette": "learn",
                "icon": "account",
                "image": "files/banner.png",
                "imageAlt": "Banner",
                "imageLink": "https://example.invalid",
            },
            "regions": {"sidebarFirst": ["item-9"]},
        },
        "author": {
            "name": "Author Name",
            "email": "a@example.invalid",
            "image": "files/a.png",
            "phone": "555-0100",
            "location": "here",
            "website": "https://w1.invalid",
            "website2": "https://w2.invalid",
            "socialLink": "https://s1.invalid",
            "socialLink2": "https://s2.invalid",
        },
        "platform": {
            "audience": "expert",
            "allowedBlocks": ["a11y-gif-player", "image"],
            "features": {"addPage": True, "deletePage": False, "unknownFlag": True},
        },
    },
    "items": [{"id": "item-1", "title": "Home"}],
}


def test_from_manifest_maps_every_block() -> None:
    settings = SiteSettings.from_manifest(MANIFEST)
    assert settings.id == "site-id-1"
    assert settings.name == "demo"
    assert settings.title == "Demo Site"
    assert settings.description == "A demo"
    assert settings.license == "CC-BY-4.0"
    assert settings.domain == "demo.example.com"
    assert settings.tags == ["one", "two"]
    assert settings.logo == "files/logo.png"
    assert settings.home_page_id == "item-1"
    assert settings.updated == 1750000000
    assert settings.sw is False
    assert settings.force_upgrade is False

    assert settings.theme is not None
    assert settings.theme.element == "learn-two-theme"
    assert settings.theme.css_variable == "--simple-colors-default-theme-deep-purple-7"
    assert settings.theme.palette == "learn"
    assert settings.theme.icon == "account"
    assert settings.theme.image == "files/banner.png"
    assert settings.theme.image_alt == "Banner"
    assert settings.theme.image_link == "https://example.invalid"
    assert settings.theme.regions == {"sidebarFirst": ["item-9"]}

    assert settings.seo is not None
    assert settings.seo.description == "A demo"
    assert settings.seo.domain == "demo.example.com"
    assert settings.seo.lang == "en"
    assert settings.seo.ga_id == "UA-1"
    assert settings.seo.private is False
    assert settings.seo.canonical is True
    assert settings.seo.pathauto is True
    assert settings.seo.publish_pages_on is True

    assert settings.author is not None
    assert settings.author.name == "Author Name"
    assert settings.author.email == "a@example.invalid"
    assert settings.author.social_link == "https://s1.invalid"
    assert settings.author.social_link2 == "https://s2.invalid"
    assert settings.author.website2 == "https://w2.invalid"

    assert settings.platform is not None
    assert settings.platform.audience == "expert"
    assert settings.platform.allowed_blocks == ["a11y-gif-player", "image"]
    assert settings.platform.features is not None
    assert settings.platform.features.add_page is True
    assert settings.platform.features.delete_page is False
    # unknown flags ride along as extras (extra="allow")
    assert settings.platform.features.model_extra == {"unknownFlag": True}

    assert settings.git is not None
    assert settings.git.vendor == "github"
    assert settings.git.branch == "main"
    assert settings.git.auto_push is True
    assert settings.git.url == "git@example.invalid:demo.git"

    # the huge `items` outline never lands in extras
    extras = settings.model_extra or {}
    assert "items" not in extras
    assert "metadata" not in extras


def test_dump_model_is_snake_case_and_drops_nones() -> None:
    dumped = dump_model(SiteSettings.from_manifest(MANIFEST))
    assert dumped["home_page_id"] == "item-1"
    assert dumped["seo"]["ga_id"] == "UA-1"
    assert dumped["platform"]["features"]["delete_page"] is False
    assert dumped["git"]["auto_push"] is True
    assert "warnings" not in dumped  # exclude_none


def test_lenient_boolean_parsing() -> None:
    manifest = {
        "metadata": {
            "site": {
                "name": "demo",
                "settings": {"private": "yes", "canonical": 0, "pathauto": "OFF", "sw": 1},
            }
        }
    }
    seo = SiteSettings.from_manifest(manifest).seo
    assert seo is not None
    assert seo.private is True
    assert seo.canonical is False
    assert seo.pathauto is False
    settings = SiteSettings.from_manifest(manifest)
    assert settings.sw is True


def test_empty_manifest_defaults() -> None:
    settings = SiteSettings.from_manifest({"title": "x"})
    assert settings.name == ""
    assert settings.title == "x"
    assert settings.theme is None
    assert settings.author is None
    assert settings.platform is None
    assert settings.git is None
    assert settings.tags is None
    # the seo block is always built (it mirrors manifest-level fields)
    assert settings.seo is not None
    assert settings.seo.description is None


def test_allowed_blocks_null_is_unrestricted() -> None:
    platform = SiteSettings.from_manifest(
        {"metadata": {"platform": {"allowedBlocks": None, "features": {}}}}
    ).platform
    assert platform is not None
    assert platform.allowed_blocks is None
    assert isinstance(platform.features, PlatformFeatures)
    assert platform.features.add_page is None


def test_top_level_author_string_does_not_collide_with_author_view() -> None:
    """Live-probed fresh site.json shape: the JSON Outline Schema top-level `author` is
    "" — it must not collide with the parsed metadata.author view (integration caught
    `TypeError: multiple values for keyword argument 'author'`). Harmless top-level
    extras like `location` are preserved."""
    manifest = {
        "author": "",
        "location": "pages",
        "title": "Demo",
        "metadata": {
            "site": {"name": "demo", "git": {"vendor": "github", "branch": "gh-pages"}},
            "author": {"name": "Ada"},
            "platform": {"audience": "expert", "features": {}, "allowedBlocks": []},
        },
    }
    settings = SiteSettings.from_manifest(manifest)
    assert settings.author is not None
    assert settings.author.name == "Ada"  # metadata.author wins the view
    extras = settings.model_extra or {}
    assert "author" not in extras  # collides with the declared field -> never an extra
    assert extras.get("location") == "pages"
    assert settings.git is not None and settings.git.branch == "gh-pages"
    assert settings.platform is not None and settings.platform.allowed_blocks == []
