"""#3137 stretch / ADR-0005: the generated route layer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from haxcms_mcp.generated import site_routes, system_routes
from haxcms_mcp.generated.route import Route

pytestmark = pytest.mark.unit

GEN_PATH = Path(__file__).resolve().parents[2] / "scripts" / "gen_routes.py"


def _load_generator():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("gen_routes_under_test", GEN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen_routes = _load_generator()


def test_committed_routes_match_the_vendored_specs() -> None:
    assert gen_routes.main(["--check"]) == 0


@pytest.mark.parametrize(
    ("operation_id", "expected"),
    [
        ("getItemByIdOrSlug", "get_item_by_id_or_slug"),
        ("sessionLogin", "session_login"),
        ("updateSiteSeo", "update_site_seo"),
        ("getSiteOpenApiJson", "get_site_open_api_json"),
    ],
)
def test_snake_case_names(operation_id: str, expected: str) -> None:
    assert gen_routes.snake(operation_id) == expected


@pytest.mark.parametrize(
    ("security", "mode"),
    [
        (None, "none"),
        ([], "none"),
        ([{"bearerAuth": []}], "bearer"),
        ([{"bearerAuth": [], "userTokenHeader": []}], "bearer+user"),
        ([{"bearerAuth": [], "siteTokenHeader": []}], "bearer+site"),
    ],
)
def test_auth_mode_from_security(security: object, mode: str) -> None:
    assert gen_routes.auth_mode(security) == mode


def test_site_routes_mount_the_site_and_encode_nested_slugs() -> None:
    route = site_routes.update_item("demo", "unit-1/lesson 2")
    assert route == Route(
        "updateItem", "PATCH", "/_sites/demo/x/api/v1/items/unit-1%2Flesson%202", "bearer+site"
    )


def test_open_site_reads_require_no_auth_by_spec() -> None:
    assert site_routes.list_items("demo").auth == "none"
    assert site_routes.get_site_summary("demo").path == "/_sites/demo/x/api/v1/site"


def test_system_routes() -> None:
    assert system_routes.session_login() == Route(
        "sessionLogin", "POST", "/system/api/v1/session/login", "none"
    )
    assert system_routes.archive_site("my-site").path == "/system/api/v1/sites/my-site/archive"
    assert system_routes.list_sites().auth == "bearer+user"
    assert system_routes.system_skeletons_get().auth == "bearer"


def test_lookup_by_operation_id_refuses_parameterised_routes() -> None:
    assert Route.from_table(system_routes.OPERATIONS, "importDocx").path == (
        "/system/api/v1/actions/import-docx"
    )
    with pytest.raises(ValueError, match="path parameters"):
        Route.from_table(system_routes.OPERATIONS, "cloneSite")


def test_every_import_and_action_the_client_dispatches_exists_in_the_spec() -> None:
    from haxcms_mcp.client.system_api import ACTION_ROUTES, IMPORT_KIND_ROUTES

    for operation_id in [*IMPORT_KIND_ROUTES.values(), *ACTION_ROUTES]:
        assert operation_id in system_routes.OPERATIONS, operation_id
