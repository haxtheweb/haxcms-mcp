"""Skeleton models (PLAN Phase 2 T2.1; API-REF §3.5, §9).

Two live shapes (Phase 2 probe of 26.8.1):

* `GET /system/api/v1/skeletons` — a LIST of flat records: `title`, `description`, `image`,
  `priority`, `category`, `attributes`, `scope`, `machineName` + `machine-name`, `demo-url`,
  `skeleton-url`, `enabled`. (API-REF §3.5 guessed "map"; live it is a list.)
* `GET /system/api/v1/skeletons/{name}` — `{meta:{name, description, version, created, type,
  priority, useCaseTitle, useCaseDescription, useCaseImage, category, tags, attributes},
  site:{name, description, theme}, build:{type, structure, items}}`.

`SkeletonMeta.from_api` accepts either shape; `Skeleton` wraps the detail record.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

_HANDLED = {
    "meta",
    "site",
    "build",
    "theme",
    "machineName",
    "machine-name",
    "name",
    "title",
    "description",
    "useCaseTitle",
    "useCaseDescription",
    "useCaseImage",
    "category",
    "tags",
    "image",
    "priority",
    "hidden",
    "terrible",
    "enabled",
    "scope",
    "demo-url",
    "skeleton-url",
    "attributes",
}


class SkeletonMeta(BaseModel):
    """One skeleton — either a list record or a detail `meta` object."""

    model_config = ConfigDict(extra="allow")

    machine_name: str = ""
    name: str = ""
    title: str = ""
    description: str = ""
    use_case_title: str | None = None
    category: list[str] = []
    tags: list[str] = []
    image: str | None = None
    priority: int | None = None
    hidden: bool | None = None
    terrible: bool | None = None
    enabled: bool | None = None
    scope: str | None = None
    demo_url: str | None = None
    skeleton_url: str | None = None

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> SkeletonMeta:
        category = record.get("category") or []
        if isinstance(category, str):
            category = [category]
        tags = record.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        machine_name = str(record.get("machineName") or record.get("machine-name") or "")
        name = str(record.get("name") or machine_name)
        use_case_title = record.get("useCaseTitle")
        title = str(record.get("title") or use_case_title or name)
        extras = {key: value for key, value in record.items() if key not in _HANDLED}
        return cls(
            machine_name=machine_name or name,
            name=name,
            title=title,
            description=str(record.get("description") or record.get("useCaseDescription") or ""),
            use_case_title=use_case_title,
            category=[str(entry) for entry in category],
            tags=[str(entry) for entry in tags],
            image=record.get("image") or record.get("useCaseImage"),
            priority=record.get("priority"),
            hidden=record.get("hidden"),
            terrible=record.get("terrible"),
            enabled=record.get("enabled"),
            scope=record.get("scope"),
            demo_url=record.get("demo-url"),
            skeleton_url=record.get("skeleton-url"),
            **extras,
        )


class Skeleton(BaseModel):
    """Full skeleton detail from `GET /system/api/v1/skeletons/{name}`."""

    model_config = ConfigDict(extra="allow")

    meta: SkeletonMeta
    site: dict[str, Any] = {}
    build: dict[str, Any] = {}
    theme: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Skeleton:
        meta_raw = data.get("meta")
        meta = SkeletonMeta.from_api(meta_raw if isinstance(meta_raw, dict) else {})
        site = data.get("site")
        build = data.get("build")
        theme = data.get("theme")
        extras = {key: value for key, value in data.items() if key not in _HANDLED}
        return cls(
            meta=meta,
            site=site if isinstance(site, dict) else {},
            build=build if isinstance(build, dict) else {},
            theme=theme if isinstance(theme, dict) else None,
            **extras,
        )
