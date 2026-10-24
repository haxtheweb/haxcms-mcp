"""Unit tests for the Phase 2 models: Theme, Skeleton, SiteDetail (PLAN T2.1)."""

from __future__ import annotations

import pytest

from haxcms_mcp.models.site import SiteDetail
from haxcms_mcp.models.skeleton import Skeleton, SkeletonMeta
from haxcms_mcp.models.theme import Theme

pytestmark = pytest.mark.unit

# live shapes captured by the Phase 2 probe (see PROGRESS.md verified facts)
SYSTEM_THEME_RECORD = {
    "element": "clean-one",
    "path": "@haxtheweb/clean-one/clean-one.js",
    "name": "Clean One",
    "thumbnail": "@haxtheweb/haxcms-elements/lib/theme-screenshots/theme-clean-one-thumb.jpg",
    "description": "Start with a blank site using the Clean One",
    "category": ["Course"],
    "hidden": False,
    "priority": -2,
    "terrible": False,
    "supportedPalettes": ["4", "5"],
    "machineName": "clean-one",
    "machine-name": "clean-one",
    "scope": "registry",
    "screenshot": "@haxtheweb/haxcms-elements/lib/theme-screenshots/theme-clean-one-thumb.jpg",
    "enabled": True,
}

SITE_THEME_RECORD = {
    "machineName": "clean-one",
    "name": "Clean One",
    "description": "Start with a blank site using the Clean One",
    "enabled": True,
    "active": True,
    "hidden": False,
    "screenshot": "thumb.jpg",
    "path": "@haxtheweb/clean-one/clean-one.js",
    "element": "clean-one",
    "links": {"self": "/_sites/demo/x/api/v1/themes/clean-one"},
    "supportedPalettes": ["4", "5"],
}

SKELETON_LIST_RECORD = {
    "title": "Online Course",
    "description": "Clean One themed online course skeleton",
    "image": "thumb.jpg",
    "priority": -2,
    "category": ["Course"],
    "attributes": [],
    "scope": "core",
    "machineName": "online-course-clean-one",
    "machine-name": "online-course-clean-one",
    "demo-url": "http://demo",
    "skeleton-url": "/system/api/v1/skeletons/online-course-clean-one",
    "enabled": True,
}

SKELETON_DETAIL_META = {
    "name": "online-course-clean-one",
    "description": "Clean One themed online course skeleton",
    "version": "1.0.0",
    "created": "2026-01-08T20:18:30Z",
    "type": "skeleton",
    "priority": -2,
    "useCaseTitle": "Online Course",
    "useCaseDescription": "An online course skeleton.",
    "useCaseImage": "thumb.jpg",
    "category": ["Course"],
    "tags": ["online", "lesson", "syllabus"],
    "attributes": [],
}

SITE_INFO = {
    "id": "site-id",
    "name": "demo",
    "title": "demo",
    "description": "A demo",
    "location": "//_sites/demo/",
    "metadata": {
        "pageCount": 5,
        "created": "2026-01-01T00:00:00.000Z",
        "updated": "2026-01-02T00:00:00.000Z",
    },
    "links": {"self": "/system/api/v1/sites/demo", "clone": "/system/api/v1/sites/demo/clone"},
}

SITE_SUMMARY = {
    "id": "site-id",
    "name": "demo",
    "title": "demo",
    "description": "A demo",
    "language": "en-US",
    "basePath": "/_sites/demo/",
    "theme": "clean-one",
    "updated": "2026-01-02T00:00:00.000Z",
    "counts": {"items": 5, "publishedItems": 4, "tags": 2, "regions": 0, "files": 1},
    "links": {"self": "/_sites/demo/x/api/v1/site"},
}


def test_theme_from_system_record() -> None:
    theme = Theme.from_api(SYSTEM_THEME_RECORD)
    assert theme.machine_name == "clean-one"
    assert theme.name == "Clean One"
    assert theme.category == ["Course"]
    assert theme.hidden is False
    assert theme.terrible is False
    assert theme.priority == -2
    assert theme.enabled is True
    assert theme.scope == "registry"
    assert theme.supported_palettes == ["4", "5"]
    assert theme.screenshot == SYSTEM_THEME_RECORD["screenshot"]


def test_theme_from_site_record() -> None:
    theme = Theme.from_api(SITE_THEME_RECORD)
    assert theme.machine_name == "clean-one"
    assert theme.active is True
    assert theme.enabled is True
    assert theme.scope is None  # site records do not carry it
    # `links` is consumed by from_api and dropped from extras
    assert theme.model_extra is not None and "links" not in theme.model_extra


def test_theme_machine_name_falls_back_to_machine_dash_name() -> None:
    theme = Theme.from_api({"machine-name": "only-dashes", "name": "Only Dashes"})
    assert theme.machine_name == "only-dashes"


def test_theme_category_string_is_normalised_to_list() -> None:
    theme = Theme.from_api({"machineName": "t", "category": "Website"})
    assert theme.category == ["Website"]


def test_skeleton_meta_from_list_record() -> None:
    meta = SkeletonMeta.from_api(SKELETON_LIST_RECORD)
    assert meta.machine_name == "online-course-clean-one"
    assert meta.name == "online-course-clean-one"  # falls back to the machine name
    assert meta.title == "Online Course"
    assert meta.category == ["Course"]
    assert meta.enabled is True
    assert meta.demo_url == "http://demo"
    assert meta.skeleton_url == "/system/api/v1/skeletons/online-course-clean-one"


def test_skeleton_meta_from_detail_meta() -> None:
    meta = SkeletonMeta.from_api(SKELETON_DETAIL_META)
    assert meta.machine_name == "online-course-clean-one"
    assert meta.name == "online-course-clean-one"
    assert meta.title == "Online Course"  # from useCaseTitle
    assert meta.use_case_title == "Online Course"
    assert meta.tags == ["online", "lesson", "syllabus"]
    assert meta.image == "thumb.jpg"  # from useCaseImage


def test_skeleton_from_detail() -> None:
    skeleton = Skeleton.from_api(
        {
            "meta": SKELETON_DETAIL_META,
            "site": {"name": "online-course-clean-one", "theme": "clean-one"},
            "build": {"type": "skeleton", "structure": "from-skeleton", "items": [{"id": "i1"}]},
        }
    )
    assert skeleton.meta.title == "Online Course"
    assert skeleton.site["theme"] == "clean-one"
    assert skeleton.build["items"] == [{"id": "i1"}]
    assert skeleton.theme is None


def test_skeleton_tolerates_missing_sections() -> None:
    skeleton = Skeleton.from_api({})
    assert skeleton.meta.machine_name == ""
    assert skeleton.site == {}
    assert skeleton.build == {}


def test_site_detail_merges_info_and_summary() -> None:
    detail = SiteDetail.from_api(SITE_INFO, SITE_SUMMARY)
    assert detail.name == "demo"
    assert detail.description == "A demo"
    assert detail.page_count == 5
    assert detail.counts is not None
    assert detail.counts.items == 5
    assert detail.counts.published_items == 4
    assert detail.counts.files == 1
    assert detail.theme == "clean-one"
    assert detail.language == "en-US"
    assert detail.created == "2026-01-01T00:00:00.000Z"
    assert detail.updated == "2026-01-02T00:00:00.000Z"
    assert detail.links is not None and "clone" in detail.links


def test_site_detail_without_summary() -> None:
    detail = SiteDetail.from_api(SITE_INFO, None)
    assert detail.name == "demo"
    assert detail.page_count == 5
    assert detail.counts is None
    assert detail.theme is None


def test_site_detail_dump_is_json_ready_and_drops_none() -> None:
    dumped = SiteDetail.from_api(SITE_INFO, None).model_dump(mode="json", exclude_none=True)
    assert dumped["name"] == "demo"
    assert "theme" not in dumped  # exclude_none drops unset optionals
    assert "counts" not in dumped
