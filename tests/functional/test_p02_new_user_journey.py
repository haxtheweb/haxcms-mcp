"""Functional user story for the Phase 2 site tools (PLAN Appendix D tutorial).

"As a new user I create my first site" — expressed only through Tool calls against the live
instance: the human name fails with the machine-name hint, the corrected name succeeds with one
configurable starting page, themes are discoverable, and the online-course skeleton produces the
Syllabus/Lesson journey pages. Ends by archiving through the tool (destructive path included).
"""

from __future__ import annotations

import contextlib

import pytest

from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient
from tests.harness.site_reads import public_titles

pytestmark = pytest.mark.functional

COURSE_SITE = "first-underscore-course"
SKELETON_SITE = "my-online-course"


async def test_new_user_creates_their_first_sites(
    mcp: McpTestClient, haxcms: HaxcmsRuntime
) -> None:
    created: list[str] = []
    try:
        # 1. the tutorial's first attempt: a human name is rejected with a teaching hint
        error = await mcp.call_error("create_site", name="First")
        assert "[INVALID_ARGUMENT]" in error
        assert "cannot contain spaces" in error
        assert "- or _" in error

        # 2. the corrected machine name succeeds, with a configurable first page
        site = await mcp.call(
            "create_site",
            name=COURSE_SITE,
            description="My first course",
            theme="clean-one",
            first_page_title="Welcome",
        )
        created.append(site["name"])
        assert site["name"] == COURSE_SITE
        assert site["description"] == "My first course"
        assert site["page_count"] == 1
        assert site["theme"] == "clean-one"
        assert public_titles(haxcms.base_url, COURSE_SITE) == ["Welcome"]

        # the site shows up in the listing and in get_site
        listing = await mcp.call("list_sites")
        assert COURSE_SITE in [entry["name"] for entry in listing["sites"]]
        assert listing["count"] == len(listing["sites"])
        fetched = await mcp.call("get_site", site=COURSE_SITE)
        assert fetched["name"] == COURSE_SITE
        assert fetched["counts"]["items"] == 1
        assert fetched["links"]["siteApi"].endswith("/x/api")

        # 3. themes are discoverable and clean-one is among them
        themes = await mcp.call("list_themes")
        machines = [theme["machine_name"] for theme in themes["themes"]]
        assert "clean-one" in machines
        assert themes["count"] == len(themes["themes"])

        # 4. skeletons are the ready-made journeys; the course one builds Syllabus + Lesson pages
        skeletons = await mcp.call("list_skeletons")
        categories = {tuple(entry.get("category") or ()) for entry in skeletons["skeletons"]}
        assert any("Course" in category for category in categories)

        skeleton = await mcp.call("get_skeleton", skeleton="online-course-clean-one")
        assert skeleton["meta"]["title"] == "Online Course"

        journey = await mcp.call(
            "create_site_from_skeleton",
            skeleton="online-course-clean-one",
            name=SKELETON_SITE,
        )
        created.append(journey["name"])
        assert journey["name"] == SKELETON_SITE
        assert journey["page_count"] == 5
        titles = public_titles(haxcms.base_url, SKELETON_SITE)
        assert "Syllabus" in titles
        assert any(title.startswith("Lesson 1") for title in titles)

        # 5. cloning makes an editable copy under a new name
        cloned = await mcp.call("clone_site", site=SKELETON_SITE)
        created.append(cloned["name"])
        assert cloned["name"] != SKELETON_SITE
        assert cloned["site"]["page_count"] == 5
    finally:
        # 6. archiving removes the sites from the listing (destructive tool path)
        for name in created:
            # cleanup must not mask the real failure
            with contextlib.suppress(Exception):
                await mcp.call("archive_site", site=name)
    listing = await mcp.call("list_sites")
    names = [entry["name"] for entry in listing["sites"]]
    for name in created:
        assert name not in names
