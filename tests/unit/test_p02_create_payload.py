"""Unit tests for the create-site payload builder (PLAN Phase 2 T2.6).

The exact blank and skeleton payloads are regression-goldened in
tests/regression/test_p02_snapshots.py; these tests assert the structural rules.
"""

from __future__ import annotations

import pytest

from haxcms_mcp.services.sites import build_create_payload, build_home_item

pytestmark = pytest.mark.unit


def test_blank_payload_defaults() -> None:
    payload = build_create_payload("demo", home_id="item-home-fixed")
    site = payload["site"]
    assert site == {
        "name": "demo",
        "description": "",
        "theme": "clean-one",
        "license": "by-sa",
        "domain": None,
    }
    build = payload["build"]
    assert build["type"] == "skeleton"
    assert build["structure"] == "from-skeleton"
    assert "skeletonMachineName" not in build
    assert len(build["items"]) == 1
    item = build["items"][0]
    assert item["id"] == "item-home-fixed"
    assert item["title"] == "Home"
    assert item["slug"] == "home"
    assert item["order"] == 0
    assert item["parent"] is None
    assert item["indent"] == 0
    assert item["content"] == "<p></p>"  # PLAN T2.3 default
    assert item["metadata"]["published"] is True


def test_blank_payload_custom_first_page_and_license() -> None:
    payload = build_create_payload(
        "demo",
        description="A course",
        theme="clean-portfolio",
        license="by-nc",
        first_page_title="Welcome",
        first_page_content="<p>Hello</p>",
        home_id="item-home-fixed",
    )
    site = payload["site"]
    assert site["description"] == "A course"
    assert site["theme"] == "clean-portfolio"
    assert site["license"] == "by-nc"
    item = payload["build"]["items"][0]
    assert item["title"] == "Welcome"
    assert item["slug"] == "welcome"
    assert item["content"] == "<p>Hello</p>"


def test_skeleton_payload_has_no_items() -> None:
    payload = build_create_payload("demo", skeleton="online-course-clean-one")
    build = payload["build"]
    assert build["type"] == "skeleton"
    assert build["structure"] == "from-skeleton"
    assert build["skeletonMachineName"] == "online-course-clean-one"
    assert "items" not in build


def test_home_item_id_is_random_by_default() -> None:
    first = build_home_item("Home", "<p></p>")
    second = build_home_item("Home", "<p></p>")
    assert first["id"].startswith("item-home-")
    assert first["id"] != second["id"]


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Home", "home"),
        ("Welcome", "welcome"),
        ("Lesson 1: Introduction", "lesson-1-introduction"),
        ("  Spaced  Out  ", "spaced-out"),
        ("???", "home"),  # nothing slugifiable falls back to home
        ("Ünïcode Title", "n-code-title"),
    ],
)
def test_home_item_slugifies_the_title(title: str, slug: str) -> None:
    assert build_home_item(title, "<p></p>")["slug"] == slug
