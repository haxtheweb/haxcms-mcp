"""haxProperties → catalog entry extraction (PLAN Phase 4 T4.4).

Shared by `scripts/extract_hax_properties.py` (generates the bundled catalog from the
26.8.1 public build) and by `CatalogService`'s live merge (refreshes entries from the
server's `GET blocks/{tag}?include=haxProperties` / `GET schemas` responses).

haxProperties shapes handled: the current flat one (`gizmo {title, description}`,
`settings.configure` / `settings.advanced` — entries carry `property` or `slot`,
`inputMethod`, optional `required`, `options` value→label) and the legacy nested one
(`configure.settings.quick` / `.advanced`, entries carry `attribute`).
`demoSchema[0] {tag, properties, content}` rebuilds an `example_html`.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

# inputMethod → catalog attribute type (select entries also carry `enum` from options)
INPUT_METHOD_TYPES = {
    "textfield": "string",
    "textarea": "string",
    "alt": "string",
    "url": "string",
    "haxupload": "string",
    "filepath": "string",
    "colorpicker": "string",
    "iconpicker": "string",
    "datepicker": "string",
    "markup": "string",
    "taglist": "string",
    "array": "string",
    "object": "string",
    "number": "number",
    "range": "number",
    "slider": "number",
    "checkbox": "boolean",
    "boolean": "boolean",
    "select": "string",
    "radio": "string",
}

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def kebab(name: str) -> str:
    """camelCase property → kebab-case HTML attribute (accentColor → accent-color)."""
    return _CAMEL.sub("-", str(name)).lower()


def _settings_groups(props: dict[str, Any]) -> list[Any]:
    """The configure/advanced entry lists from either haxProperties shape."""
    settings = props.get("settings")
    if isinstance(settings, dict) and ("configure" in settings or "advanced" in settings):
        return [settings.get("configure"), settings.get("advanced")]
    configure = props.get("configure")
    if isinstance(configure, dict):
        inner = configure.get("settings")
        if isinstance(inner, dict):
            return [inner.get("quick"), inner.get("advanced")]
    return []


def _unset_names(props: dict[str, Any]) -> set[str]:
    """Attribute names the element itself strips on save (saveOptions.unsetAttributes).

    These are editor-only or derived state (e.g. true-false-question's `_tfanswer`):
    they never survive a saveNode write, so the catalog must not offer them.
    """
    save_options = props.get("saveOptions")
    if isinstance(save_options, dict):
        unset = save_options.get("unsetAttributes")
        if isinstance(unset, list):
            return {kebab(str(name)) for name in unset}
    return set()


def _items_list_enum(entry: dict[str, Any]) -> list[str] | None:
    """Enum values from a radio/select `itemsList` ([{value, text}, ...])."""
    items_list = entry.get("itemsList")
    if not isinstance(items_list, list):
        return None
    values = [
        str(item["value"])
        for item in items_list
        if isinstance(item, dict) and item.get("value") is not None
    ]
    return values or None


def attributes_from_settings(
    props: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(attributes, slots)` extracted from a haxProperties object."""
    attributes: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    seen_attributes: set[str] = set()
    seen_slots: set[str] = set()
    unset = _unset_names(props)
    for group in _settings_groups(props):
        if not isinstance(group, list):
            continue
        for entry in group:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "")
            description = str(entry.get("description") or title)
            if "slot" in entry:
                slot_name = str(entry.get("slot") or "") or "default"
                if slot_name not in seen_slots:
                    seen_slots.add(slot_name)
                    slots.append({"name": slot_name, "description": title})
                continue
            property_name = entry.get("property") or entry.get("attribute")
            if not property_name or not isinstance(property_name, str):
                continue
            name = kebab(property_name)
            if name in seen_attributes or name in unset or name.startswith("_"):
                continue  # duplicates, save-stripped editor state, internal lit props
            seen_attributes.add(name)
            attribute: dict[str, Any] = {
                "name": name,
                "type": INPUT_METHOD_TYPES.get(str(entry.get("inputMethod") or ""), "string"),
                "required": bool(entry.get("required")),
                "description": description,
            }
            options = entry.get("options")
            if isinstance(options, dict) and options:
                attribute["enum"] = [str(key) for key in options]
            else:
                enum = _items_list_enum(entry)
                if enum is not None:
                    attribute["enum"] = enum
            attributes.append(attribute)
    return attributes, slots


def example_from_demo_schema(tag: str, demo_schema: Any) -> str:
    """`<tag attr="...">content</tag>` rebuilt from demoSchema[0] ("" when absent)."""
    if not isinstance(demo_schema, list) or not demo_schema:
        return ""
    demo = demo_schema[0]
    if not isinstance(demo, dict):
        return ""
    attrs: list[str] = []
    properties = demo.get("properties")
    if isinstance(properties, dict):
        for name, value in properties.items():
            if value is True:
                attrs.append(f'{kebab(name)}="{kebab(name)}"')
            elif value is False or value is None:
                continue
            elif isinstance(value, (dict, list)):
                continue  # structured demo properties are not HTML attributes
            else:
                attrs.append(f'{kebab(name)}="{escape(str(value), quote=True)}"')
    opening = f"<{tag}" + (" " + " ".join(attrs) if attrs else "") + ">"
    content = str(demo.get("content") or "")
    return f"{opening}{content}</{tag}>"


def entry_from_hax_properties(tag: str, props: Any) -> dict[str, Any] | None:
    """Catalog entry dict (no category/agent_notes) from haxProperties; None if unusable."""
    if not isinstance(props, dict):
        return None
    gizmo = props.get("gizmo")
    attributes, slots = attributes_from_settings(props)
    entry: dict[str, Any] = {
        "tag": tag,
        "title": str(gizmo.get("title") or "") if isinstance(gizmo, dict) else "",
        "description": str(gizmo.get("description") or "") if isinstance(gizmo, dict) else "",
        "attributes": attributes,
        "slots": slots,
        "example_html": example_from_demo_schema(tag, props.get("demoSchema")),
    }
    return entry
