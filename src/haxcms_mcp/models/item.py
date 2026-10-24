"""Item, ItemMetadata, ItemCollection and OutlineNode models (PLAN Phase 3 T3.1).

Live record shape (API-REF §4.1-4.2; `itemToSummary` in siteRouteUtils.js, read Phase 3):
`GET items` / `GET items/{idOrSlug}` / `PATCH items/{idOrSlug}` all return

```
{ id, title, slug, parent|null, indent, order, location, description, metadata:{...raw...},
  region|null, tags:[...], published:bool, links:{self,content,parent?,children?},
  related:[link-rel objects], content? (with include=content), jsonld? (detail always),
  exports?, haxElementSchema? }
```

`published` is `metadata.published !== false`; `tags` is `metadata.tags` normalised to a list.
`jsonld`, `exports`, `haxElementSchema` and `related` are heavy machine-facing sections the
tools never need — `from_api` drops them. Unknown metadata keys are preserved in
`ItemMetadata.extra` (PLAN T3.1) and round-trip through `to_api` so outline saves never
lose data.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# metadata keys from API-REF §4.1 (+ region, which itemToSummary reads from metadata)
_METADATA_TO_FIELD = {
    "created": "created",
    "updated": "updated",
    "published": "published",
    "locked": "locked",
    "hideInMenu": "hide_in_menu",
    "pageType": "page_type",
    "tags": "tags",
    "relatedItems": "related_items",
    "image": "image",
    "icon": "icon",
    "accentColor": "accent_color",
    "theme": "theme",
    "region": "region",
    "files": "files",
    "images": "images",
    "videos": "videos",
    "overridePathauto": "override_pathauto",
}
_FIELD_TO_METADATA = {field: key for key, field in _METADATA_TO_FIELD.items()}

# heavy record sections from_api drops (see module docstring)
_DROPPED = {"jsonld", "exports", "haxElementSchema", "related"}

_HANDLED = {
    "id",
    "title",
    "slug",
    "parent",
    "indent",
    "order",
    "location",
    "description",
    "metadata",
    "region",
    "tags",
    "published",
    "content",
    "links",
}


def _as_tag_list(value: Any) -> list[str]:
    """metadata.tags is usually a list; manifests also store 'a,b' strings."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(entry) for entry in value]
    return []


class ItemMetadata(BaseModel):
    """The item's `metadata` object: typed known keys + `extra` for everything else."""

    model_config = ConfigDict(extra="forbid")

    created: int | None = None
    updated: int | None = None
    published: bool | None = None
    locked: bool | None = None
    hide_in_menu: bool | None = None
    page_type: str | None = None
    tags: list[str] | None = None
    related_items: list[str] | None = None
    image: str | None = None
    icon: str | None = None
    accent_color: str | None = None
    # saveNode.js stores the FULL theme object ({element, path, ..., key}) for pages with a
    # developer-theme; manifests written by older tooling may carry a bare key string
    theme: dict[str, Any] | str | None = None
    region: str | None = None
    files: list[Any] | None = None
    images: list[str] | None = None
    videos: list[str] | None = None
    override_pathauto: bool | None = None
    extra: dict[str, Any] = {}

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> ItemMetadata:
        known: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in record.items():
            field = _METADATA_TO_FIELD.get(key)
            if field is None:
                extra[key] = value
                continue
            if field == "tags":
                known[field] = _as_tag_list(value)
            elif field in {"related_items", "images", "videos"}:
                known[field] = value if isinstance(value, list) else [value]
            elif field == "files":
                # legacy manifests stored a {uuid: {...}} map; keep it raw in extra
                if isinstance(value, list):
                    known[field] = list(value)
                else:
                    extra[key] = value
            else:
                known[field] = value
        return cls(extra=extra, **known)

    def to_api(self) -> dict[str, Any]:
        """Re-serialize for outbound payloads (camelCase keys, absent fields omitted)."""
        out: dict[str, Any] = {}
        for field, key in _FIELD_TO_METADATA.items():
            value = getattr(self, field)
            if value is not None:
                out[key] = value
        out.update(self.extra)
        return out


class Item(BaseModel):
    """One outline item / page record (API-REF §4.1)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    title: str = ""
    slug: str = ""
    parent: str | None = None
    indent: int = 0
    order: int = 0
    location: str = ""
    description: str = ""
    metadata: ItemMetadata = Field(default_factory=ItemMetadata)
    region: str | None = None
    tags: list[str] | None = None
    published: bool | None = None
    content: str | None = None
    links: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> Item:
        raw_metadata = record.get("metadata")
        metadata = ItemMetadata.from_api(raw_metadata if isinstance(raw_metadata, dict) else {})
        tags = record.get("tags")
        tag_list = _as_tag_list(tags) if tags is not None else metadata.tags
        published = record.get("published")
        if published is None:
            # itemToSummary: published = metadata.published !== false
            published = True if metadata.published is None else metadata.published
        parent = record.get("parent")
        extras = {key: value for key, value in record.items() if key not in _HANDLED | _DROPPED}
        return cls(
            id=str(record.get("id") or ""),
            title=str(record.get("title") or ""),
            slug=str(record.get("slug") or ""),
            parent=str(parent) if parent else None,
            indent=int(record.get("indent") or 0),
            order=int(record.get("order") or 0),
            location=str(record.get("location") or ""),
            description=str(record.get("description") or ""),
            metadata=metadata,
            region=record.get("region"),
            tags=tag_list,
            published=bool(published),
            content=record.get("content"),
            links=record.get("links") if isinstance(record.get("links"), dict) else None,
            **extras,
        )


class ItemCollection(BaseModel):
    """The `GET items` list envelope: `{count, total, page, items}` (API-REF §4.2)."""

    count: int = 0
    total: int = 0
    page: dict[str, Any] = {}
    items: list[Item] = []

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ItemCollection:
        raw_items = data.get("items")
        page = data.get("page")
        return cls(
            count=int(data.get("count") or 0),
            total=int(data.get("total") or 0),
            page=page if isinstance(page, dict) else {},
            items=[Item.from_api(entry) for entry in raw_items if isinstance(entry, dict)]
            if isinstance(raw_items, list)
            else [],
        )


class OutlineNode(BaseModel):
    """One node of the outline tree: an Item plus its children (PLAN T3.1)."""

    item: Item
    children: list[OutlineNode] = []


OutlineNode.model_rebuild()
