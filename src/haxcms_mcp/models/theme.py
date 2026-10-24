"""Theme model (PLAN Phase 2 T2.1).

One flexible record covering both shapes observed live (Phase 2 probe):
system `GET /system/api/v1/themes` records (`element`, `path`, `thumbnail`, `category`,
`hidden`, `priority`, `terrible`, `machineName`, `scope`, `enabled`) and site-level
`GET /_sites/{site}/x/api/v1/themes` records (`machineName`, `name`, `description`,
`enabled`, `active`, `hidden`, `screenshot`, `path`, `element`, `supportedPalettes`).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# keys consumed by from_api; anything else is kept as an extra
_HANDLED = {
    "machineName",
    "machine-name",
    "name",
    "description",
    "category",
    "hidden",
    "terrible",
    "priority",
    "enabled",
    "active",
    "element",
    "path",
    "screenshot",
    "thumbnail",
    "supportedPalettes",
    "scope",
    "links",
}


class Theme(BaseModel):
    """One theme record from the system or a site-level theme listing."""

    model_config = ConfigDict(extra="allow")

    machine_name: str
    name: str = ""
    description: str = ""
    category: list[str] = []
    hidden: bool = False
    terrible: bool = False
    priority: int | None = None
    enabled: bool | None = None
    active: bool | None = None
    element: str | None = None
    path: str | None = None
    screenshot: str | None = None
    supported_palettes: list[str] | None = None
    scope: str | None = None

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> Theme:
        category = record.get("category") or []
        if isinstance(category, str):
            category = [category]
        extras = {key: value for key, value in record.items() if key not in _HANDLED}
        return cls(
            machine_name=str(
                record.get("machineName")
                or record.get("machine-name")
                or record.get("element")
                or ""
            ),
            name=str(record.get("name") or ""),
            description=str(record.get("description") or ""),
            category=[str(entry) for entry in category],
            hidden=bool(record.get("hidden") or False),
            terrible=bool(record.get("terrible") or False),
            priority=record.get("priority"),
            enabled=record.get("enabled"),
            active=record.get("active"),
            element=record.get("element"),
            path=record.get("path"),
            screenshot=record.get("screenshot") or record.get("thumbnail"),
            supported_palettes=record.get("supportedPalettes"),
            scope=record.get("scope"),
            **extras,
        )
