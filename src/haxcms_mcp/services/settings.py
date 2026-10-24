"""Site settings service (PLAN Phase 6 T6.3; API-REF §7).

Facts this module relies on (source-verified against ../haxcms-nodejs e969655c, recorded in
PROGRESS.md):

* The ONLY complete settings read is the public static `GET /_sites/{site}/site.json` —
  `SiteSummary` (GET site) has no metadata block (deviation from PLAN T6.1/T6.3).
* `PATCH site` is reachable ONLY via the scoped-details path (title / homePageId / sw /
  forceUpgrade); the full form path needs a `haxcms_form_token` no reachable route mints, so
  `tags` is NOT writable (update_site_info fails fast with UNSUPPORTED).
* An invalid `homePageId` is silently DELETED server-side — home_page is pre-resolved through
  `find_page` (id-or-slug -> item id) and "" clears the setting.
* `PATCH site/appearance` enforces strict key allow-lists; changing the theme ELEMENT replaces
  the whole metadata.theme with the registry theme (variables/regions reset) — bundle
  palette/accent_color/icon/banner into the SAME call to keep them.
* `accent_color` normalizes to a bare color name (`deep-purple`); the server stores it as
  `--simple-colors-default-theme-<color>-7`. Palette and color name: `[a-z0-9-]+`.
* `PATCH site/blocks` rejects unknown tags with a GENERIC 400 — dashed tags are pre-validated
  against `GET custom-elements/{tag}` so the error names the offending tag.
* `PATCH site/platform` has REPLACE semantics (features = {} then only the payload keys) —
  the service merges the requested flags over the manifest's current features.
* Feature gates: siteManifest guards the manifest/editor/blocks/platform routes, themeManifest
  the appearance route, seoManifest the SEO route; a 403 "...disabled for this site" (the verb
  varies: "Manifest editing is..." vs "Platform settings are...") maps to FEATURE_DISABLED.
"""

from __future__ import annotations

import re
from typing import Any

from haxcms_mcp.client import HaxcmsClient, site_api
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.settings import FEATURE_FIELD_MAP, SiteSettings
from haxcms_mcp.services.pages import find_page
from haxcms_mcp.services.sites import list_themes

# saveAppearanceSettings.js validRegions (exact camelCase keys).
VALID_REGIONS = (
    "header",
    "sidebarFirst",
    "sidebarSecond",
    "contentTop",
    "contentBottom",
    "footerPrimary",
    "footerSecondary",
)
# savePlatformSettings.js validFeatureKeys (canonical names; legacy aliases are NOT accepted).
VALID_FEATURE_KEYS = tuple(FEATURE_FIELD_MAP)
VALID_AUDIENCES = ("novice", "expert")
ALTERNATE_FORMATS = ("rss", "sitemap", "search", "llms", "service-worker")

CSS_VARIABLE_PREFIX = "--simple-colors-default-theme-"
PALETTE_RE = re.compile(r"^[a-z0-9-]+$")
BLOCK_TAG_RE = re.compile(r"^[a-z][a-z0-9]*$")  # plain HTML tags (dashless)


# --- pure payload builders (regression-goldened in tests/unit/test_p06_payloads.py) -------


def build_scoped_manifest_payload(
    site: str, *, title: str | None = None, home_page_id: str | None = None
) -> dict[str, Any]:
    """The PATCH-site body for the scoped-details path (the only reachable one).

    Scoped detection requires the `manifest` OBJECT; the dash keys are the admin-UI form
    names. `home_page_id` semantics: None = don't touch, "" = clear (the server deletes the
    key), non-empty = an exact manifest.items[].id (the caller pre-resolves slugs — an
    invalid id would be silently deleted upstream).
    """
    manifest_site: dict[str, Any] = {}
    if title is not None:
        manifest_site["manifest-title"] = title
    if home_page_id is not None:
        manifest_site["manifest-metadata-site-homePageId"] = home_page_id
    return {"site": {"name": site}, "manifest": {"site": manifest_site}}


def build_seo_fields(
    *,
    description: str | None = None,
    domain: str | None = None,
    logo: str | None = None,
    lang: str | None = None,
    ga_id: str | None = None,
    private: bool | None = None,
    canonical: bool | None = None,
    pathauto: bool | None = None,
    publish_pages_on: bool | None = None,
) -> dict[str, Any]:
    """The `seo` wrapper of PATCH site/seo — SHORT keys, only the provided ones."""
    fields: dict[str, Any] = {}
    if description is not None:
        fields["description"] = description
    if domain is not None:
        fields["domain"] = domain
    if logo is not None:
        fields["logo"] = logo
    if lang is not None:
        fields["lang"] = lang
    if ga_id is not None:
        fields["gaID"] = ga_id
    if private is not None:
        fields["private"] = bool(private)
    if canonical is not None:
        fields["canonical"] = bool(canonical)
    if pathauto is not None:
        fields["pathauto"] = bool(pathauto)
    if publish_pages_on is not None:
        fields["publishPagesOn"] = bool(publish_pages_on)
    return fields


def build_author_fields(
    *,
    license: str | None = None,
    name: str | None = None,
    email: str | None = None,
    image: str | None = None,
    phone: str | None = None,
    location: str | None = None,
    website: str | None = None,
    social_link: str | None = None,
) -> dict[str, Any]:
    """The `author` wrapper of PATCH site/seo (license writes the top-level manifest key)."""
    fields: dict[str, Any] = {}
    if license is not None:
        fields["license"] = license
    if name is not None:
        fields["name"] = name
    if email is not None:
        fields["email"] = email
    if image is not None:
        fields["image"] = image
    if phone is not None:
        fields["phone"] = phone
    if location is not None:
        fields["location"] = location
    if website is not None:
        fields["website"] = website
    if social_link is not None:
        fields["socialLink"] = social_link
    return fields


def build_appearance_theme(
    *,
    element: str | None = None,
    palette: str | None = None,
    accent_color: str | None = None,
    icon: str | None = None,
    banner_image: str | None = None,
    banner_alt: str | None = None,
    banner_link: str | None = None,
    region: str | None = None,
    region_page_ids: list[str] | None = None,
) -> dict[str, Any]:
    """The `manifest.theme` block of PATCH site/appearance — ONLY the 14 allowed keys.

    `accent_color` is the bare color name (normalize_accent_color); the server stores it as
    `--simple-colors-default-theme-<color>-7`. `palette` "" deletes the key server-side.
    A `region` carries its resolved page-id array (empty list clears the region).
    """
    theme: dict[str, Any] = {}
    if element is not None:
        theme["manifest-metadata-theme-element"] = element
    if palette is not None:
        theme["manifest-metadata-theme-variables-palette"] = palette
    if accent_color is not None:
        theme["manifest-metadata-theme-variables-cssVariable"] = accent_color
    if icon is not None:
        theme["manifest-metadata-theme-variables-icon"] = icon
    if banner_image is not None:
        theme["manifest-metadata-theme-variables-image"] = banner_image
    if banner_alt is not None:
        theme["manifest-metadata-theme-variables-imageAlt"] = banner_alt
    if banner_link is not None:
        theme["manifest-metadata-theme-variables-imageLink"] = banner_link
    if region is not None:
        theme[f"manifest-metadata-theme-regions-{region}"] = list(region_page_ids or [])
    return theme


def merge_platform_features(current: dict[str, Any], requested: dict[str, bool]) -> dict[str, bool]:
    """The FULL flag set for the REPLACE-semantics platform route.

    Current manifest flags pass through (non-boolean values are dropped — the route demands
    strict JSON booleans), then the requested flags win. Absent flags stay absent upstream,
    where platformAllows defaults them to true.
    """
    merged: dict[str, bool] = {}
    for key, value in current.items():
        if isinstance(value, bool):
            merged[key] = value
    merged.update(requested)
    return merged


# --- validators / normalizers --------------------------------------------------------------


def normalize_accent_color(value: str) -> str:
    """Bare color name for cssVariable: accepts `deep-purple` or the full var form."""
    candidate = (value or "").strip().lower()
    if candidate.startswith(CSS_VARIABLE_PREFIX):
        candidate = candidate[len(CSS_VARIABLE_PREFIX) :]
        if candidate.endswith("-7"):
            candidate = candidate[:-2]
    if not candidate or not PALETTE_RE.fullmatch(candidate):
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid accent color {value!r}",
            hint="use a simple-colors name like deep-purple (allowed: a-z, 0-9, -)",
        )
    return candidate


def normalize_palette(value: str) -> str:
    """Trim + lowercase palette name ("" is allowed — it deletes the key server-side)."""
    candidate = (value or "").strip().lower()
    if candidate and not PALETTE_RE.fullmatch(candidate):
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid palette {value!r}",
            hint="palette names allow a-z, 0-9 and - (empty string removes the palette)",
        )
    return candidate


def validate_region(region: str) -> str:
    if region not in VALID_REGIONS:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown region {region!r}",
            hint=f"valid regions: {', '.join(VALID_REGIONS)}",
        )
    return region


def validate_features(features: dict[str, bool]) -> dict[str, bool]:
    """Reject unknown keys and non-boolean values (the route 400s generically otherwise)."""
    if not features:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "at least one feature flag is required",
            hint=f"valid keys: {', '.join(VALID_FEATURE_KEYS)}",
        )
    unknown = [key for key in features if key not in FEATURE_FIELD_MAP]
    if unknown:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown platform feature key(s): {', '.join(sorted(unknown))}",
            hint=f"valid keys: {', '.join(VALID_FEATURE_KEYS)}",
        )
    bad = [key for key, value in features.items() if not isinstance(value, bool)]
    if bad:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"feature values must be booleans, got non-boolean for: {', '.join(sorted(bad))}",
        )
    return dict(features)


def _require_fields(**fields: Any) -> None:
    if all(value is None for value in fields.values()):
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "nothing to update - pass at least one field",
            hint=f"updatable fields: {', '.join(fields)}",
        )


# --- service --------------------------------------------------------------------------------


async def get_site_settings(client: HaxcmsClient, site: str) -> SiteSettings:
    """The full settings view, parsed from the public site.json manifest."""
    manifest = await site_api.fetch_site_manifest(client, site)
    return SiteSettings.from_manifest(manifest)


async def update_site_info(
    client: HaxcmsClient,
    site: str,
    *,
    title: str | None = None,
    description: str | None = None,
    domain: str | None = None,
    tags: list[str] | None = None,
    logo: str | None = None,
    home_page: str | None = None,
) -> SiteSettings:
    """Update the site-info fields; returns the fresh settings view.

    Split across two routes: title/home_page -> the scoped-details PATCH site path;
    description/domain/logo -> PATCH site/seo. `tags` is NOT writable through any reachable
    v1 route (UNSUPPORTED, fail-fast before any write). `home_page` is an id-or-slug
    (pre-resolved to an item id — the server silently deletes an invalid homePageId);
    `home_page=""` clears it.
    """
    if tags is not None:
        raise HaxcmsMcpError(
            ErrorCode.UNSUPPORTED,
            "site tags cannot be written through the v1 API",
            hint=(
                "the only route writing metadata.site.tags needs a haxcms_form_token that no "
                "reachable endpoint mints (HAXcms NodeJS 26.8.1); edit site.json on the server"
            ),
        )
    _require_fields(
        title=title, description=description, domain=domain, logo=logo, home_page=home_page
    )
    seo_fields = build_seo_fields(description=description, domain=domain, logo=logo)
    if seo_fields:
        await site_api.update_seo(client, site, seo=seo_fields)
    home_page_id: str | None = None
    if home_page is not None:
        candidate = home_page.strip()
        if candidate:
            item = await find_page(client, site, candidate)
            if not item.id:
                raise HaxcmsMcpError(
                    ErrorCode.UPSTREAM_ERROR,
                    f"page {candidate!r} resolved without an id",
                )
            home_page_id = item.id
        else:
            home_page_id = ""  # empty clears the setting (server deletes the key)
    if title is not None or home_page_id is not None:
        payload = build_scoped_manifest_payload(site, title=title, home_page_id=home_page_id)
        await site_api.update_manifest(client, site, payload)
    return await get_site_settings(client, site)


async def update_author_info(
    client: HaxcmsClient,
    site: str,
    *,
    license: str | None = None,
    name: str | None = None,
    email: str | None = None,
    image: str | None = None,
    phone: str | None = None,
    location: str | None = None,
    website: str | None = None,
    social_link: str | None = None,
) -> SiteSettings:
    """Update the author tab (PATCH site/seo `author` wrapper); returns the fresh view.

    `license` writes the top-level manifest license; empty strings clear fields. The
    upstream website2/socialLink2 keys are intentionally not exposed (PLAN scope).
    """
    _require_fields(
        license=license,
        name=name,
        email=email,
        image=image,
        phone=phone,
        location=location,
        website=website,
        social_link=social_link,
    )
    author = build_author_fields(
        license=license,
        name=name,
        email=email,
        image=image,
        phone=phone,
        location=location,
        website=website,
        social_link=social_link,
    )
    await site_api.update_seo(client, site, author=author)
    return await get_site_settings(client, site)


async def set_site_theme(
    client: HaxcmsClient,
    site: str,
    theme: str,
    *,
    palette: str | None = None,
    accent_color: str | None = None,
    icon: str | None = None,
    banner_image: str | None = None,
    banner_alt: str | None = None,
    banner_link: str | None = None,
) -> SiteSettings:
    """Switch the theme and set appearance variables in ONE call; returns the fresh view.

    `theme` is validated against the LIVE system registry (unknown -> INVALID_ARGUMENT;
    hidden themes are allowed with a warning, mirroring create_site). Changing the element
    RESETS variables/regions to the new theme's registry defaults — pass palette /
    accent_color / icon / banner_* in the same call to keep them. `accent_color` accepts a
    bare name (deep-purple) or the full --simple-colors-default-theme-<color>-7 form.
    """
    element = (theme or "").strip()
    if not element:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "theme must not be empty",
            hint="call list_themes for the installed theme machine names",
        )
    themes = await list_themes(client)
    record = next((entry for entry in themes if entry.machine_name == element), None)
    if record is None:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown theme {theme!r}",
            hint="call list_themes for the installed theme machine names",
        )
    warnings: list[str] = []
    if record.hidden:
        warnings.append(f"theme {element!r} is marked hidden in the registry but was accepted")
    warnings.append(
        "changing the theme element resets theme variables and regions to the new theme's "
        "registry defaults - pass palette/accent_color/icon/banner in the SAME call to keep them"
    )
    theme_payload = build_appearance_theme(
        element=element,
        palette=normalize_palette(palette) if palette is not None else None,
        accent_color=(normalize_accent_color(accent_color) if accent_color is not None else None),
        icon=icon,
        banner_image=banner_image,
        banner_alt=banner_alt,
        banner_link=banner_link,
    )
    await site_api.update_appearance(client, site, theme_payload)
    settings = await get_site_settings(client, site)
    settings.warnings = warnings
    return settings


async def set_theme_regions(
    client: HaxcmsClient, site: str, region: str, page_ids: list[str]
) -> SiteSettings:
    """Assign pages to one theme region; returns the fresh view.

    `region` is one of the seven camelCase names; `page_ids` are ids-or-slugs (each
    pre-resolved to an item id — the appearance route stores the array as sent) and
    `page_ids=[]` clears the region. Other regions are untouched.
    """
    validate_region(region)
    resolved: list[str] = []
    for page in page_ids:
        item = await find_page(client, site, str(page).strip())
        if not item.id:
            raise HaxcmsMcpError(ErrorCode.UPSTREAM_ERROR, f"page {page!r} resolved without an id")
        resolved.append(item.id)
    theme_payload = build_appearance_theme(region=region, region_page_ids=resolved)
    await site_api.update_appearance(client, site, theme_payload)
    return await get_site_settings(client, site)


async def update_seo_settings(
    client: HaxcmsClient,
    site: str,
    *,
    description: str | None = None,
    domain: str | None = None,
    lang: str | None = None,
    ga_id: str | None = None,
    canonical: bool | None = None,
    private: bool | None = None,
    pathauto: bool | None = None,
    publish_pages_on: bool | None = None,
    logo: str | None = None,
) -> SiteSettings:
    """Update the SEO tab (PATCH site/seo `seo` wrapper); returns the fresh view.

    description writes the top-level manifest description; domain/logo write
    metadata.site.*; lang/gaID and the four booleans write metadata.site.settings.*.
    Only the provided keys are sent (the route writes present keys only).
    """
    _require_fields(
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
    seo = build_seo_fields(
        description=description,
        domain=domain,
        logo=logo,
        lang=lang,
        ga_id=ga_id,
        private=private,
        canonical=canonical,
        pathauto=pathauto,
        publish_pages_on=publish_pages_on,
    )
    await site_api.update_seo(client, site, seo=seo)
    return await get_site_settings(client, site)


async def set_editor_audience(client: HaxcmsClient, site: str, audience: str) -> SiteSettings:
    """Set metadata.platform.audience ('novice' shows the simplified editor UI)."""
    candidate = (audience or "").strip().lower()
    if candidate not in VALID_AUDIENCES:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid audience {audience!r}",
            hint=f"valid values: {', '.join(VALID_AUDIENCES)}",
        )
    await site_api.update_editor(client, site, candidate)
    return await get_site_settings(client, site)


async def set_allowed_blocks(
    client: HaxcmsClient, site: str, tags: list[str] | None
) -> SiteSettings:
    """Restrict (or with `tags=None` unrestrict) the blocks offered in the editor.

    Each tag must be a plain dashless HTML tag (^[a-z][a-z0-9]*$) or an existing
    custom-element tag (dashed tags are pre-validated against GET custom-elements/{tag}
    because the route 400s generically). The server stores the list deduped + sorted.
    """
    if tags is None:
        await site_api.update_allowed_blocks(client, site, None)
        return await get_site_settings(client, site)
    cleaned: list[str] = []
    for tag in tags:
        candidate = str(tag).strip()
        if not candidate:
            raise HaxcmsMcpError(ErrorCode.INVALID_ARGUMENT, "block tags must not be empty")
        if candidate in cleaned:
            continue
        cleaned.append(candidate)
    for candidate in cleaned:
        if BLOCK_TAG_RE.fullmatch(candidate):
            continue  # plain HTML tag - always allowed
        try:
            await site_api.get_custom_element(client, site, candidate)
        except HaxcmsMcpError as exc:
            if exc.code is ErrorCode.NOT_FOUND:
                raise HaxcmsMcpError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"unknown block tag {candidate!r}",
                    hint=(
                        "plain tags must match ^[a-z][a-z0-9]*$; dashed custom-element tags "
                        "must exist in the registry (list_blocks / get_block)"
                    ),
                ) from exc
            raise
    await site_api.update_allowed_blocks(client, site, cleaned)
    return await get_site_settings(client, site)


async def set_platform_features(
    client: HaxcmsClient, site: str, features: dict[str, bool]
) -> SiteSettings:
    """Set platform feature flags; returns the fresh view (with lockout warnings).

    `features` keys come from the 21 validFeatureKeys (canonical camelCase; legacy aliases
    rejected); values must be booleans. The upstream route REPLACES the whole feature set,
    so the service merges the request over the manifest's current flags. WARNING:
    siteManifest=False also disables the platform route itself (FEATURE_DISABLED) — it
    cannot be re-enabled through the API afterwards.
    """
    requested = validate_features(features)
    warnings: list[str] = []
    if requested.get("siteManifest") is False:
        warnings.append(
            "siteManifest=False disables the manifest, editor, blocks AND platform routes "
            "themselves - they will return FEATURE_DISABLED and cannot be re-enabled through "
            "the API (edit site.json on the server to recover)"
        )
    if requested.get("themeManifest") is False:
        warnings.append(
            "themeManifest=False makes set_site_theme/set_theme_regions return FEATURE_DISABLED "
            "until it is re-enabled"
        )
    if requested.get("seoManifest") is False:
        warnings.append(
            "seoManifest=False makes update_seo_settings/update_author_info (and the SEO "
            "fields of update_site_info) return FEATURE_DISABLED until it is re-enabled"
        )
    manifest = await site_api.fetch_site_manifest(client, site)
    metadata = manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    platform = metadata.get("platform")
    platform = platform if isinstance(platform, dict) else {}
    current = platform.get("features")
    current = current if isinstance(current, dict) else {}
    merged = merge_platform_features(current, requested)
    await site_api.update_platform(client, site, merged)
    settings = await get_site_settings(client, site)
    if warnings:
        settings.warnings = warnings
    return settings


async def regenerate_alternate_formats(
    client: HaxcmsClient, site: str, format: str | None = None
) -> dict[str, Any]:
    """Rebuild the alternative-format files (rss/sitemap/search/llms/service-worker).

    `format=None` regenerates ALL formats. Response `{updated, site: {name}, format}`.
    """
    fmt: str | None = None
    if format is not None:
        fmt = format.strip().lower()
        if fmt not in ALTERNATE_FORMATS:
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                f"unknown alternative format {format!r}",
                hint=f"valid formats: {', '.join(ALTERNATE_FORMATS)} (or omit for all)",
            )
    return await site_api.update_alternative_formats(client, site, fmt)


async def configure_site_git(
    client: HaxcmsClient,
    site: str,
    *,
    branch: str | None = None,
    auto_push: bool | None = None,
    remote_url: str | None = None,
    vendor: str | None = None,
) -> SiteSettings:
    """Git publishing settings (metadata.site.git) — UNSUPPORTED in HAXcms NodeJS 26.8.1.

    Source-verified: the reachable scoped-details `PATCH site` path writes ONLY title /
    homePageId / sw / forceUpgrade; `manifest-metadata-site-git-*` keys are not part of it,
    and the full form path that would write them needs a `haxcms_form_token` that no
    reachable route mints (`validateRequestToken` only passes when
    `haxcms_middleware=node-cli`, which the served instance is not). So this always raises
    UNSUPPORTED without touching the network; `get_site_settings` still REPORTS the current
    git block. Live-probed in tests/integration/test_p06_git.py.
    """
    raise HaxcmsMcpError(
        ErrorCode.UNSUPPORTED,
        "HAXcms NodeJS 26.8.1 exposes no API for the git publishing settings",
        hint=(
            "the Operator must edit metadata.site.git in the site's site.json on the "
            "server; get_site_settings reports the current git block"
        ),
    )
