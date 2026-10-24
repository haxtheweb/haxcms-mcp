"""Site lifecycle service (PLAN Phase 2 T2.3; API-REF §3.1-3.5, §9).

Facts this module relies on (Phase 2 live probe of 26.8.1, recorded in PROGRESS.md):

* `POST sites` ignores a `site.title` key — the created site's title equals its machine name.
* `POST sites` with a name that already exists returns 200 and silently creates `<name>-1`;
  the ACTUAL name must be read back from the response (`metadata.site.name` / `location`).
* `POST sites` with an unknown theme returns 400 `"Invalid theme supplied for site creation"`
  (mapped to INVALID_ARGUMENT by the envelope) — and leaves a phantom site registered.
* `POST sites/{name}/clone` returns `{detail: "/_sites/<new>", name: "<new>"}`.
* `POST sites/{name}/archive` returns `{name, archivedName, detail: "Site archived"}`.
* System `GET themes` and `GET skeletons` return LISTS; site summary reads are public.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from haxcms_mcp.client import HaxcmsClient, site_api, system_api
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.models.common import dump_model
from haxcms_mcp.models.site import SiteDetail, SiteListEntry
from haxcms_mcp.models.skeleton import Skeleton, SkeletonMeta
from haxcms_mcp.models.theme import Theme

SITE_NAME_RE = re.compile(r"^[a-z0-9\-_]+$")
DEFAULT_THEME = "clean-one"
DEFAULT_LICENSE = "by-sa"  # the value the HAXcms dashboard sends on create
DEFAULT_PAGE_TITLE = "Home"
DEFAULT_PAGE_CONTENT = "<p></p>"


def validate_site_name(name: str) -> str:
    """Return the trimmed machine name or raise INVALID_ARGUMENT.

    Rejects spaces, uppercase and everything outside ``[a-z0-9-_]`` — the HAXcms dashboard runs
    human input through generateMachineName, the API does not (PLAN Appendix D: ``First`` fails).
    """
    candidate = (name or "").strip()
    if not candidate:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "site name must not be empty",
            hint="names cannot contain spaces; use - or _ between lowercase words",
        )
    if not SITE_NAME_RE.fullmatch(candidate):
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid site name {name!r}",
            hint="names cannot contain spaces; use - or _ (allowed: a-z, 0-9, - and _)",
        )
    return candidate


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug or "home"


def build_home_item(title: str, content: str, *, item_id: str | None = None) -> dict[str, Any]:
    """One JSONOutlineSchemaItem for the blank-site first page (API-REF §3.3 shape)."""
    return {
        "id": item_id or f"item-home-{secrets.token_hex(8)}",
        "title": title,
        "slug": _slugify(title),
        "order": 0,
        "parent": None,
        "indent": 0,
        "content": content,
        "metadata": {"published": True, "hideInMenu": False, "tags": []},
    }


def build_create_payload(
    name: str,
    *,
    description: str = "",
    theme: str = DEFAULT_THEME,
    license: str = DEFAULT_LICENSE,
    skeleton: str | None = None,
    first_page_title: str = DEFAULT_PAGE_TITLE,
    first_page_content: str = DEFAULT_PAGE_CONTENT,
    home_id: str | None = None,
) -> dict[str, Any]:
    """The `POST sites` body (pure function — regression-goldened).

    Blank site: ``build.items`` holds one home item. Skeleton site: ``build.skeletonMachineName``
    and NO items — the skeleton's theme/description/license/pages win over the request.
    """
    site: dict[str, Any] = {
        "name": name,
        "description": description,
        "theme": theme,
        "license": license,
        "domain": None,
    }
    build: dict[str, Any] = {"type": "skeleton", "structure": "from-skeleton"}
    if skeleton is not None:
        build["skeletonMachineName"] = skeleton
    else:
        build["items"] = [build_home_item(first_page_title, first_page_content, item_id=home_id)]
    return {"site": site, "build": build}


def _created_name(data: dict[str, Any], fallback: str) -> str:
    """Actual site name from a create response: metadata.site.name, else the location path."""
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        site_meta = metadata.get("site")
        if isinstance(site_meta, dict) and site_meta.get("name"):
            return str(site_meta["name"])
    location = data.get("location") or data.get("slug")
    if isinstance(location, str) and "/_sites/" in location:
        return location.split("/_sites/", 1)[1].split("/", 1)[0]
    return fallback


def _clone_name(data: dict[str, Any]) -> str:
    """New name from a clone response: `data.name` (verified), else parsed from `data.detail`."""
    name = data.get("name")
    if isinstance(name, str) and name:
        return name
    detail = data.get("detail")
    if isinstance(detail, str) and "/_sites/" in detail:
        return detail.split("/_sites/", 1)[1].split("/", 1)[0]
    raise HaxcmsMcpError(
        ErrorCode.UPSTREAM_ERROR,
        "clone response did not name the new site",
        details={"response": data},
    )


async def list_sites(client: HaxcmsClient) -> list[SiteListEntry]:
    """All sites on the instance (API-REF §3.1; bearer + user token)."""
    listing = await system_api.list_sites(client)
    return listing.items


async def get_site(client: HaxcmsClient, site: str) -> SiteDetail:
    """System site info merged with the public summary (API-REF §3.1 + §3.5 site read)."""
    info = await system_api.site_info(client, site)
    summary: dict[str, Any] | None = None
    warning: str | None = None
    try:
        summary = await site_api.site_summary(client, site)
    except HaxcmsMcpError as exc:  # best-effort: info alone is still a useful answer
        warning = f"public site summary unavailable: {exc.formatted}"
    detail = SiteDetail.from_api(info, summary)
    if warning:
        detail.warnings = [warning]
    return detail


async def create_site(
    client: HaxcmsClient,
    name: str,
    *,
    title: str | None = None,
    description: str = "",
    theme: str = DEFAULT_THEME,
    license: str | None = None,
    skeleton: str | None = None,
    first_page_title: str = DEFAULT_PAGE_TITLE,
    first_page_content: str = DEFAULT_PAGE_CONTENT,
) -> SiteDetail:
    """Create a site and return its merged detail record (API-REF §3.3).

    `theme` is validated against the LIVE system theme list (unknown → INVALID_ARGUMENT before
    any write; hidden themes are allowed with a warning). `skeleton` (machine name from
    `list_skeletons`) switches to from-skeleton creation, where the skeleton's own theme,
    description, license and pages win.
    """
    machine = validate_site_name(name)
    warnings: list[str] = []
    if skeleton is None:
        themes = await list_themes(client)
        record = next((entry for entry in themes if entry.machine_name == theme), None)
        if record is None:
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                f"unknown theme {theme!r}",
                hint="call list_themes for the installed theme machine names",
            )
        if record.hidden:
            warnings.append(f"theme {theme!r} is marked hidden in the registry but was accepted")
    payload = build_create_payload(
        machine,
        description=description,
        theme=theme,
        license=license or DEFAULT_LICENSE,
        skeleton=skeleton,
        first_page_title=first_page_title,
        first_page_content=first_page_content,
    )
    if title is not None:
        payload["site"]["title"] = title
        if title != machine:
            warnings.append(
                f"upstream ignores site.title on create; the site title is the machine name "
                f"{machine!r} (verified Phase 2)"
            )
    data = await system_api.create_site(client, payload)
    actual = _created_name(data, machine)
    if actual != machine:
        warnings.append(
            f"name {machine!r} was already taken; the server created {actual!r} instead"
        )
    detail = await get_site(client, actual)
    if warnings:
        detail.warnings = [*(detail.warnings or []), *warnings]
    return detail


async def create_site_from_skeleton(
    client: HaxcmsClient,
    skeleton: str,
    name: str | None = None,
    *,
    title: str | None = None,
    description: str = "",
) -> SiteDetail:
    """Create a site pre-populated from an installed skeleton (API-REF §9).

    `name` defaults to the skeleton machine name; the skeleton's theme/description/license/pages
    win over anything requested (verified Phase 2: online-course-clean-one yields 5 pages).
    """
    skeleton_name = (skeleton or "").strip()
    if not skeleton_name:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "skeleton machine name must not be empty",
            hint="call list_skeletons for the installed skeleton machine names",
        )
    return await create_site(
        client,
        name if name is not None else skeleton_name,
        title=title,
        description=description,
        skeleton=skeleton_name,
    )


async def clone_site(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """Clone a site (API-REF §3.4) -> `{name, site}` with the NEW name parsed from the response."""
    data = await system_api.clone_site(client, site)
    new_name = _clone_name(data)
    detail = await get_site(client, new_name)
    return {"name": new_name, "site": dump_model(detail)}


async def archive_site(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """Archive a site (API-REF §3.4; destructive) -> `{name, archived_name, detail}`.

    The site leaves `list_sites` and its folder moves under `_archived/` in the HAXcms root;
    archive does NOT delete anything.
    """
    data = await system_api.archive_site(client, site)
    return {
        "name": data.get("name") or site,
        "archived_name": data.get("archivedName"),
        "detail": data.get("detail") or "Site archived",
    }


async def list_themes(client: HaxcmsClient) -> list[Theme]:
    """System theme registry (API-REF §3.5) — the machine names valid for `create_site`."""
    records = await system_api.list_themes(client)
    return [Theme.from_api(record) for record in records]


async def list_skeletons(client: HaxcmsClient) -> list[SkeletonMeta]:
    """Installed skeletons (API-REF §3.5, §9) — grouped by `category` they are the journeys."""
    records = await system_api.list_skeletons(client)
    return [SkeletonMeta.from_api(record) for record in records]


async def get_skeleton(client: HaxcmsClient, name: str) -> Skeleton:
    """Full skeleton detail `{meta, site, build}` (API-REF §3.5)."""
    skeleton_name = (name or "").strip()
    if not skeleton_name:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            "skeleton machine name must not be empty",
            hint="call list_skeletons for the installed skeleton machine names",
        )
    data = await system_api.get_skeleton(client, skeleton_name)
    return Skeleton.from_api(data)
