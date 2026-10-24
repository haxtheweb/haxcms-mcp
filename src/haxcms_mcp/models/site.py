"""Site models (PLAN Phase 1 T1.8, Phase 2 T2.1; API-REF §3.1, §3.2).

Live shapes verified by the Phase 2 probe of 26.8.1:

* `GET /system/api/v1/sites/{name}` (site info) `data` keys: `description, id, links, location,
  metadata, name, title`; `metadata` = `{pageCount, created, updated}` (ISO strings); `links` =
  `{self, clone, archive, download, downloadSkeleton, saveAsTemplate, siteApi}`.
* `GET /_sites/{site}/x/api/v1/site` (public summary) `data`: `{id, name, title, description,
  language, basePath, theme, updated, counts:{items, publishedItems, tags, regions, files},
  links}` (site-spec.yaml `SiteSummary`).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SiteListEntry(BaseModel):
    """One entry of `GET /system/api/v1/sites` `data.items`.

    Each item is a site.json without `items`, plus `location`, `slug`, and `metadata.pageCount`;
    the Site Name lives at `metadata.site.name` (API-REF §3.1).
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str
    title: str = ""
    description: str = ""
    slug: str | None = None
    location: str | None = None
    page_count: int | None = None

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> SiteListEntry:
        metadata = item.get("metadata") or {}
        site_meta = metadata.get("site") or {}
        # heavy nested site.json keys are dropped from list entries (kept by SiteDetail);
        # scalar keys like author/license stay as extras
        handled = {
            "title",
            "description",
            "slug",
            "location",
            "metadata",
            "items",
            "theme",
            "build",
            "node",
            "platform",
        }
        extras = {key: value for key, value in item.items() if key not in handled}
        return cls(
            name=str(site_meta.get("name") or item.get("name") or ""),
            title=str(item.get("title") or ""),
            description=str(item.get("description") or ""),
            slug=item.get("slug"),
            location=item.get("location"),
            page_count=metadata.get("pageCount"),
            **extras,
        )


class SiteList(BaseModel):
    """`data` of `GET /system/api/v1/sites`: `{id, title, items}`."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    title: str = ""
    items: list[SiteListEntry] = []

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SiteList:
        items = [SiteListEntry.from_api(item) for item in data.get("items") or []]
        extras = {key: value for key, value in data.items() if key not in {"id", "title", "items"}}
        return cls(id=data.get("id"), title=str(data.get("title") or ""), items=items, **extras)


class SiteCounts(BaseModel):
    """`counts` of the public site summary."""

    model_config = ConfigDict(extra="allow")

    items: int | None = None
    published_items: int | None = None
    tags: int | None = None
    regions: int | None = None
    files: int | None = None

    @classmethod
    def from_api(cls, counts: dict[str, Any]) -> SiteCounts:
        handled = {"items", "publishedItems", "tags", "regions", "files"}
        extras = {key: value for key, value in counts.items() if key not in handled}
        return cls(
            items=counts.get("items"),
            published_items=counts.get("publishedItems"),
            tags=counts.get("tags"),
            regions=counts.get("regions"),
            files=counts.get("files"),
            **extras,
        )


class SiteSummary(BaseModel):
    """`data` of `GET /_sites/{site}/x/api/v1/site` (public; site-spec.yaml `SiteSummary`)."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str = ""
    title: str = ""
    description: str = ""
    language: str | None = None
    base_path: str | None = None
    theme: str | None = None
    updated: str | None = None
    counts: SiteCounts | None = None
    links: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SiteSummary:
        counts = data.get("counts")
        handled = {
            "id",
            "name",
            "title",
            "description",
            "language",
            "basePath",
            "theme",
            "updated",
            "counts",
            "links",
        }
        extras = {key: value for key, value in data.items() if key not in handled}
        return cls(
            id=data.get("id"),
            name=str(data.get("name") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            language=data.get("language"),
            base_path=data.get("basePath"),
            theme=data.get("theme"),
            updated=data.get("updated"),
            counts=SiteCounts.from_api(counts) if isinstance(counts, dict) else None,
            links=data.get("links") if isinstance(data.get("links"), dict) else None,
            **extras,
        )


class SiteInfo(BaseModel):
    """`data` of `GET /system/api/v1/sites/{name}` (bearer + user token)."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str = ""
    title: str = ""
    description: str = ""
    location: str | None = None
    metadata: dict[str, Any] = {}
    links: dict[str, Any] = {}

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SiteInfo:
        handled = {"id", "name", "title", "description", "location", "metadata", "links"}
        extras = {key: value for key, value in data.items() if key not in handled}
        metadata = data.get("metadata")
        links = data.get("links")
        return cls(
            id=data.get("id"),
            name=str(data.get("name") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            location=data.get("location"),
            metadata=metadata if isinstance(metadata, dict) else {},
            links=links if isinstance(links, dict) else {},
            **extras,
        )

    @property
    def page_count(self) -> int | None:
        value = self.metadata.get("pageCount")
        return int(value) if isinstance(value, int) else None


class SiteDetail(BaseModel):
    """Merged view returned by `get_site`: system site info + public summary."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str
    title: str = ""
    description: str = ""
    location: str | None = None
    theme: str | None = None
    language: str | None = None
    page_count: int | None = None
    counts: SiteCounts | None = None
    created: str | None = None
    updated: str | None = None
    links: dict[str, Any] | None = None
    warnings: list[str] | None = None

    @classmethod
    def from_api(cls, info: dict[str, Any], summary: dict[str, Any] | None = None) -> SiteDetail:
        info_model = SiteInfo.from_api(info)
        summary_model = SiteSummary.from_api(summary) if isinstance(summary, dict) else None
        metadata = info_model.metadata
        created = metadata.get("created")
        updated = metadata.get("updated")
        return cls(
            id=info_model.id or (summary_model.id if summary_model else None),
            name=info_model.name or (summary_model.name if summary_model else ""),
            title=info_model.title or (summary_model.title if summary_model else ""),
            description=info_model.description
            or (summary_model.description if summary_model else ""),
            location=info_model.location,
            theme=summary_model.theme if summary_model else None,
            language=summary_model.language if summary_model else None,
            page_count=info_model.page_count,
            counts=summary_model.counts if summary_model else None,
            created=created if isinstance(created, str) else None,
            updated=updated if isinstance(updated, str) else None,
            links=info_model.links or None,
        )
