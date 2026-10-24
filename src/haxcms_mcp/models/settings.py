"""Site settings models (PLAN Phase 6 T6.1).

Live shapes source-verified against `../haxcms-nodejs` (e969655c), recorded in PROGRESS.md:

* `SiteSettings` is a view over the PUBLIC STATIC manifest `GET /_sites/{site}/site.json`
  (raw JSON, no `{status, data}` envelope). DEVIATION from PLAN T6.1 ("view over
  `SiteSummary.metadata`"): the public `GET site` summary carries no metadata block, and the
  system `GET sites/{name}` metadata is only `{pageCount, created, updated}`.
* manifest map: `title`/`description`/`license` top-level; `metadata.site.{name, domain,
  tags, logo, homePageId, updated, settings.{lang, gaID, private, canonical, pathauto,
  publishPagesOn, sw, forceUpgrade}, git.{vendor, branch, autoPush, url}}`;
  `metadata.theme.{element, variables.{cssVariable, palette, icon, image, imageAlt,
  imageLink}, regions.{header, sidebarFirst, sidebarSecond, contentTop, contentBottom,
  footerPrimary, footerSecondary}}`; `metadata.author.{image, name, email, phone, location,
  website, website2, socialLink, socialLink2}`; `metadata.platform.{audience, features
  (the 21 validFeatureKeys as strict booleans), allowedBlocks (sorted list, or null =
  unrestricted)}`.
* `SeoSettings` mirrors the SEO tab: description (top-level in the manifest), domain/logo
  (metadata.site), lang/gaID + the four booleans (metadata.site.settings) — exactly the
  fields `PATCH site/seo` writes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

_TRUE_STRINGS = {"1", "true", "yes", "on"}
_FALSE_STRINGS = {"0", "false", "no", "off"}


def _flag(value: Any) -> bool | None:
    """Lenient boolean mirror of the server's parseBooleanFromInput (None when unparseable)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return None


def _manifest_dicts(manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(metadata.site, metadata.site.settings) of a manifest, each {} when absent/invalid."""
    metadata = manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    site_meta = metadata.get("site")
    site_meta = site_meta if isinstance(site_meta, dict) else {}
    settings = site_meta.get("settings")
    settings = settings if isinstance(settings, dict) else {}
    return site_meta, settings


class GitSettings(BaseModel):
    """`metadata.site.git` — read-only view (no v1 route writes it; see configure_site_git)."""

    model_config = ConfigDict(extra="allow")

    vendor: str | None = None
    branch: str | None = None
    auto_push: bool | None = None
    url: str | None = None

    @classmethod
    def from_api(cls, git: dict[str, Any]) -> GitSettings:
        handled = {"vendor", "branch", "autoPush", "url"}
        extras = {key: value for key, value in git.items() if key not in handled}
        return cls(
            vendor=git.get("vendor"),
            branch=git.get("branch"),
            auto_push=_flag(git.get("autoPush")),
            url=git.get("url"),
            **extras,
        )


class ThemeSettings(BaseModel):
    """`metadata.theme` — element, the six appearance variables, and the region map."""

    model_config = ConfigDict(extra="allow")

    element: str | None = None
    css_variable: str | None = None
    palette: str | None = None
    icon: str | None = None
    image: str | None = None
    image_alt: str | None = None
    image_link: str | None = None
    regions: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, theme: dict[str, Any]) -> ThemeSettings:
        variables = theme.get("variables")
        variables = variables if isinstance(variables, dict) else {}
        regions = theme.get("regions")
        handled_vars = {"cssVariable", "palette", "icon", "image", "imageAlt", "imageLink"}
        handled_theme = {"element", "variables", "regions"}
        extras = {key: value for key, value in theme.items() if key not in handled_theme}
        extras.update({key: value for key, value in variables.items() if key not in handled_vars})
        return cls(
            element=theme.get("element"),
            css_variable=variables.get("cssVariable"),
            palette=variables.get("palette"),
            icon=variables.get("icon"),
            image=variables.get("image"),
            image_alt=variables.get("imageAlt"),
            image_link=variables.get("imageLink"),
            regions=regions if isinstance(regions, dict) else None,
            **extras,
        )


class SeoSettings(BaseModel):
    """The SEO tab: exactly the fields `PATCH site/seo` writes (plus settings extras)."""

    model_config = ConfigDict(extra="allow")

    description: str | None = None
    domain: str | None = None
    logo: str | None = None
    lang: str | None = None
    ga_id: str | None = None
    private: bool | None = None
    canonical: bool | None = None
    pathauto: bool | None = None
    publish_pages_on: bool | None = None

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> SeoSettings:
        site_meta, settings = _manifest_dicts(manifest)
        # sw/forceUpgrade belong to the manifest scoped-details path, not the SEO route;
        # they surface flat on SiteSettings and stay out of the seo block's extras.
        handled = {
            "lang",
            "gaID",
            "private",
            "canonical",
            "pathauto",
            "publishPagesOn",
            "sw",
            "forceUpgrade",
        }
        extras = {key: value for key, value in settings.items() if key not in handled}
        description = manifest.get("description")
        return cls(
            description=str(description) if description else None,
            domain=site_meta.get("domain"),
            logo=site_meta.get("logo"),
            lang=settings.get("lang"),
            ga_id=settings.get("gaID"),
            private=_flag(settings.get("private")),
            canonical=_flag(settings.get("canonical")),
            pathauto=_flag(settings.get("pathauto")),
            publish_pages_on=_flag(settings.get("publishPagesOn")),
            **extras,
        )


class AuthorSettings(BaseModel):
    """`metadata.author` — the author tab `PATCH site/seo` writes (license lives top-level)."""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    email: str | None = None
    image: str | None = None
    phone: str | None = None
    location: str | None = None
    website: str | None = None
    website2: str | None = None
    social_link: str | None = None
    social_link2: str | None = None

    @classmethod
    def from_api(cls, author: dict[str, Any]) -> AuthorSettings:
        handled = {
            "name",
            "email",
            "image",
            "phone",
            "location",
            "website",
            "website2",
            "socialLink",
            "socialLink2",
        }
        extras = {key: value for key, value in author.items() if key not in handled}
        return cls(
            name=author.get("name"),
            email=author.get("email"),
            image=author.get("image"),
            phone=author.get("phone"),
            location=author.get("location"),
            website=author.get("website"),
            website2=author.get("website2"),
            social_link=author.get("socialLink"),
            social_link2=author.get("socialLink2"),
            **extras,
        )


# savePlatformSettings.js validFeatureKeys (the 21 flags the platform tab exposes).
FEATURE_FIELD_MAP = {
    "addPage": "add_page",
    "saveAndEdit": "save_and_edit",
    "deletePage": "delete_page",
    "outlineDesigner": "outline_designer",
    "styleGuide": "style_guide",
    "insights": "insights",
    "siteManifest": "site_manifest",
    "themeManifest": "theme_manifest",
    "authorManifest": "author_manifest",
    "seoManifest": "seo_manifest",
    "pageBreak": "page_break",
    "addBlock": "add_block",
    "popularGizmos": "popular_gizmos",
    "recentGizmos": "recent_gizmos",
    "contentMap": "content_map",
    "viewSource": "view_source",
    "uploadMedia": "upload_media",
    "onlineMedia": "online_media",
    "community": "community",
    "pageTemplates": "page_templates",
    "blockTemplates": "block_templates",
}


class PlatformFeatures(BaseModel):
    """`metadata.platform.features` — the 21 feature flags (unknown keys kept as extras)."""

    model_config = ConfigDict(extra="allow")

    add_page: bool | None = None
    save_and_edit: bool | None = None
    delete_page: bool | None = None
    outline_designer: bool | None = None
    style_guide: bool | None = None
    insights: bool | None = None
    site_manifest: bool | None = None
    theme_manifest: bool | None = None
    author_manifest: bool | None = None
    seo_manifest: bool | None = None
    page_break: bool | None = None
    add_block: bool | None = None
    popular_gizmos: bool | None = None
    recent_gizmos: bool | None = None
    content_map: bool | None = None
    view_source: bool | None = None
    upload_media: bool | None = None
    online_media: bool | None = None
    community: bool | None = None
    page_templates: bool | None = None
    block_templates: bool | None = None

    @classmethod
    def from_api(cls, features: dict[str, Any]) -> PlatformFeatures:
        values: dict[str, Any] = {}
        extras: dict[str, Any] = {}
        for key, value in features.items():
            field = FEATURE_FIELD_MAP.get(key)
            if field is None:
                extras[key] = value
            else:
                values[field] = _flag(value)
        return cls(**values, **extras)


class PlatformSettings(BaseModel):
    """`metadata.platform` — audience, allowedBlocks, and the feature flags."""

    model_config = ConfigDict(extra="allow")

    audience: str | None = None
    allowed_blocks: list[str] | None = None
    features: PlatformFeatures | None = None

    @classmethod
    def from_api(cls, platform: dict[str, Any]) -> PlatformSettings:
        allowed = platform.get("allowedBlocks")
        features = platform.get("features")
        handled = {"audience", "allowedBlocks", "features"}
        extras = {key: value for key, value in platform.items() if key not in handled}
        return cls(
            audience=platform.get("audience"),
            allowed_blocks=([str(tag) for tag in allowed] if isinstance(allowed, list) else None),
            features=PlatformFeatures.from_api(features) if isinstance(features, dict) else None,
            **extras,
        )


class SiteSettings(BaseModel):
    """The full settings view `get_site_settings` returns (parsed from site.json)."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str = ""
    title: str = ""
    description: str = ""
    license: str | None = None
    domain: str | None = None
    tags: list[str] | None = None
    logo: str | None = None
    home_page_id: str | None = None
    sw: bool | None = None
    force_upgrade: bool | None = None
    updated: int | str | None = None
    theme: ThemeSettings | None = None
    seo: SeoSettings | None = None
    author: AuthorSettings | None = None
    platform: PlatformSettings | None = None
    git: GitSettings | None = None
    warnings: list[str] | None = None

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> SiteSettings:
        metadata = manifest.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        site_meta, settings = _manifest_dicts(manifest)
        theme = metadata.get("theme")
        author = metadata.get("author")
        platform = metadata.get("platform")
        git = site_meta.get("git")
        tags = site_meta.get("tags")
        updated = site_meta.get("updated")
        # `items` is the full page outline (huge, and already served by list_pages). The
        # JSON Outline Schema top-level `author` ("" on fresh sites — live-probed) shares
        # the name of the parsed metadata.author view, so declared field names never
        # reach **extras; harmless top-level extras like `location` are preserved.
        handled = {"id", "name", "title", "description", "license", "metadata", "items"}
        extras = {
            key: value
            for key, value in manifest.items()
            if key not in handled and key not in cls.model_fields
        }
        return cls(
            id=manifest.get("id"),
            name=str(site_meta.get("name") or manifest.get("name") or ""),
            title=str(manifest.get("title") or ""),
            description=str(manifest.get("description") or ""),
            license=manifest.get("license"),
            domain=site_meta.get("domain"),
            tags=[str(tag) for tag in tags] if isinstance(tags, list) else None,
            logo=site_meta.get("logo"),
            home_page_id=site_meta.get("homePageId"),
            sw=_flag(settings.get("sw")),
            force_upgrade=_flag(settings.get("forceUpgrade")),
            updated=updated if isinstance(updated, (int, str)) else None,
            theme=ThemeSettings.from_api(theme) if isinstance(theme, dict) else None,
            seo=SeoSettings.from_manifest(manifest),
            author=AuthorSettings.from_api(author) if isinstance(author, dict) else None,
            platform=(PlatformSettings.from_api(platform) if isinstance(platform, dict) else None),
            git=GitSettings.from_api(git) if isinstance(git, dict) else None,
            **extras,
        )
