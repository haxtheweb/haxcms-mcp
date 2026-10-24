"""Phase 6 integration tests: every settings tool against the live instance.

PLAN Phase 6 integration list: `test_p06_settings.py` — each tool changes `site.json` on
disk as expected: title, description, theme element and palette, regions, author, SEO
flags incl. the pathauto toggle affecting a later rename, audience, allowed blocks incl.
rejection of an unknown tag, platform feature off -> FEATURE_DISABLED on delete_page then
back on.

DEVIATION (recorded in PROGRESS.md): PLAN also lists "tags" among the on-disk changes —
`tags` is NOT writable through the 26.8.1 API (the scoped-details PATCH site path writes
only title/homePageId/sw/forceUpgrade; the form path needs an un-mintable
haxcms_form_token), so the tags case asserts UNSUPPORTED and an UNCHANGED site.json.

Live-contract facts pinned from `../haxcms-nodejs` source (read-only):

* `saveNode` regenerates the slug from the title only when `metadata.site.settings.pathauto
  === true` (strict) and the page has no overridePathauto — the toggle test sets the flag
  explicitly both ways instead of relying on the create default.
* `saveAppearanceSettings` stores the palette trimmed+lowercased, normalizes cssVariable
  to `--simple-colors-default-theme-<color>-7`, Set-dedupes region arrays, and a theme
  ELEMENT change replaces the whole metadata.theme (regions reset).
* `saveBlockSettings` stores allowedBlocks deduped+sorted; `savePlatformSettings` has
  REPLACE semantics (the service merges over the current flags); `deletePage: false` makes
  the delete route answer 403 'Delete is disabled for this site'.
* Every manifest write bumps `metadata.site.updated` (epoch seconds) and git-commits.
* Fresh-site defaults (live-probed): top-level `author` is "" and there is a `location`
  key; `metadata.site.git` is `{vendor: github, branch: gh-pages}`; settings are
  `{lang: en-US, publishPagesOn: true, canonical: true, pathauto: true}`; platform is
  `{audience: expert, features: {}, allowedBlocks: []}`; `homePageId` is ABSENT until the
  first manifest write; the theme block is the full registry copy (path, thumbnail,
  supportedPalettes, default variables) without `regions`.
"""

from __future__ import annotations

import pytest

from haxcms_mcp.models.item import Item
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.mcp_client import McpTestClient

pytestmark = pytest.mark.integration


async def test_get_site_settings_matches_disk(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    """The read tool reflects the on-disk manifest (the public site.json is the source)."""
    view = await mcp.call("get_site_settings", site=site)
    manifest = haxcms.read_site_json(site)
    assert view["name"] == site
    assert view["title"] == manifest["title"]
    assert view["theme"]["element"] == manifest["metadata"]["theme"]["element"]
    # a fresh site has no homePageId key at all (live-probed) — both sides must agree
    assert view.get("home_page_id") == manifest["metadata"]["site"].get("homePageId")


async def test_update_site_info_title_description_home_page(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime, page: Item
) -> None:
    """Title/description land in the manifest; home_page pre-resolves slug -> item id."""
    before_updated = haxcms.read_site_json(site)["metadata"]["site"].get("updated") or 0

    view = await mcp.call(
        "update_site_info",
        title="Course Alpha",
        description="An alpha course.",
        home_page=page.slug,
        site=site,
    )
    assert view["title"] == "Course Alpha"
    assert view["description"] == "An alpha course."
    assert view["home_page_id"] == page.id

    manifest = haxcms.read_site_json(site)
    assert manifest["title"] == "Course Alpha"
    assert manifest["description"] == "An alpha course."
    assert manifest["metadata"]["site"]["homePageId"] == page.id
    # every manifest write bumps the epoch-seconds stamp
    assert int(manifest["metadata"]["site"]["updated"]) >= int(before_updated)


async def test_update_site_info_tags_unsupported_site_json_unchanged(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    """DEVIATION from PLAN's integration list: tags fail fast and nothing is written."""
    before = haxcms.read_site_json(site)
    err = await mcp.call_error(
        "update_site_info", tags=["alpha", "beta"], title="Never Applied", site=site
    )
    assert "UNSUPPORTED" in err
    assert "tags" in err
    assert "site.json" in err  # the hint points the Operator at the server-side file
    assert haxcms.read_site_json(site) == before  # not even the bundled title was applied


async def test_set_site_theme_element_palette_accent(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime
) -> None:
    """The element switch and the variables land in metadata.theme in ONE call."""
    view = await mcp.call(
        "set_site_theme",
        theme="learn-two-theme",
        palette=" Learn ",
        accent_color="deep-purple",
        site=site,
    )
    assert view["theme"]["element"] == "learn-two-theme"
    assert view["theme"]["palette"] == "learn"  # trimmed + lowercased upstream
    assert view["theme"]["css_variable"] == "--simple-colors-default-theme-deep-purple-7"
    # the element-reset warning rides along on every theme switch
    assert any("registry defaults" in warning for warning in view["warnings"])

    theme_block = haxcms.read_site_json(site)["metadata"]["theme"]
    assert theme_block["element"] == "learn-two-theme"
    assert theme_block["variables"]["palette"] == "learn"
    assert theme_block["variables"]["cssVariable"] == "--simple-colors-default-theme-deep-purple-7"


async def test_set_theme_regions(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime, page: Item
) -> None:
    """The region array is stored under metadata.theme.regions (page id, not slug)."""
    view = await mcp.call(
        "set_theme_regions", region="sidebarFirst", page_ids=[page.slug], site=site
    )
    assert view["theme"]["regions"]["sidebarFirst"] == [page.id]

    regions = haxcms.read_site_json(site)["metadata"]["theme"]["regions"]
    assert regions["sidebarFirst"] == [page.id]


async def test_update_author_info(mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime) -> None:
    """The author wrapper writes metadata.author; license writes the TOP-LEVEL key."""
    view = await mcp.call(
        "update_author_info",
        name="Ada Lovelace",
        email="ada@example.invalid",
        license="by-nc",
        location="London",
        site=site,
    )
    assert view["author"]["name"] == "Ada Lovelace"
    assert view["author"]["email"] == "ada@example.invalid"
    assert view["license"] == "by-nc"

    manifest = haxcms.read_site_json(site)
    assert manifest["metadata"]["author"]["name"] == "Ada Lovelace"
    assert manifest["metadata"]["author"]["email"] == "ada@example.invalid"
    assert manifest["license"] == "by-nc"


async def test_seo_flags_and_pathauto_toggle(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime, page: Item
) -> None:
    """SEO flags persist verbatim; the pathauto toggle steers a later rename's slug."""
    view = await mcp.call(
        "update_seo_settings",
        lang="es",
        ga_id="G-TEST",
        canonical=True,
        private=False,
        publish_pages_on=True,
        pathauto=False,
        site=site,
    )
    assert view["seo"]["lang"] == "es"
    assert view["seo"]["ga_id"] == "G-TEST"
    assert view["seo"]["canonical"] is True
    assert view["seo"]["publish_pages_on"] is True
    assert view["seo"]["pathauto"] is False

    settings_block = haxcms.read_site_json(site)["metadata"]["site"]["settings"]
    assert settings_block["lang"] == "es"
    assert settings_block["gaID"] == "G-TEST"
    assert settings_block["canonical"] is True
    assert settings_block["publishPagesOn"] is True
    assert settings_block["pathauto"] is False

    # pathauto OFF: renaming the title keeps the slug (saveNode regenerates only when
    # settings.pathauto === true)
    renamed = await mcp.call(
        "update_page_details", page=page.id, title="Renamed While Pathauto Off", site=site
    )
    assert renamed["title"] == "Renamed While Pathauto Off"
    assert renamed["slug"] == page.slug

    # pathauto ON: the next rename regenerates the slug from the title
    await mcp.call("update_seo_settings", pathauto=True, site=site)
    assert haxcms.read_site_json(site)["metadata"]["site"]["settings"]["pathauto"] is True
    renamed = await mcp.call(
        "update_page_details", page=page.id, title="Renamed With Pathauto", site=site
    )
    assert renamed["slug"] == "renamed-with-pathauto"


async def test_set_editor_audience(mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime) -> None:
    view = await mcp.call("set_editor_audience", audience=" Expert ", site=site)
    assert view["platform"]["audience"] == "expert"
    assert haxcms.read_site_json(site)["metadata"]["platform"]["audience"] == "expert"


async def test_allowed_blocks(mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime) -> None:
    """Unknown tags are rejected naming the offender; stored deduped+sorted; null clears."""
    err = await mcp.call_error("set_allowed_blocks", tags=["image", "not-a-real-block"], site=site)
    assert "INVALID_ARGUMENT" in err
    assert "not-a-real-block" in err  # our pre-check names it; the server's 400 is generic

    view = await mcp.call(
        "set_allowed_blocks", tags=["image", "a11y-gif-player", "image"], site=site
    )
    assert view["platform"]["allowed_blocks"] == ["a11y-gif-player", "image"]
    assert haxcms.read_site_json(site)["metadata"]["platform"]["allowedBlocks"] == [
        "a11y-gif-player",
        "image",
    ]

    view = await mcp.call("set_allowed_blocks", site=site)  # tags omitted -> unrestricted
    assert view["platform"].get("allowed_blocks") is None
    assert haxcms.read_site_json(site)["metadata"]["platform"].get("allowedBlocks") is None


async def test_platform_features_gate_delete_page(
    mcp: McpTestClient, site: str, haxcms: HaxcmsRuntime, page: Item
) -> None:
    """T6.5 live: deletePage=False -> delete_page FEATURE_DISABLED; True again -> works."""
    view = await mcp.call("set_platform_features", features={"deletePage": False}, site=site)
    assert view["platform"]["features"]["delete_page"] is False
    assert haxcms.read_site_json(site)["metadata"]["platform"]["features"]["deletePage"] is False

    err = await mcp.call_error("delete_page", page=page.id, site=site)
    assert "FEATURE_DISABLED" in err
    assert "Delete is disabled for this site" in err

    # the page survived the refused delete
    record = await mcp.call("get_page", page=page.id, site=site)
    assert record["id"] == page.id

    view = await mcp.call("set_platform_features", features={"deletePage": True}, site=site)
    assert view["platform"]["features"]["delete_page"] is True
    await mcp.call("delete_page", page=page.id, site=site)
    err = await mcp.call_error("get_page", page=page.id, site=site)
    assert "NOT_FOUND" in err


async def test_regenerate_alternate_formats(mcp: McpTestClient, site: str) -> None:
    """One format, then all; an unknown format is rejected before any request."""
    result = await mcp.call("regenerate_alternate_formats", format=" RSS ", site=site)
    assert result["updated"] is True
    assert result["format"] == "rss"
    assert result["site"]["name"] == site

    result = await mcp.call("regenerate_alternate_formats", site=site)  # None -> all formats
    assert result["updated"] is True

    err = await mcp.call_error("regenerate_alternate_formats", format="atom", site=site)
    assert "INVALID_ARGUMENT" in err
    assert "service-worker" in err  # the hint lists the five valid formats
