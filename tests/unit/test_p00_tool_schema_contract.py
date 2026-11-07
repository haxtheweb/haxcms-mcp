"""Contract tests over EVERY registered tool's MCP listing (PLAN §5).

regression/test_p00_snapshots.py pins the exact schemas; these tests assert the
invariants any MCP client relies on, so a new tool cannot break them without a red test
even when its snapshot is regenerated: each input/output schema is a valid JSON Schema
(Draft 2020-12, the dialect MCP specifies), `required` only names declared properties,
every tool documents itself and carries a complete annotation set, read-only tools are
never marked destructive, the `site` argument is always optional (Default Site
addressing, PLAN §2.4), and a call missing a required argument is refused by schema
validation before any HTTP request is made.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError
from jsonschema import Draft202012Validator
from mcp_types import Tool

from haxcms_mcp.config import Settings
from haxcms_mcp.server import build_server

pytestmark = pytest.mark.unit

BASE = "http://hax.invalid"


def make_settings(**kwargs: object) -> Settings:
    return Settings(base_url=BASE, **kwargs)  # type: ignore[arg-type]


async def list_tools() -> list[Tool]:
    async with Client(build_server(make_settings())) as client:
        return list(await client.list_tools())


@pytest.fixture(scope="module")
async def tools() -> list[Tool]:
    listed = await list_tools()
    assert len(listed) > 100  # sanity: the whole registry, not a partial build
    return listed


async def test_tool_names_are_unique_snake_case(tools: list[Tool]) -> None:
    names = [tool.name for tool in tools]
    assert len(names) == len(set(names))
    for name in names:
        assert name.replace("_", "").isalnum(), name
        assert name == name.lower(), name


async def test_every_input_schema_is_a_valid_object_schema(tools: list[Tool]) -> None:
    problems: list[str] = []
    for tool in tools:
        schema: dict[str, Any] = dict(tool.input_schema)
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001 - collect every offender, then fail once
            problems.append(f"{tool.name}: {exc}")
            continue
        if schema.get("type") != "object":
            problems.append(f"{tool.name}: input schema type is {schema.get('type')!r}")
        properties = schema.get("properties") or {}
        undeclared = set(schema.get("required") or []) - set(properties)
        if undeclared:
            problems.append(f"{tool.name}: required names undeclared {sorted(undeclared)}")
        for prop, prop_schema in properties.items():
            if not isinstance(prop_schema, dict) or not prop_schema:
                problems.append(f"{tool.name}.{prop}: empty property schema")
    assert problems == []


async def test_every_output_schema_is_valid_when_present(tools: list[Tool]) -> None:
    problems: list[str] = []
    for tool in tools:
        if tool.output_schema is None:
            continue
        try:
            Draft202012Validator.check_schema(dict(tool.output_schema))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{tool.name}: {exc}")
    assert problems == []


async def test_every_tool_is_documented_and_fully_annotated(tools: list[Tool]) -> None:
    problems: list[str] = []
    for tool in tools:
        if not (tool.description or "").strip():
            problems.append(f"{tool.name}: no description")
        annotations = tool.annotations
        if annotations is None:
            problems.append(f"{tool.name}: no annotations")
            continue
        if not (annotations.title or "").strip():
            problems.append(f"{tool.name}: no annotation title")
        hints = {
            "read_only_hint": annotations.read_only_hint,
            "destructive_hint": annotations.destructive_hint,
            "idempotent_hint": annotations.idempotent_hint,
            "open_world_hint": annotations.open_world_hint,
        }
        for hint, value in hints.items():
            if not isinstance(value, bool):
                problems.append(f"{tool.name}: {hint} is {value!r}, not a bool")
        if annotations.read_only_hint and annotations.destructive_hint:
            problems.append(f"{tool.name}: read-only AND destructive")
    assert problems == []


async def test_site_argument_is_always_optional(tools: list[Tool]) -> None:
    """Default Site addressing (PLAN §2.4): no tool may require `site`."""
    with_site = [tool for tool in tools if "site" in (tool.input_schema.get("properties") or {})]
    assert with_site, "expected site-scoped tools"
    problems = [
        tool.name for tool in with_site if "site" in (tool.input_schema.get("required") or [])
    ]
    assert problems == []
    for tool in with_site:
        site_schema = tool.input_schema["properties"]["site"]
        # `site=None` must validate: it means "use the Default Site"
        Draft202012Validator(site_schema).validate(None)


async def test_missing_required_arguments_are_refused_before_any_http(
    tools: list[Tool],
) -> None:
    required_tools = [tool for tool in tools if tool.input_schema.get("required")]
    assert required_tools
    unrefused: list[str] = []
    # unmatched requests are answered (and recorded) instead of raising, so a tool that
    # reached the wire would show up in router.calls
    with respx.mock(assert_all_called=False, assert_all_mocked=False) as router:
        # the instance publishes "MCP enabled, writable", so the read-only gate lets every
        # call through to schema validation (and the policy is cached, not re-fetched)
        router.get(f"{BASE}/system/api/v1").mock(
            return_value=httpx.Response(
                200, json={"status": 200, "data": {"mcp": {"enabled": True, "readOnly": False}}}
            )
        )
        async with Client(build_server(make_settings(default_site="demo"))) as client:
            for tool in required_tools:
                try:
                    await client.call_tool(tool.name, {})
                except ToolError as exc:
                    text = str(exc)
                    missing = tool.input_schema["required"][0]
                    if missing not in text:
                        unrefused.append(f"{tool.name}: {text[:120]}")
                else:
                    unrefused.append(f"{tool.name}: accepted an empty call")
        other_requests = [
            call.request.url.path
            for call in router.calls
            if call.request.url.path != "/system/api/v1"
        ]
    assert unrefused == []
    # nothing but the policy probe (and the best-effort spec probe) touched the wire
    assert [path for path in other_requests if "/openapi" not in path] == []
