"""Site settings tools (PLAN Phase 6 T6.4).

Read the full settings view (public site.json manifest) and write the settings groups
HAXcms NodeJS 26.8.1 exposes: site info, author, theme, regions, SEO, editor audience,
allowed blocks, platform feature flags, alternative formats. All mutations are bearer +
site token; each upstream route has its own feature gate (a disabled gate surfaces as
FEATURE_DISABLED). `configure_site_git` documents the UNSUPPORTED git publishing block.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.config import Settings
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.services import settings as settings_service
from haxcms_mcp.tools._common import resolve_site, tool_annotations


def register_settings_tools(mcp: FastMCP, settings: Settings, client: HaxcmsClient) -> None:
    """Register the eleven Phase 6 settings tools on the FastMCP app."""

    @mcp.tool(annotations=tool_annotations("Get site settings", read_only=True))
    async def get_site_settings(site: str | None = None) -> dict[str, Any]:
        """Read the site's full settings view (parsed from the public site.json manifest).

        Returns: identity (`id`, `name`, `title`, `description`, `license`, `domain`,
        `tags`, `logo`, `home_page_id`, `updated`), `sw`/`force_upgrade`, the `theme`
        block (`element`, `css_variable`, `palette`, `icon`, banner image fields, raw
        `regions`), the `seo` block (`lang`, `ga_id`, `private`, `canonical`, `pathauto`,
        `publish_pages_on`), the `author` block, the `platform` block (`audience`,
        `allowed_blocks` — null means unrestricted — and the 21 `features` flags), and
        the read-only `git` block (`vendor`, `branch`, `auto_push`, `url`). Unknown
        upstream keys are preserved as extras on each block; `warnings` collects anything
        noteworthy. This is the ONLY complete settings read — use it before and after
        any settings change.
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.get_site_settings(client, name)
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Update site info"))
    async def update_site_info(
        title: str | None = None,
        description: str | None = None,
        domain: str | None = None,
        logo: str | None = None,
        home_page: str | None = None,
        tags: list[str] | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Update site-info fields; returns the fresh settings view.

        `title` (HTML tags are stripped upstream), `description`, `domain`, `logo`
        (site-relative path or URL), and `home_page` — a page id or slug (pre-resolved;
        an unknown page fails NOT_FOUND) or "" to CLEAR the home-page setting. At least
        one field is required. WARNING: `tags` is NOT writable through the 26.8.1 API —
        passing it fails UNSUPPORTED before any other field is applied; the Operator must
        edit `metadata.site.tags` in site.json on the server.
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.update_site_info(
            client,
            name,
            title=title,
            description=description,
            domain=domain,
            tags=tags,
            logo=logo,
            home_page=home_page,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Update author info"))
    async def update_author_info(
        license: str | None = None,
        name: str | None = None,
        email: str | None = None,
        image: str | None = None,
        phone: str | None = None,
        location: str | None = None,
        website: str | None = None,
        social_link: str | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Update the author block; returns the fresh settings view.

        Only the fields passed are written. `license` is a Creative Commons identifier
        (e.g. `by-sa`, `by-nc`) and lands on the TOP-LEVEL manifest license (shared with
        the site license). `image` is a path/URL. At least one field is required.
        """
        # `site_name`, not `name`: the local would shadow this tool's author-name
        # parameter (the live suite caught the site machine name in metadata.author.name).
        site_name = resolve_site(site, settings.default_site)
        result = await settings_service.update_author_info(
            client,
            site_name,
            license=license,
            name=name,
            email=email,
            image=image,
            phone=phone,
            location=location,
            website=website,
            social_link=social_link,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Set site theme"))
    async def set_site_theme(
        theme: str,
        palette: str | None = None,
        accent_color: str | None = None,
        icon: str | None = None,
        banner_image: str | None = None,
        banner_alt: str | None = None,
        banner_link: str | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Switch the theme element and set appearance variables in ONE call.

        `theme` must exist in the live registry (list_themes; hidden themes work with a
        warning). WARNING: changing the element REPLACES the whole theme block with the
        registry theme's defaults — palette, accent_color, icon, banner and REGION
        assignments reset — so pass everything you want to keep in the SAME call.
        `accent_color` accepts a bare simple-colors name (`deep-purple`) or the full
        `--simple-colors-default-theme-<color>-7` form; `palette` "" removes the palette;
        `banner_image`/`banner_alt`/`banner_link` set the banner variables. Returns the
        fresh settings view (check its `warnings`).
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.set_site_theme(
            client,
            name,
            theme,
            palette=palette,
            accent_color=accent_color,
            icon=icon,
            banner_image=banner_image,
            banner_alt=banner_alt,
            banner_link=banner_link,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Set theme regions"))
    async def set_theme_regions(
        region: str,
        page_ids: list[str],
        site: str | None = None,
    ) -> dict[str, Any]:
        """Assign pages to one theme region (menus/sidebars/footers); returns fresh settings.

        `region` is one of: header, sidebarFirst, sidebarSecond, contentTop, contentBottom,
        footerPrimary, footerSecondary (exact camelCase). `page_ids` is the FULL replacement
        list for that region — page ids or slugs (each pre-resolved; unknown pages fail
        NOT_FOUND) — and `page_ids=[]` clears the region. Other regions are untouched, but
        note set_site_theme resets ALL regions to the registry defaults.
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.set_theme_regions(client, name, region, page_ids)
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Update SEO settings"))
    async def update_seo_settings(
        description: str | None = None,
        domain: str | None = None,
        logo: str | None = None,
        lang: str | None = None,
        ga_id: str | None = None,
        private: bool | None = None,
        canonical: bool | None = None,
        pathauto: bool | None = None,
        publish_pages_on: bool | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Update the SEO block; returns the fresh settings view.

        Only the fields passed are written; at least one is required. `lang` is a BCP-47
        code (e.g. `en`); `ga_id` a Google Analytics property id; `private` hides the site
        from search; `canonical` toggles canonical URLs; `pathauto` auto-derives page slugs
        from titles (affects create_page/rename_page); `publish_pages_on` toggles publish
        timestamps; `description`/`domain`/`logo` overlap with update_site_info (same
        underlying fields). Gated by the seoManifest feature flag.
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.update_seo_settings(
            client,
            name,
            description=description,
            domain=domain,
            lang=lang,
            ga_id=ga_id,
            canonical=canonical,
            private=private,
            pathauto=pathauto,
            publish_pages_on=publish_pages_on,
            logo=logo,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Set editor audience"))
    async def set_editor_audience(audience: str, site: str | None = None) -> dict[str, Any]:
        """Set the editor audience: `novice` (simplified editor UI) or `expert` (full).

        Stored on metadata.platform.audience. Returns the fresh settings view. Gated by
        the siteManifest feature flag.
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.set_editor_audience(client, name, audience)
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Set allowed blocks"))
    async def set_allowed_blocks(
        tags: list[str] | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Restrict which blocks the editor offers; returns the fresh settings view.

        `tags` is the FULL allow-list (e.g. ["image", "a11y-gif-player", "markdown"]) —
        stored deduped. `tags=null` (omit it) removes the restriction entirely. Dashed
        tags are pre-validated against the instance's web-component registry (an unknown
        tag fails INVALID_ARGUMENT naming it); plain HTML tags (video, img, hr...) pass.
        An empty list is rejected. Gated by the siteManifest feature flag.
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.set_allowed_blocks(client, name, tags)
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Set platform features"))
    async def set_platform_features(
        features: dict[str, bool],
        site: str | None = None,
    ) -> dict[str, Any]:
        """Toggle platform feature flags; returns the fresh settings view (check `warnings`).

        `features` maps canonical camelCase keys to booleans — e.g. {"deletePage": false}.
        Valid keys: addPage, saveAndEdit, deletePage, outlineDesigner, styleGuide,
        insights, siteManifest, themeManifest, authorManifest, seoManifest, pageBreak,
        addBlock, popularGizmos, recentGizmos, contentMap, viewSource, uploadMedia,
        onlineMedia, community, pageTemplates, blockTemplates. Only the flags you pass
        change (the service merges over the current set). A disabled flag makes the
        matching tools fail FEATURE_DISABLED (deletePage -> delete_page, uploadMedia ->
        upload_file, seoManifest -> the SEO tools...). WARNING: siteManifest=false also
        locks the manifest/editor/blocks/platform routes themselves and CANNOT be undone
        through the API — the Operator must edit site.json on the server to recover.
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.set_platform_features(client, name, features)
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Configure site git"))
    async def configure_site_git(
        branch: str | None = None,
        auto_push: bool | None = None,
        remote_url: str | None = None,
        vendor: str | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Configure the site's git publishing settings — ALWAYS fails UNSUPPORTED.

        HAXcms NodeJS 26.8.1 exposes no API route that persists `metadata.site.git`
        (branch, autoPush, remote url, vendor): the reachable scoped manifest route
        writes only title/homePageId/sw/forceUpgrade, and the full form route needs a
        form token no reachable endpoint mints. The Operator must edit
        `metadata.site.git` in the site's site.json on the server directly.
        get_site_settings still REPORTS the current git block (read-only).
        """
        name = resolve_site(site, settings.default_site)
        result = await settings_service.configure_site_git(
            client,
            name,
            branch=branch,
            auto_push=auto_push,
            remote_url=remote_url,
            vendor=vendor,
        )
        return dump_model(result)

    @mcp.tool(annotations=tool_annotations("Regenerate alternate formats"))
    async def regenerate_alternate_formats(
        format: str | None = None,
        site: str | None = None,
    ) -> dict[str, Any]:
        """Rebuild the site's alternative-format files; returns {updated, site, format}.

        `format` is one of: rss, sitemap, search, llms, service-worker — omit it (null)
        to regenerate ALL of them. These files are normally rebuilt automatically on
        publish; this forces a rebuild (e.g. after editing files behind HAXcms's back).
        Not gated by a feature flag.
        """
        name = resolve_site(site, settings.default_site)
        return await settings_service.regenerate_alternate_formats(client, name, format=format)
