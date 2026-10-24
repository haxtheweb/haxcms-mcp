"""Functional user story for the Phase 6 settings tools (PLAN Appendix D tutorial).

"The settings dialog, part 2: themes" — expressed only through Tool calls against the live
instance: switch the tutorial course to `learn-two-theme`, set a palette, an accent color
and an icon in the SAME call (an element switch resets the theme block to registry
defaults), then put the Welcome page into the `sidebarFirst` region; `get_site_settings`
reflects all three, and the on-disk `site.json` agrees.
"""

from __future__ import annotations

import contextlib
import secrets

import pytest

from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.functional

SITE = f"p6-theme-{secrets.token_hex(3)}"


async def test_theme_journey(mcp: McpTestClient, haxcms: HaxcmsRuntime) -> None:
    try:
        course = await mcp.call(
            "create_site", name=SITE, theme="clean-one", first_page_title="Welcome"
        )
        assert course["name"] == SITE

        # baseline: the fresh course is clean-one with no variable overrides
        baseline = await mcp.call("get_site_settings", site=SITE)
        assert baseline["theme"]["element"] == "clean-one"

        outline = await mcp.call("get_outline", site=SITE)
        welcome_id = outline["outline"][0]["item"]["id"]

        # the theme switch bundles palette + accent color + icon: changing the element
        # REPLACES the whole metadata.theme with the registry theme, so anything not in
        # this same call would be lost (the view says so in its warnings)
        themed = await mcp.call(
            "set_site_theme",
            theme="learn-two-theme",
            palette="learn",
            accent_color="deep-purple",
            icon="account",
            site=SITE,
        )
        assert themed["theme"]["element"] == "learn-two-theme"
        assert any("registry defaults" in warning for warning in themed["warnings"])

        # regions are assigned AFTER the switch (the switch reset them)
        await mcp.call("set_theme_regions", region="sidebarFirst", page_ids=[welcome_id], site=SITE)

        # get_site_settings reflects all three: theme, variables, region assignment
        final = await mcp.call("get_site_settings", site=SITE)
        assert final["theme"]["element"] == "learn-two-theme"
        assert final["theme"]["palette"] == "learn"
        assert final["theme"]["css_variable"] == "--simple-colors-default-theme-deep-purple-7"
        assert final["theme"]["icon"] == "account"
        assert final["theme"]["regions"]["sidebarFirst"] == [welcome_id]

        # and the on-disk manifest agrees (the settings dialog writes site.json)
        theme_block = haxcms.read_site_json(SITE)["metadata"]["theme"]
        assert theme_block["element"] == "learn-two-theme"
        assert theme_block["variables"]["palette"] == "learn"
        assert theme_block["variables"]["cssVariable"] == (
            "--simple-colors-default-theme-deep-purple-7"
        )
        assert theme_block["variables"]["icon"] == "account"
        assert theme_block["regions"]["sidebarFirst"] == [welcome_id]
    finally:
        # cleanup must not mask the real failure
        with contextlib.suppress(Exception):
            await mcp.call("archive_site", site=SITE)
